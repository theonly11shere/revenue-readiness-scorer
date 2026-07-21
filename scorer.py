#!/usr/bin/env python3
"""
Revenue Readiness Scorer — Core scoring engine + Market Doppelgänger features.
"""

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config import (
    MAX_PAGES_FREE, MAX_PAGES_PAID, MIN_PAGES_PER_TEMPLATE_PAID,
    REQUEST_TIMEOUT, MAX_DOWNLOAD_SIZE, PLAYWRIGHT_TIMEOUT,
    TEMPLATE_PATTERNS, JS_FRAMEWORK_SIGNATURES,
    GENERIC_PHRASES, TEMPLATE_SIGNATURES, COMPLAINT_KEYWORDS,
    TOTAL_CHECKS, SEVERITY, FUTURE_PREDICTIONS,
    FAILURE_SEVERITY_BY_WEIGHT,
)


# ═══════════════════════════════════════════════════════════
# TEMPLATE FINGERPRINTER
# ═══════════════════════════════════════════════════════════

class TemplateFingerprinter:
    """Detect CMS / theme / builder signatures in scraped HTML and CSS."""

    def fingerprint(self, html: str) -> Dict[str, Any]:
        if not html or len(html) < 100:
            return self._custom_result()

        html_lower = html.lower()
        matched = []

        for name, platform, signatures, popularity in TEMPLATE_SIGNATURES:
            hits = 0
            for sig in signatures:
                if sig.lower() in html_lower:
                    hits += 1
            if hits > 0:
                weight = hits * popularity
                matched.append((name, weight, platform, hits))

        if not matched:
            return self._custom_result()

        matched.sort(key=lambda x: x[1], reverse=True)
        total_weight = sum(m[1] for m in matched)
        popularity_boost = min(total_weight / 10_000_000, 5)
        generic_score = min(50 + int(popularity_boost * 10), 98)

        names = [m[0] for m in matched[:3]]
        platforms = list(set([m[2] for m in matched]))
        detected_template = " + ".join(names) if names else "Generic / Templated"
        is_custom = generic_score < 40
        sites_using_similar = sum(m[1] for m in matched) // 100

        return {
            "generic_score": generic_score,
            "detected_template": detected_template,
            "platforms": platforms,
            "sites_using_similar": sites_using_similar,
            "is_custom": is_custom,
            "matched_signatures": len(matched),
        }

    def _custom_result(self) -> Dict[str, Any]:
        return {
            "generic_score": 10,
            "detected_template": "Custom / Unknown",
            "platforms": [],
            "sites_using_similar": 0,
            "is_custom": True,
            "matched_signatures": 0,
        }


# ═══════════════════════════════════════════════════════════
# CONTENT SAMENESS CHECKER
# ═══════════════════════════════════════════════════════════

class ContentSamenessChecker:
    """Detect generic, overused business / AI clichés in page text."""

    def check(self, text: str) -> Dict[str, Any]:
        if not text or len(text) < 50:
            return {"score": 0, "matched_phrases": [], "sites_with_same_voice": 0}

        text_lower = text.lower()
        matched = []

        for phrase in GENERIC_PHRASES:
            if phrase in text_lower:
                matched.append(phrase)

        word_count = len(text.split())
        if word_count == 0:
            return {"score": 0, "matched_phrases": [], "sites_with_same_voice": 0}

        density = len(matched) / max(len(GENERIC_PHRASES), 1)
        score = min(int(density * 200), 98)
        sites_with_same_voice = round(score * 37 / 100) * 100

        return {
            "score": score,
            "matched_phrases": matched[:10],
            "sites_with_same_voice": sites_with_same_voice,
        }


# ═══════════════════════════════════════════════════════════
# VISUAL TWIN MATCHER
# ═══════════════════════════════════════════════════════════

