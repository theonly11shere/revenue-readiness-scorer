#!/usr/bin/env python3
"""
Website Scraper — fetches pages, extracts signals, and runs Market Doppelgänger checks.
"""

import json
import os
import re
from collections import Counter
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from scorer import (
    TemplateFingerprinter,
    ContentSamenessChecker,
    VisualTwinMatcher,
)

# ── Configuration ───────────────────────

MAX_PAGES_FREE = 3
MAX_PAGES_PAID = 10
MIN_PAGES_PER_TEMPLATE_PAID = 2
REQUEST_TIMEOUT = 15
MAX_DOWNLOAD_SIZE = 5 * 1024 * 1024
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


# ── Template Discovery Crawler ───────────

class TemplateDiscoveryCrawler:
    def __init__(self, base_url: str, tier: str = "free"):
        self.base_url = base_url if base_url.startswith("http") else f"https://{base_url}"
        self.domain = urlparse(self.base_url).netloc
        self.tier = tier
        self.max_pages = MAX_PAGES_PAID if tier == "paid" else MAX_PAGES_FREE
        self.min_per_template = MIN_PAGES_PER_TEMPLATE_PAID if tier == "paid" else 1
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        self._discovered: Dict[str, List[str]] = {}
        self._all_links: set = set()

    def classify_path(self, url: str, soup: Optional[BeautifulSoup] = None) -> str:
        path = urlparse(url).path.lower()
        for pattern, ttype in TEMPLATE_PATTERNS.items():
            if re.search(pattern, path, re.I):
                return ttype
        if soup is not None:
            text = soup.get_text(separator=" ", strip=True).lower()
            if any(w in text for w in ("add to cart", "buy now", "price:", "$", "checkout")):
                return "product"
            if any(w in text for w in ("contact us", "get in touch", "send message", "phone", "email")):
                return "contact"
            if any(w in text for w in ("our services", "what we offer", "solutions", "capabilities")):
                return "service"
            if any(w in text for w in ("blog", "article", "posted on", "read more")):
                return "blog"
            if any(w in text for w in ("privacy policy", "terms of service", "refund policy", "cookie policy")):
                return "policy"
            if any(w in text for w in ("find us", "our location", "visit us", "directions")):
                return "location"
        return "other"

    def _fetch_html(self, url: str) -> Tuple[str, Optional[BeautifulSoup]]:
        try:
            resp = requests.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if resp.status_code >= 400:
                return "", None
            if len(resp.content) > MAX_DOWNLOAD_SIZE:
                return "", None
            soup = BeautifulSoup(resp.text, "html.parser")
            return resp.text, soup
        except Exception:
            return "", None

    def discover(self, homepage_soup: BeautifulSoup) -> Dict[str, List[str]]:
        links = homepage_soup.find_all("a", href=True)
        for a in links:
            href = a["href"]
            full = urljoin(self.base_url, href)
            parsed = urlparse(full)
            if parsed.netloc != self.domain:
                continue
            if full in self._all_links:
                continue
            self._all_links.add(full)
            ttype = self.classify_path(full)
            self._discovered.setdefault(ttype, []).append(full)
        if "home" not in self._discovered:
            self._discovered["home"] = [self.base_url]
        elif self.base_url not in self._discovered["home"]:
            self._discovered["home"].insert(0, self.base_url)
        return self._discovered

    def select_sample(self) -> List[Tuple[str, str]]:
        if not self._discovered:
            return [(self.base_url, "home")]
        selected: List[Tuple[str, str]] = []
        counts: Dict[str, int] = {}
        types = list(self._discovered.keys())
        round_idx = 0
        while len(selected) < self.max_pages:
            added_in_round = False
            for ttype in types:
                urls = self._discovered[ttype]
                current = counts.get(ttype, 0)
                need = self.min_per_template if self.tier == "paid" else 1
                if current < len(urls) and (current < need or self.tier == "paid"):
                    selected.append((urls[current], ttype))
                    counts[ttype] = current + 1
                    added_in_round = True
                    if len(selected) >= self.max_pages:
                        break
            if not added_in_round:
                break
            round_idx += 1
        return selected


# ── Rendered Page Fetcher ───────────────

class RenderedPageFetcher:
    def __init__(self):
        self._available = False
        try:
            from playwright.sync_api import sync_playwright
            self._pw_module = sync_playwright
            self._available = True
        except Exception:
            self._pw_module = None
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def is_js_framework(self, html_text: str) -> Tuple[bool, Optional[str]]:
        lower = html_text.lower()
        for sig, framework in JS_FRAMEWORK_SIGNATURES.items():
            if sig.lower() in lower:
                return True, framework
        return False, None

    def fetch_with_playwright(self, url: str) -> str:
        if not self._available or self._pw_module is None:
            raise RuntimeError("Playwright is not installed.")
        with self._pw_module() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=PLAYWRIGHT_TIMEOUT * 1000)
                html = page.content()
            finally:
                browser.close()
        return html

    def fetch(self, url: str, use_playwright: Optional[bool] = None) -> Tuple[str, str, Optional[str]]:
        if use_playwright is False:
            resp = requests.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text, "static", None

        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        html_static = resp.text

        is_js, framework = self.is_js_framework(html_static)
        if use_playwright is True or (use_playwright is None and is_js and self._available):
            try:
                html_rendered = self.fetch_with_playwright(url)
                return html_rendered, "rendered", framework
            except Exception:
                pass
        return html_static, "static", framework if is_js else None


