#!/usr/bin/env python3
"""Revenue Readiness Scorer — Core scoring engine + real Visual Twin."""
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
    TEMPLATE_PATTERNS, JS_FRAMEWORK_SIGNATURES,
    GENERIC_PHRASES, TEMPLATE_SIGNATURES, COMPLAINT_KEYWORDS,
    TOTAL_CHECKS, SEVERITY, FUTURE_PREDICTIONS,
    FAILURE_SEVERITY_BY_WEIGHT, SCREENSHOT_DIR, VISUAL_TWIN_MIN_SIMILARITY,
)

# Try to import SSIM; fallback to simple pixel diff if not available
try:
    from skimage.metrics import structural_similarity as ssim
    from PIL import Image
    import numpy as np
    _SSIM_AVAILABLE = True
except Exception:
    _SSIM_AVAILABLE = False


class TemplateFingerprinter:
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


class ContentSamenessChecker:
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


class VisualTwinMatcher:
    """Real visual twin using screenshot SSIM comparison + side-by-side generation."""

    def __init__(self, fingerprint: Dict[str, Any]):
        self.fingerprint = fingerprint
        self.fp_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fingerprints.jsonl")
        self.screenshot_dir = SCREENSHOT_DIR
        os.makedirs(self.screenshot_dir, exist_ok=True)

    def _compare_screenshots(self, path1: str, path2: str) -> Optional[float]:
        if not _SSIM_AVAILABLE or not os.path.exists(path1) or not os.path.exists(path2):
            return None
        try:
            img1 = np.array(Image.open(path1).convert("L").resize((400, 300)))
            img2 = np.array(Image.open(path2).convert("L").resize((400, 300)))
            score, _ = ssim(img1, img2, full=True)
            return float(score)
        except Exception:
            return None

    def _create_side_by_side(self, path1: str, path2: str, label1: str, label2: str) -> Optional[str]:
        """Create a side-by-side comparison image of two screenshots."""
        if not _SSIM_AVAILABLE:
            return None
        try:
            img1 = Image.open(path1).convert("RGB")
            img2 = Image.open(path2).convert("RGB")

            # Resize both to same height
            target_height = 600
            w1, h1 = img1.size
            w2, h2 = img2.size
            img1 = img1.resize((int(w1 * target_height / h1), target_height))
            img2 = img2.resize((int(w2 * target_height / h2), target_height))

            # Create combined image with labels
            from PIL import ImageDraw, ImageFont
            label_height = 30
            border = 4
            total_width = img1.width + img2.width + border
            total_height = target_height + label_height

            combined = Image.new("RGB", (total_width, total_height), (20, 20, 20))
            draw = ImageDraw.Draw(combined)

            # Try to load a font, fallback to default
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
            except Exception:
                font = ImageFont.load_default()

            # Paste images
            combined.paste(img1, (0, label_height))
            combined.paste(img2, (img1.width + border, label_height))

            # Draw labels
            draw.text((10, 5), label1, fill=(255, 255, 255), font=font)
            draw.text((img1.width + border + 10, 5), label2, fill=(255, 255, 255), font=font)

            # Draw border between images
            draw.rectangle([img1.width, label_height, img1.width + border, total_height], fill=(255, 255, 255))

            # Save
            domain = self.fingerprint.get("domain", "unknown")
            out_name = f"twin_compare_{domain}_{int(datetime.now().timestamp())}.png"
            out_path = os.path.join(self.screenshot_dir, out_name)
            combined.save(out_path)
            return out_path
        except Exception as e:
            print(f"[VisualTwinMatcher] Side-by-side creation failed: {e}")
            return None

    def match(self) -> Dict[str, Any]:
        my_url = self.fingerprint.get("url", "").lower().rstrip("/")
        my_domain = self.fingerprint.get("domain", "").lower()
        # Try screenshot_path first, then screenshot for backward compat
        my_screenshot = self.fingerprint.get("screenshot_path") or self.fingerprint.get("screenshot")

        if not my_screenshot or not os.path.exists(my_screenshot):
            return self._fallback_match()

        closest = None
        closest_score = -1.0
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
                            existing_domain = existing.get("domain", "").lower()
                            # Skip self-match
                            if existing_url == my_url or existing_domain == my_domain or not existing_url:
                                continue
                            existing_ss = existing.get("screenshot_path") or existing.get("screenshot")
                            if existing_ss and os.path.exists(existing_ss):
                                ssim_score = self._compare_screenshots(my_screenshot, existing_ss)
                                if ssim_score is not None and ssim_score > closest_score:
                                    closest_score = ssim_score
                                    closest = existing_url
                                    closest_fp = existing
                        except Exception:
                            continue
            except Exception:
                pass

        if closest is None or closest_fp is None:
            return self._fallback_match()

        similarity_percent = int(closest_score * 100)
        matching_elements = self._matching_elements(self.fingerprint, closest_fp)

        # Generate side-by-side comparison
        twin_ss = closest_fp.get("screenshot_path") or closest_fp.get("screenshot")
        side_by_side = None
        if twin_ss and os.path.exists(twin_ss):
            side_by_side = self._create_side_by_side(
                my_screenshot,
                twin_ss,
                my_domain,
                closest_fp.get("domain", "competitor")
            )

        return {
            "similarity_percent": similarity_percent,
            "label": self._visual_label(similarity_percent),
            "closest_match_url": closest,
            "matching_elements": matching_elements,
            "screenshot_twin": twin_ss,
            "ssim_score": round(closest_score, 3),
            "method": "ssim_screenshot",
            "side_by_side_path": side_by_side,
        }

    def _fallback_match(self) -> Dict[str, Any]:
        my_vec = self._vectorize(self.fingerprint)
        my_url = self.fingerprint.get("url", "").lower().rstrip("/")
        my_domain = self.fingerprint.get("domain", "").lower()
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
                            existing_domain = existing.get("domain", "").lower()
                            if existing_url == my_url or existing_domain == my_domain or not existing_url:
                                continue
                            existing_vec = self._vectorize(existing)
                            dist = self._distance(my_vec, existing_vec)
                            if dist < closest_dist:
                                closest_dist = dist
                                closest = existing_url
                                closest_fp = existing
                        except Exception:
                            continue
            except Exception:
                pass

        if closest is None:
            return {
                "similarity_percent": 0,
                "label": "Unique Visual",
                "closest_match_url": None,
                "matching_elements": [],
                "screenshot_twin": None,
                "ssim_score": 0.0,
                "method": "fallback_color_font",
                "side_by_side_path": None,
            }

        similarity = max(0, min(100, int(100 - closest_dist * 33)))
        elements = self._matching_elements(self.fingerprint, closest_fp)
        twin_ss = closest_fp.get("screenshot_path") or closest_fp.get("screenshot")

        # Try to create side-by-side even in fallback mode if we have screenshots
        side_by_side = None
        my_ss = self.fingerprint.get("screenshot_path") or self.fingerprint.get("screenshot")
        if my_ss and twin_ss and os.path.exists(my_ss) and os.path.exists(twin_ss):
            side_by_side = self._create_side_by_side(
                my_ss,
                twin_ss,
                my_domain,
                closest_fp.get("domain", "competitor")
            )

        return {
            "similarity_percent": similarity,
            "label": self._visual_label(similarity),
            "closest_match_url": closest,
            "matching_elements": elements,
            "screenshot_twin": twin_ss,
            "ssim_score": 0.0,
            "method": "fallback_color_font",
            "side_by_side_path": side_by_side,
        }

    def _hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        if len(hex_color) == 3:
            hex_color = "".join([c * 2 for c in hex_color])
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    def _vectorize(self, fp: Dict[str, Any]) -> List[float]:
        vec = []
        # Try dominant_colors first, then colors
        colors = fp.get("dominant_colors", []) or fp.get("colors", [])
        for c in colors[:3]:
            try:
                r, g, b = self._hex_to_rgb(c)
                vec.extend([r / 255.0, g / 255.0, b / 255.0])
            except Exception:
                vec.extend([0.0, 0.0, 0.0])
        while len(vec) < 9:
            vec.extend([0.0, 0.0, 0.0])

        fonts = fp.get("font_families", [])
        vec.append(len(fonts) / 5.0)

        # Try layout_ratios first, then layout
        layout = fp.get("layout_ratios", {}) or fp.get("layout", {})
        vec.append(1.0 if layout.get("has_hero") else 0.0)
        vec.append((layout.get("grid_columns", 0) or 0) / 6.0)
        vec.append((layout.get("sections", 0) or layout.get("section_count", 0) or 0) / 20.0)
        return vec

    def _distance(self, v1: List[float], v2: List[float]) -> float:
        return sum((a - b) ** 2 for a, b in zip(v1, v2)) ** 0.5

    def _matching_elements(self, fp1: Dict, fp2: Dict) -> List[str]:
        elements = []
        # Colors
        c1 = set(fp1.get("dominant_colors", []) or fp1.get("colors", []))
        c2 = set(fp2.get("dominant_colors", []) or fp2.get("colors", []))
        shared_colors = c1 & c2
        if shared_colors:
            elements.append(f"color {list(shared_colors)[0]}")

        # Fonts
        f1 = set(fp1.get("font_families", []))
        f2 = set(fp2.get("font_families", []))
        shared_fonts = f1 & f2
        if shared_fonts:
            elements.append(f"font {list(shared_fonts)[0]}")

        # Layout
        l1 = fp1.get("layout_ratios", {}) or fp1.get("layout", {})
        l2 = fp2.get("layout_ratios", {}) or fp2.get("layout", {})
        if l1.get("has_hero") and l2.get("has_hero"):
            elements.append("hero layout")
        if l1.get("has_grid") and l2.get("has_grid"):
            elements.append(f"{l1.get('grid_columns', 0)}-column grid")
        if l1.get("sections", 0) and l2.get("sections", 0):
            elements.append(f"{min(l1.get('sections', 0), l2.get('sections', 0))} similar sections")
        return elements[:5]

    def _visual_label(self, similarity: int) -> str:
        if similarity >= 80: return "Clone Detected"
        if similarity >= 50: return "Similar Layout"
        if similarity >= 20: return "Some Overlap"
        return "Unique Visual"

    def save(self) -> None:
        try:
            with open(self.fp_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(self.fingerprint) + "\n")
        except Exception:
            pass


