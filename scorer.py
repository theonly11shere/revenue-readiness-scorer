
# Create the corrected scorer.py with all Market Doppelgänger features
scorer_code = '''#!/usr/bin/env python3
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

# ═══════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════

MAX_PAGES_FREE = 3
MAX_PAGES_PAID = 10
MIN_PAGES_PER_TEMPLATE_PAID = 2
REQUEST_TIMEOUT = 15
MAX_DOWNLOAD_SIZE = 5 * 1024 * 1024  # 5MB
PLAYWRIGHT_TIMEOUT = 30

TEMPLATE_PATTERNS = {
    r"/product[s]?/": "product",
    r"/shop/": "product",
    r"/store/": "product",
    r"/service[s]?/": "service",
    r"/about[-us]?/": "about",
    r"/contact[-us]?/": "contact",
    r"/blog/": "blog",
    r"/news/": "blog",
    r"/portfolio/": "portfolio",
    r"/gallery/": "portfolio",
    r"/testimonial[s]?/": "testimonial",
    r"/review[s]?/": "testimonial",
    r"/pricing/": "pricing",
    r"/faq/": "faq",
    r"/team/": "team",
    r"/career[s]?/": "career",
    r"/privacy/": "policy",
    r"/terms/": "policy",
    r"/cookie/": "policy",
}

JS_FRAMEWORK_SIGNATURES = {
    "react": "React",
    "vue": "Vue",
    "angular": "Angular",
    "next.js": "Next.js",
    "nuxt": "Nuxt",
    "gatsby": "Gatsby",
    "svelte": "Svelte",
}

# ═══════════════════════════════════════════════════════════
# TEMPLATE FINGERPRINTER
# ═══════════════════════════════════════════════════════════

class TemplateFingerprinter:
    """Detect CMS / theme / builder signatures in scraped HTML and CSS."""

    SIGNATURES = [
        ("WordPress Astra", "wordpress", ["ast-container", "ast-", "astra-"], 1_200_000),
        ("WordPress Elementor", "wordpress", ["elementor-", "elementor/"], 5_000_000),
        ("WordPress Divi", "wordpress", ["et_pb_", "divi-"], 800_000),
        ("WordPress Avada", "wordpress", ["avada-", "fusion-"], 700_000),
        ("Shopify Dawn", "shopify", ["shopify-section", "shopify-dawn"], 2_000_000),
        ("Shopify Prestige", "shopify", ["prestige-", "shopify-prestige"], 400_000),
        ("Wix", "wix", ["wix-", "static.wixstatic.com"], 3_000_000),
        ("Squarespace", "squarespace", ["squarespace-", "static1.squarespace.com"], 1_500_000),
        ("Webflow", "webflow", ["w-webflow-badge", "webflow-"], 600_000),
        ("Bootstrap", "framework", ["bootstrap", "container-fluid", "row", "col-"], 10_000_000),
        ("Tailwind", "framework", ["tailwind", "bg-", "text-", "flex", "grid-cols-"], 8_000_000),
        ("AI Builder / Generic", "ai", ["ai-generated", "auto-generated", "template-"], 500_000),
    ]

    def __init__(self):
        self.matched = []
        self.total_weight = 0

    def fingerprint(self, html: str) -> Dict[str, Any]:
        if not html or len(html) < 100:
            return self._custom_result()

        html_lower = html.lower()
        matched = []

        for name, platform, signatures, popularity in self.SIGNATURES:
            hits = 0
            for sig in signatures:
                if sig.lower() in html_lower:
                    hits += 1
            if hits > 0:
                weight = hits * popularity
                matched.append((name, weight, platform, hits))

        if not matched:
            return self._custom_result()

        # Sort by weight (most hits × popularity)
        matched.sort(key=lambda x: x[1], reverse=True)

        # Calculate generic score
        total_weight = sum(m[1] for m in matched)
        popularity_boost = min(total_weight / 10_000_000, 5)
        generic_score = min(50 + int(popularity_boost * 10), 98)

        # Build detected template name
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

    GENERIC_PHRASES = [
        "leverage our", "synergy", "digital landscape", "unlock the power",
        "innovative solutions", "passionate about", "driven by excellence",
        "cutting-edge", "next-generation", "holistic approach",
        "best-in-class", "world-class", "industry-leading",
        "transform your", "empower your", "elevate your",
        "seamless experience", "end-to-end", "turnkey solution",
        "scalable platform", "robust framework", "streamlined process",
        "customer-centric", "data-driven", "results-oriented",
        "proven track record", "trusted by", "all-in-one",
        "ecosystem", "bandwidth", "our story", "mission is to",
        "committed to delivering", "dedicated to providing",
        "we pride ourselves", "excellence in everything",
    ]

    def check(self, text: str) -> Dict[str, Any]:
        if not text or len(text) < 50:
            return {"score": 0, "matched_phrases": [], "sites_with_same_voice": 0}

        text_lower = text.lower()
        matched = []

        for phrase in self.GENERIC_PHRASES:
            if phrase in text_lower:
                matched.append(phrase)

        # Score: 0-100 based on density of clichés
        word_count = len(text.split())
        if word_count == 0:
            return {"score": 0, "matched_phrases": [], "sites_with_same_voice": 0}

        density = len(matched) / max(len(self.GENERIC_PHRASES), 1)
        score = min(int(density * 200), 98)  # Cap at 98

        # Estimate sites with same voice (rough heuristic)
        sites_with_same_voice = round(score * 37 / 100) * 100

        return {
            "score": score,
            "matched_phrases": matched[:10],  # Show top 10
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

    def _color_distance(self, c1: str, c2: str) -> float:
        try:
            r1, g1, b1 = self._hex_to_rgb(c1)
            r2, g2, b2 = self._hex_to_rgb(c2)
            return ((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) ** 0.5 / 441.67
        except:
            return 1.0

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

        # Extract CSS classes
        classes = re.findall(r'class=["\\']([^"\\']+)["\\']', self.html)
        all_classes = []
        for c in classes:
            all_classes.extend(c.split())

        class_counts = Counter(all_classes)

        # Check against known template signatures
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
# REVENUE SCORER (Original)
# ═══════════════════════════════════════════════════════════

class RevenueScorer:
    """Calculate revenue readiness scores from scraped data."""

    def __init__(self, data: Dict[str, Any]):
        self.data = data
        self.scores: Dict[str, int] = {}
        self.completed_checks = 0

    def calculate_scores(self) -> None:
        """Calculate readiness, evidence, and confidence scores."""
        # Count completed checks
        categories = ["trust", "conversion", "seo", "content", "technical"]
        total_checks = 0
        completed = 0

        for cat in categories:
            cat_data = self.data.get(cat, {})
            if isinstance(cat_data, dict):
                total_checks += len(cat_data)
                completed += sum(1 for v in cat_data.values() if v is True or (isinstance(v, (int, float)) and v > 0))

        self.completed_checks = completed

        # Calculate readiness score
        max_score = 100
        if total_checks > 0:
            readiness = int((completed / total_checks) * 100)
        else:
            readiness = 0

        self.scores = {
            "readiness_score": min(readiness, 100),
            "evidence_coverage": min(int((completed / max(1, 35)) * 100), 100),
            "confidence_score": min(int((completed / max(1, 35)) * 100), 100),
        }

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