# ── Main Scraper ─────────────────────────

class WebsiteScraper:
    def __init__(self, url: str, tier: str = "free", use_playwright: Optional[bool] = None):
        self.url = url if url.startswith("http") else f"https://{url}"
        self.domain = urlparse(self.url).netloc
        self.tier = tier
        self.use_playwright = use_playwright
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        self.data: Dict[str, Any] = {}
        self.pages: List[Dict[str, Any]] = []
        self.rendering_engine = "static"
        self.detected_framework: Optional[str] = None

    def scrape(self) -> Dict[str, Any]:
        try:
            # Step 1: Fetch homepage
            fetcher = RenderedPageFetcher()
            html, engine, framework = fetcher.fetch(self.url, self.use_playwright)
            self.rendering_engine = engine
            self.detected_framework = framework

            soup = BeautifulSoup(html, "html.parser")
            self.data["status_code"] = 200
            self.data["html_length"] = len(html)
            self.data["raw_html"] = html
            self.data["rendering_engine"] = engine
            self.data["detected_framework"] = framework
            self.data["tier"] = self.tier
            self.data["timestamp"] = datetime.now().isoformat()

            # ── Market Doppelgänger features ──
            self.data["template_fingerprint"] = TemplateFingerprinter().fingerprint(html)
            self.data["content_sameness"] = ContentSamenessChecker().check(
                soup.get_text(separator=" ", strip=True)
            )

            visual_fp = self._extract_visual_features(html, soup)
            visual_fp["url"] = self.url
            visual_fp["timestamp"] = datetime.now().isoformat()
            twin_matcher = VisualTwinMatcher(visual_fp)
            self.data["visual_twin"] = twin_matcher.match()
            twin_matcher.save()
            # ── End Market Doppelgänger ──

            # Step 2: Discover templates and select sample
            crawler = TemplateDiscoveryCrawler(self.url, tier=self.tier)
            crawler.discover(soup)
            sample = crawler.select_sample()
            self.data["pages_sampled"] = len(sample)
            self.data["max_pages"] = crawler.max_pages
            self.data["template_breakdown"] = {}

            # Step 3: Crawl each sampled page
            for page_url, template_type in sample:
                page_data = self._scrape_page(page_url, template_type, fetcher)
                self.pages.append(page_data)
                self.data["template_breakdown"][template_type] = (
                    self.data["template_breakdown"].get(template_type, 0) + 1
                )

            # Step 4: Aggregate signals
            self._aggregate_signals()

        except Exception as e:
            self.data["error"] = str(e)
        return self.data

    def _scrape_page(self, page_url: str, template_type: str, fetcher: RenderedPageFetcher) -> Dict[str, Any]:
        try:
            html, engine, _ = fetcher.fetch(page_url, self.use_playwright)
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return {
                "url": page_url,
                "template_type": template_type,
                "error": "fetch_failed",
                "trust": {},
                "conversion": {},
                "seo": {},
                "content": {},
                "technical": {},
            }

        page_data: Dict[str, Any] = {
            "url": page_url,
            "template_type": template_type,
            "rendering_engine": engine,
        }
        page_data["trust"] = self._extract_trust_signals(soup, page_url)
        page_data["conversion"] = self._extract_conversion_signals(soup, page_url)
        page_data["seo"] = self._extract_seo_signals(soup, page_url)
        page_data["content"] = self._extract_content_signals(soup, page_url)
        page_data["technical"] = self._extract_technical_signals(soup, page_url)
        return page_data

    def _aggregate_signals(self) -> None:
        for cat in ("trust", "conversion", "seo", "content", "technical"):
            self.data[cat] = {}
        for page in self.pages:
            for cat in ("trust", "conversion", "seo", "content", "technical"):
                src = page.get(cat, {})
                dst = self.data[cat]
                for key, value in src.items():
                    if key not in dst:
                        dst[key] = value
                    else:
                        if isinstance(value, bool) and isinstance(dst[key], bool):
                            dst[key] = dst[key] or value
                        elif isinstance(value, (int, float)) and isinstance(dst[key], (int, float)):
                            dst[key] = max(dst[key], value)
                        elif value and not dst[key]:
                            dst[key] = value

    def _extract_visual_features(self, html: str, soup: BeautifulSoup) -> Dict[str, Any]:
        hex_colors = re.findall(r"#[0-9a-fA-F]{3,6}\b", html)
        normalized: List[str] = []
        for c in hex_colors:
            c = c.lower()
            if len(c) == 4:
                c = "#" + "".join([c[1] * 2, c[2] * 2, c[3] * 2])
            normalized.append(c)
        dominant_colors = [c for c, _ in Counter(normalized).most_common(3)]

        font_families: set = set()
        generic = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "inherit", "initial", "unset", "default"}
        for match in re.findall(r"font-family\s*:\s*([^;]+)", html, re.IGNORECASE):
            for font in match.split(","):
                font = font.strip().strip("\"'").lower()
                if font and font not in generic:
                    font_families.add(font)

        sections = len(soup.find_all("section"))
        if sections == 0:
            sections = len(soup.find_all(["div", "article"], class_=re.compile(r"section|hero|banner", re.I)))

        has_hero = bool(soup.find(class_=re.compile(r"hero|banner", re.I))) or bool(soup.find("section"))

        grid_columns = 0
        has_grid = False
        grid_classes = soup.find_all(class_=re.compile(r"grid-cols-(\d+)", re.I))
        if grid_classes:
            has_grid = True
            for tag in grid_classes:
                classes = " ".join(tag.get("class", []))
                nums = re.findall(r"grid-cols-(\d+)", classes, re.I)
                if nums:
                    grid_columns = max(grid_columns, max(int(n) for n in nums))

        grid_css = re.findall(r"grid-template-columns\s*:\s*[^;]*repeat\s*\(\s*(\d+)", html, re.IGNORECASE)
        if grid_css:
            has_grid = True
            grid_columns = max(grid_columns, max(int(n) for n in grid_css))

        return {
            "dominant_colors": dominant_colors,
            "font_families": list(font_families)[:5],
            "layout_ratios": {
                "hero": 0.4 if has_hero else 0.0,
                "grid_columns": grid_columns,
                "sections": sections,
                "has_hero": has_hero,
                "has_grid": has_grid,
            },
        }

    def _extract_trust_signals(self, soup: BeautifulSoup, page_url: str) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        d["ssl"] = page_url.startswith("https")
        d["contact"] = bool(soup.find(string=re.compile(r"contact|email|phone", re.I)))
        d["about"] = bool(soup.find("a", href=re.compile(r"about", re.I)))
        d["privacy"] = bool(soup.find("a", href=re.compile(r"privacy", re.I)))
        d["terms"] = bool(soup.find("a", href=re.compile(r"term", re.I)))
        d["reviews"] = bool(soup.find(string=re.compile(r"review|testimonial", re.I)))
        d["team_photos"] = len(soup.find_all("img", src=re.compile(r"team|staff|about", re.I))) > 0
        return d

    def _extract_conversion_signals(self, soup: BeautifulSoup, page_url: str) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        d["cta"] = bool(soup.find(string=re.compile(r"book|schedule|quote|contact|call", re.I)))
        d["mobile"] = "viewport" in str(soup.find("meta", attrs={"name": "viewport"}))
        d["phone_clickable"] = bool(soup.find("a", href=re.compile(r"tel:")))
        d["email_capture"] = bool(soup.find("input", attrs={"type": "email"}))
        d["pricing"] = bool(soup.find(string=re.compile(r"price|cost|rate|fee", re.I)))
        d["testimonials"] = bool(soup.find(string=re.compile(r"testimonial|review|client", re.I)))
        return d

    def _extract_seo_signals(self, soup: BeautifulSoup, page_url: str) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        title = soup.find("title")
        d["title"] = bool(title and len(title.get_text()) > 10)
        desc = soup.find("meta", attrs={"name": "description"})
        d["meta_desc"] = bool(desc and len(desc.get("content", "")) > 50)
        d["h1"] = len(soup.find_all("h1")) == 1
        d["alt_text"] = all(img.get("alt") for img in soup.find_all("img")[:5])
        d["schema"] = bool(soup.find("script", attrs={"type": "application/ld+json"}))
        return d

    def _extract_content_signals(self, soup: BeautifulSoup, page_url: str) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        text = soup.get_text()
        d["word_count"] = len(text.split())
        d["unique"] = len(set(text.split())) / max(len(text.split()), 1) > 0.6
        sentences = re.split(r"[.!?]+", text)
        avg_len = sum(len(s.split()) for s in sentences) / max(len(sentences), 1)
        d["ai_patterns"] = avg_len > 15 and avg_len < 25
        d["services"] = bool(soup.find(string=re.compile(r"service|offering|solution", re.I)))
        d["blog"] = bool(soup.find("a", href=re.compile(r"blog|news|article", re.I)))
        d["faq"] = bool(soup.find(string=re.compile(r"faq|frequently", re.I)))
        return d

    def _extract_technical_signals(self, soup: BeautifulSoup, page_url: str) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        d["canonical"] = bool(soup.find("link", attrs={"rel": "canonical"}))
        d["structured"] = bool(soup.find("script", attrs={"type": "application/ld+json"}))
        d["favicon"] = bool(soup.find("link", rel=re.compile(r"icon|shortcut icon", re.I)))
        links = soup.find_all("a", href=True)[:10]
        broken = 0
        for link in links:
            try:
                r = requests.head(urljoin(page_url, link["href"]), timeout=5, allow_redirects=True)
                if r.status_code >= 400:
                    broken += 1
            except Exception:
                broken += 1
        d["broken_links"] = broken
        d["broken_pct"] = broken / max(len(links), 1)
        return d