class VisualTwinMatcher:
    """Match visual fingerprints against a database of previous scans."""

    def __init__(self, fingerprint: Dict[str, Any]):
        self.fingerprint = fingerprint
        self.fp_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "fingerprints.jsonl"
        )

    def _hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        if len(hex_color) == 3:
            hex_color = "".join([c * 2 for c in hex_color])
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    def _vectorize(self, fp: Dict[str, Any]) -> List[float]:
        vec = []
        colors = fp.get("dominant_colors", [])
        for c in colors[:3]:
            try:
                r, g, b = self._hex_to_rgb(c)
                vec.extend([r / 255.0, g / 255.0, b / 255.0])
            except:
                vec.extend([0.0, 0.0, 0.0])
        while len(vec) < 9:
            vec.extend([0.0, 0.0, 0.0])

        fonts = fp.get("font_families", [])
        vec.append(len(fonts) / 5.0)

        layout = fp.get("layout_ratios", {})
        vec.append(layout.get("hero", 0) / 1.0)
        vec.append((layout.get("grid_columns", 0) or 0) / 6.0)
        vec.append((layout.get("sections", 0) or 0) / 20.0)
        return vec

    def _distance(self, v1: List[float], v2: List[float]) -> float:
        return sum((a - b) ** 2 for a, b in zip(v1, v2)) ** 0.5

    def _similarity(self, dist: float) -> int:
        return max(0, min(100, int(100 - dist * 33)))

    def _matching_elements(self, fp1: Dict, fp2: Dict) -> List[str]:
        elements = []
        c1 = set(fp1.get("dominant_colors", []))
        c2 = set(fp2.get("dominant_colors", []))
        shared_colors = c1 & c2
        if shared_colors:
            elements.append(f"color {list(shared_colors)[0]}")

        f1 = set(fp1.get("font_families", []))
        f2 = set(fp2.get("font_families", []))
        shared_fonts = f1 & f2
        if shared_fonts:
            elements.append(f"font {list(shared_fonts)[0]}")

        l1 = fp1.get("layout_ratios", {})
        l2 = fp2.get("layout_ratios", {})
        if l1.get("has_hero") and l2.get("has_hero"):
            elements.append("hero layout")
        if l1.get("has_grid") and l2.get("has_grid"):
            elements.append(f"{l1.get('grid_columns', 0)}-column grid")
        if l1.get("sections", 0) and l2.get("sections", 0):
            elements.append(f"{min(l1['sections'], l2['sections'])} similar sections")

        return elements[:5]

    def match(self) -> Dict[str, Any]:
        my_vec = self._vectorize(self.fingerprint)
        my_url = self.fingerprint.get("url", "").lower().rstrip("/")

        closest = None
        closest_dist = float("inf")
        closest_fp = None

        if os.path.exists(self.fp_file):
            try:
                with open(self.fp_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            existing = json.loads(line)
                            existing_url = existing.get("url", "").lower().rstrip("/")
                            if existing_url == my_url or not existing_url:
                                continue
                            existing_vec = self._vectorize(existing)
                            dist = self._distance(my_vec, existing_vec)
                            if dist < closest_dist:
                                closest_dist = dist
                                closest = existing_url
                                closest_fp = existing
                        except:
                            continue
            except:
                pass

        if closest is None or closest_fp is None:
            return {
                "similarity_percent": 0,
                "closest_match_url": None,
                "matching_elements": [],
            }

        similarity = self._similarity(closest_dist)
        elements = self._matching_elements(self.fingerprint, closest_fp)

        return {
            "similarity_percent": similarity,
            "closest_match_url": closest,
            "matching_elements": elements,
        }

    def save(self) -> None:
        try:
            with open(self.fp_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(self.fingerprint) + "\\n")
        except:
            pass


# ═══════════════════════════════════════════════════════════
# COPYCAT INDEX SCORER
# ═══════════════════════════════════════════════════════════

class CopycatIndexScorer:
    """Score how 'template-y' a site is based on CSS class signatures."""

    def __init__(self, html: str):
        self.html = html.lower() if html else ""

    def score(self) -> Dict[str, Any]:
        if not self.html:
            return {
                "copycat_index": 0,
                "template_match": "Unknown / Custom",
                "matched_classes": [],
            }

        classes = re.findall(r'class=["\']([^"\']+)["\']', self.html)
        all_classes = []
        for c in classes:
            all_classes.extend(c.split())

        class_counts = Counter(all_classes)

        template_signatures = {
            "WordPress Astra": ["ast-container", "ast-row", "ast-col"],
            "WordPress Elementor": ["elementor-section", "elementor-column"],
            "WordPress Divi": ["et_pb_section", "et_pb_row"],
            "Shopify Dawn": ["shopify-section", "section-header"],
            "Bootstrap": ["container", "row", "col-md", "col-lg"],
            "Tailwind": ["flex", "grid", "bg-", "text-", "p-", "m-"],
        }

        matches = []
        for template, sigs in template_signatures.items():
            hits = sum(class_counts.get(s, 0) for s in sigs)
            if hits > 0:
                matches.append((template, hits))

        if not matches:
            return {
                "copycat_index": 10,
                "template_match": "Unknown / Custom",
                "matched_classes": [],
            }

        matches.sort(key=lambda x: x[1], reverse=True)
        top_template = matches[0][0]
        total_hits = sum(m[1] for m in matches)
        copycat_index = min(50 + total_hits * 2, 98)
        matched_classes = [m[0] for m in matches[:3]]

        return {
            "copycat_index": copycat_index,
            "template_match": top_template,
            "matched_classes": matched_classes,
        }


# ═══════════════════════════════════════════════════════════
# SOCIAL SIGNALS FETCHER
# ═══════════════════════════════════════════════════════════

class SocialSignalsFetcher:
    """Measures REAL public conversation about a brand on Reddit."""

    def __init__(self, brand: str, domain: str):
        self.brand = brand.lower()
        self.domain = domain.lower()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; TrillokaBot/1.0)"})

    def scan(self, max_signals: int = 4, own: bool = False) -> Dict[str, Any]:
        try:
            posts = self._search_reddit([self.brand, self.domain], per_query=8)
        except Exception:
            posts = []

        mentions: List[str] = []
        complaints: List[str] = []
        for post in posts:
            data = post.get("data", {})
            title = data.get("title", "") or ""
            selftext = data.get("selftext", "") or ""
            subreddit = data.get("subreddit", "") or ""
            blob = (title + " " + selftext).lower()
            if not title or (self.brand not in blob and self.domain not in blob):
                continue
            entry = f'Reddit r/{subreddit}: "{title[:80]}..."'
            mentions.append(entry)
            if any(kw in blob for kw in COMPLAINT_KEYWORDS):
                complaints.append(entry)

        total = len(mentions)
        positive = [m for m in mentions if m not in complaints]

        if own:
            return {
                "mentions_found": total,
                "complaints_found": len(complaints),
                "verdict": "own",
                "verdict_label": "Home turf — the Architect's own domain",
                "signals": [],
                "positive_examples": [],
                "negative_examples": [],
            }

        if total == 0:
            verdict, verdict_label = "invisible", "No public conversation found — invisible online"
        elif total <= 3:
            verdict, verdict_label = "quiet", "Barely discussed online"
        else:
            verdict, verdict_label = "discussed", "People are talking about this business"

        signals = (complaints + positive)[:max_signals]

        return {
            "mentions_found": total,
            "complaints_found": len(complaints),
            "verdict": verdict,
            "verdict_label": verdict_label,
            "signals": signals,
            "positive_examples": positive[:3],
            "negative_examples": complaints[:3],
        }

    def _search_reddit(self, queries: List[str], per_query: int = 5) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for query in queries:
            try:
                response = self.session.get(
                    "https://www.reddit.com/search.json",
                    params={"q": query, "limit": per_query, "sort": "new"},
                    timeout=5,
                )
                if response.status_code == 200:
                    results.extend(response.json().get("data", {}).get("children", []))
            except Exception:
                continue
        return results