class CopycatIndexScorer:
    def __init__(self, html: str):
        self.html = html.lower() if html else ""

    def score(self) -> Dict[str, Any]:
        if not self.html:
            return {"copycat_index": 0, "template_match": "Unknown / Custom", "matched_classes": []}
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
            return {"copycat_index": 10, "template_match": "Unknown / Custom", "matched_classes": []}
        matches.sort(key=lambda x: x[1], reverse=True)
        top_template = matches[0][0]
        total_hits = sum(m[1] for m in matches)
        copycat_index = min(50 + total_hits * 2, 98)
        matched_classes = [m[0] for m in matches[:3]]
        return {"copycat_index": copycat_index, "template_match": top_template, "matched_classes": matched_classes}


class SocialSignalsFetcher:
    def __init__(self, brand: str, domain: str):
        self.brand = brand.lower()
        self.domain = domain.lower()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; TrillokaBot/1.0)"})

    def scan(self, max_signals: int = 4, own: bool = False) -> Dict[str, Any]:
        try:
            reddit_posts = self._search_reddit([self.brand, self.domain], per_query=8)
        except Exception:
            reddit_posts = []
        try:
            trustpilot = self._search_trustpilot(self.domain)
        except Exception:
            trustpilot = []
        try:
            yelp = self._search_yelp(self.brand)
        except Exception:
            yelp = []
        try:
            google_reviews = self._search_google_reviews(self.domain)
        except Exception:
            google_reviews = []

        mentions: List[str] = []
        complaints: List[str] = []
        all_sources = reddit_posts + trustpilot + yelp + google_reviews
        for entry in all_sources:
            title = entry.get("title", "")
            text = entry.get("text", "")
            source = entry.get("source", "")
            blob = (title + " " + text).lower()
            if not title:
                continue
            mentions.append(f"{source}: {title[:80]}...")
            if any(kw in blob for kw in COMPLAINT_KEYWORDS):
                complaints.append(f"{source}: {title[:80]}...")

        total = len(mentions)
        positive = [m for m in mentions if m not in complaints]
        if own:
            return {
                "mentions_found": total,
                "complaints_found": len(complaints),
                "verdict": "own",
                "verdict_label": "Home turf",
                "signals": [],
                "positive_examples": [],
                "negative_examples": [],
                "sources": {"reddit": len(reddit_posts), "trustpilot": len(trustpilot), "yelp": len(yelp), "google": len(google_reviews)},
            }
        if total == 0:
            verdict, verdict_label = "invisible", "No public conversation found"
        elif total <= 5:
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
            "sources": {"reddit": len(reddit_posts), "trustpilot": len(trustpilot), "yelp": len(yelp), "google": len(google_reviews)},
        }

    def _search_reddit(self, queries: List[str], per_query: int = 5) -> List[Dict[str, Any]]:
        results = []
        for query in queries:
            try:
                response = self.session.get(
                    "https://www.reddit.com/search.json",
                    params={"q": query, "limit": per_query, "sort": "new"},
                    timeout=5,
                )
                if response.status_code == 200:
                    for child in response.json().get("data", {}).get("children", []):
                        d = child.get("data", {})
                        results.append({
                            "title": d.get("title", ""),
                            "text": d.get("selftext", ""),
                            "source": f"Reddit r/{d.get('subreddit', '')}",
                        })
            except Exception:
                continue
        return results

    def _search_trustpilot(self, domain: str) -> List[Dict[str, Any]]:
        try:
            resp = self.session.get(f"https://www.trustpilot.com/review/{domain}", timeout=8)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            reviews = soup.find_all("p", {"data-service-review-text-typography": True})
            out = []
            for r in reviews[:5]:
                out.append({"title": r.get_text()[:100], "text": r.get_text(), "source": "Trustpilot"})
            return out
        except Exception:
            return []

    def _search_yelp(self, brand: str) -> List[Dict[str, Any]]:
        try:
            resp = self.session.get(f"https://www.yelp.com/search?find_desc={brand}", timeout=8)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            reviews = soup.find_all("p", class_=re.compile(r"comment"))
            out = []
            for r in reviews[:3]:
                out.append({"title": r.get_text()[:100], "text": r.get_text(), "source": "Yelp"})
            return out
        except Exception:
            return []

    def _search_google_reviews(self, domain: str) -> List[Dict[str, Any]]:
        try:
            resp = self.session.get(f"https://www.google.com/search?q={domain}+reviews", timeout=8)
            soup = BeautifulSoup(resp.text, "html.parser")
            snippets = soup.find_all("span", class_=re.compile(r"review"))
            out = []
            for s in snippets[:3]:
                out.append({"title": s.get_text()[:100], "text": s.get_text(), "source": "Google"})
            return out
        except Exception:
            return []


class RevenueScorer:
    def __init__(self, data: Dict[str, Any]):
        self.data = data
        self.scores: Dict[str, int] = {}
        self.completed_checks = 0

    def calculate_scores(self) -> Dict[str, int]:
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