# ═══════════════════════════════════════════════════════════
# REVENUE SCORER (Three-Score System)
# ═══════════════════════════════════════════════════════════

class RevenueScorer:
    """Calculate revenue readiness scores from scraped data."""

    def __init__(self, data: Dict[str, Any]):
        self.data = data
        self.scores: Dict[str, int] = {}
        self.completed_checks = 0

    def calculate_scores(self) -> Dict[str, int]:
        """Calculate readiness, evidence, and confidence scores."""
        categories = ["trust", "conversion", "seo", "content", "technical"]
        total_checks = 0
        completed = 0
        high_value_complete = 0

        for cat in categories:
            cat_data = self.data.get(cat, {})
            if isinstance(cat_data, dict):
                total_checks += len(cat_data)
                cat_completed = sum(1 for v in cat_data.values() if v is True or (isinstance(v, (int, float)) and v > 0))
                completed += cat_completed
                # High-value categories: trust and conversion
                if cat in ["trust", "conversion"] and cat_completed >= 3:
                    high_value_complete += 1

        self.completed_checks = completed

        readiness = int((completed / max(total_checks, 1)) * 100) if total_checks > 0 else 0
        evidence = int((completed / max(TOTAL_CHECKS, 1)) * 100)
        confidence = int((high_value_complete / 2) * 100) if high_value_complete > 0 else int((completed / max(TOTAL_CHECKS, 1)) * 50)

        self.scores = {
            "readiness_score": min(readiness, 100),
            "evidence_coverage": min(evidence, 100),
            "confidence_score": min(confidence, 100),
        }
        return self.scores

    def get_scores(self) -> Dict[str, int]:
        return self.scores

    def get_readiness_score(self) -> int:
        return self.scores.get("readiness_score", 0)

    def get_top_failures(self, n: int = 10) -> List[Dict[str, Any]]:
        """Get top failures sorted by severity."""
        failures = []
        severity_order = {"critical": 3, "high": 2, "medium": 1, "low": 0}

        categories = ["trust", "conversion", "seo", "content", "technical"]
        for cat in categories:
            cat_data = self.data.get(cat, {})
            if isinstance(cat_data, dict):
                for key, value in cat_data.items():
                    if value is False or value == 0 or value is None:
                        severity = "high" if cat in ["conversion", "trust"] else "medium"
                        failures.append({
                            "category": cat,
                            "item": key,
                            "severity": severity,
                            "one_liner": f"{key.replace('_', ' ').title()} is missing or below threshold.",
                            "completed": False,
                        })

        failures.sort(key=lambda x: severity_order.get(x["severity"], 0), reverse=True)
        return failures[:n]
