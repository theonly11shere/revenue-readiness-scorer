#!/usr/bin/env python3
"""Website Scraper — fetches pages, extracts signals, runs real tests."""
import asyncio
import json
import os
import re
import ssl
import time
from collections import Counter
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import aiohttp
import requests
import textstat
from bs4 import BeautifulSoup

from config import (
    MAX_PAGES_FREE, MAX_PAGES_PAID, MIN_PAGES_PER_TEMPLATE_PAID,
    REQUEST_TIMEOUT, MAX_DOWNLOAD_SIZE, PLAYWRIGHT_TIMEOUT,
    TEMPLATE_PATTERNS, JS_FRAMEWORK_SIGNATURES,
    SECURITY_HEADERS, BUSINESS_TYPE_KEYWORDS, BUSINESS_TYPE_CHECKS,
    SCREENSHOT_DIR, LIGHTHOUSE_ENABLED, LIGHTHOUSE_TIMEOUT,
)
from scorer import TemplateFingerprinter, ContentSamenessChecker

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

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

    def fetch_with_playwright(self, url: str, mobile: bool = False) -> Tuple[str, Optional[bytes]]:
        if not self._available or self._pw_module is None:
            raise RuntimeError("Playwright is not installed.")
        with self._pw_module() as p:
            browser = p.chromium.launch(headless=True)
            context_kwargs = {}
            if mobile:
                context_kwargs = {"viewport": {"width": 375, "height": 812}, "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"}
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=PLAYWRIGHT_TIMEOUT * 1000)
                html = page.content()
                screenshot = page.screenshot(full_page=False) if not mobile else None
            finally:
                browser.close()
        return html, screenshot

    def run_lighthouse(self, url: str) -> Dict[str, Any]:
        """Run Lighthouse audit via Playwright CDP."""
        if not self._available or not LIGHTHOUSE_ENABLED:
            return {}
        try:
            with self._pw_module() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                client = page.context.new_cdp_session(page)
                page.goto(url, wait_until="networkidle", timeout=LIGHTHOUSE_TIMEOUT * 1000)
                metrics = client.send("Performance.getMetrics")
                browser.close()
                # Extract useful metrics
                m = {item["name"]: item["value"] for item in metrics.get("metrics", [])}
                return {
                    "lcp": round(m.get("LargestContentfulPaint", 0) / 1000, 2),
                    "fcp": round(m.get("FirstContentfulPaint", 0) / 1000, 2),
                    "ttfb": round(m.get("NavigationStart", 0) / 1000, 2),
                    "dom_complete": round(m.get("DomContentLoaded", 0) / 1000, 2),
                    "layout_shifts": int(m.get("LayoutShift", 0)),
                }
        except Exception:
            return {}

    def test_mobile_responsive(self, url: str) -> Dict[str, Any]:
        """Render at mobile viewport and detect issues."""
        if not self._available:
            return {"tested": False, "pass": False, "issues": ["Playwright not available"]}
        try:
            with self._pw_module() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 375, "height": 812},
                    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"
                )
                page = context.new_page()
                page.goto(url, wait_until="networkidle", timeout=PLAYWRIGHT_TIMEOUT * 1000)
                # Check for horizontal scroll
                has_scroll = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
                # Check for tiny text
                tiny_text = page.evaluate("""() => {
                    const el = document.querySelector('p, span, a, button, li');
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    return parseFloat(style.fontSize) < 12;
                }""")
                # Check tap targets
                small_taps = page.evaluate("""() => {
                    const taps = document.querySelectorAll('a, button, input, [role="button"]');
                    let bad = 0;
                    taps.forEach(el => {
                        const rect = el.getBoundingClientRect();
                        if (rect.width < 44 || rect.height < 44) bad++;
                    });
                    return bad;
                }""")
                browser.close()
                issues = []
                if has_scroll:
                    issues.append("Horizontal scroll detected at 375px width")
                if tiny_text:
                    issues.append("Text smaller than 12px detected")
                if small_taps > 3:
                    issues.append(f"{small_taps} tap targets smaller than 44x44px")
                return {
                    "tested": True,
                    "pass": len(issues) == 0,
                    "issues": issues,
                    "viewport_width": 375,
                    "viewport_height": 812,
                }
        except Exception as e:
            return {"tested": False, "pass": False, "issues": [str(e)]}

    def capture_screenshot(self, url: str, filename: str) -> Optional[str]:
        """Capture full-page screenshot for visual twin."""
        if not self._available:
            return None
        try:
            with self._pw_module() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                page.goto(url, wait_until="networkidle", timeout=PLAYWRIGHT_TIMEOUT * 1000)
                path = os.path.join(SCREENSHOT_DIR, filename)
                page.screenshot(path=path, full_page=True)
                browser.close()
                return path
        except Exception:
            return None

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
                html_rendered, _ = self.fetch_with_playwright(url)
                return html_rendered, "rendered", framework
            except Exception:
                pass
        return html_static, "static", framework if is_js else None


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

            # Business type detection
            self.data["business_type"] = self._detect_business_type(soup)

            # Screenshot capture
            screenshot_path = fetcher.capture_screenshot(self.url, f"{self.domain.replace('.', '_')}.png")
            self.data["screenshot_path"] = screenshot_path

            # Lighthouse performance
            self.data["lighthouse"] = fetcher.run_lighthouse(self.url) if LIGHTHOUSE_ENABLED else {}

            # Real mobile responsive test
            self.data["mobile_test"] = fetcher.test_mobile_responsive(self.url) if fetcher.available else {"tested": False, "pass": False}

            # SSL validation
            self.data["ssl_valid"] = self._check_ssl_valid(self.url)

            # Security headers
            self.data["security_headers"] = self._check_security_headers(self.url)

            # Template fingerprint
            self.data["template_fingerprint"] = TemplateFingerprinter().fingerprint(html)
            self.data["content_sameness"] = ContentSamenessChecker().check(soup.get_text(separator=" ", strip=True))

            # Visual twin fingerprint
            visual_fp = self._extract_visual_features(html, soup)
            visual_fp["url"] = self.url
            visual_fp["timestamp"] = datetime.now().isoformat()
            visual_fp["screenshot"] = screenshot_path
            self.data["visual_fingerprint"] = visual_fp

            # Crawl sample pages
            crawler = TemplateDiscoveryCrawler(self.url, tier=self.tier)
            crawler.discover(soup)
            sample = crawler.select_sample()
            self.data["pages_sampled"] = len(sample)
            self.data["max_pages"] = crawler.max_pages
            self.data["template_breakdown"] = {}

            for page_url, template_type in sample:
                page_data = self._scrape_page(page_url, template_type, fetcher)
                self.pages.append(page_data)
                self.data["template_breakdown"][template_type] = self.data["template_breakdown"].get(template_type, 0) + 1

            self._aggregate_signals()
            # Aggregate broken links across all pages
            self.data["broken_links_full"] = self._check_all_broken_links()

        except Exception as e:
            self.data["error"] = str(e)
        return self.data

    def _detect_business_type(self, soup: BeautifulSoup) -> Dict[str, Any]:
        text = soup.get_text(separator=" ", strip=True).lower()
        scores = {}
        for btype, keywords in BUSINESS_TYPE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            scores[btype] = score
        best = max(scores, key=scores.get) if scores else "unknown"
        confidence = min(100, scores.get(best, 0) * 10)
        return {
            "detected_type": best,
            "confidence": confidence,
            "scores": scores,
            "specific_checks": BUSINESS_TYPE_CHECKS.get(best, []),
        }

    def _check_ssl_valid(self, url: str) -> Dict[str, Any]:
        hostname = urlparse(url).hostname or url
        try:
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(ssl.socket(), server_hostname=hostname) as s:
                s.settimeout(5)
                s.connect((hostname, 443))
                cert = s.getpeercert()
                cipher = s.cipher()
                version = s.version()
                expiry = cert.get("notAfter", "")
                issuer = cert.get("issuer", [])
                subject = cert.get("subject", [])
                return {
                    "valid": True,
                    "expiry": expiry,
                    "issuer": str(issuer),
                    "subject": str(subject),
                    "tls_version": version,
                    "cipher": str(cipher),
                }
        except Exception as e:
            return {"valid": False, "error": str(e)}

    def _check_security_headers(self, url: str) -> Dict[str, Any]:
        try:
            resp = requests.head(url, timeout=10, allow_redirects=True)
            headers = resp.headers
            found = {h: headers.get(h, "Missing") for h in SECURITY_HEADERS}
            score = sum(1 for v in found.values() if v != "Missing")
            return {"present": found, "score": score, "max": len(SECURITY_HEADERS), "pass": score >= 3}
        except Exception as e:
            return {"present": {}, "score": 0, "max": len(SECURITY_HEADERS), "pass": False, "error": str(e)}

    async def _async_check_link(self, session: aiohttp.ClientSession, page_url: str, href: str) -> Optional[Dict[str, Any]]:
        full = urljoin(page_url, href)
        try:
            async with session.head(full, timeout=aiohttp.ClientTimeout(total=8), allow_redirects=True) as resp:
                if resp.status >= 400:
                    return {"url": full, "status": resp.status, "page": page_url}
        except Exception:
            try:
                async with session.get(full, timeout=aiohttp.ClientTimeout(total=8), allow_redirects=True) as resp:
                    if resp.status >= 400:
                        return {"url": full, "status": resp.status, "page": page_url}
            except Exception:
                return {"url": full, "status": 0, "page": page_url, "error": "Unreachable"}
        return None

    def _check_all_broken_links(self) -> Dict[str, Any]:
        all_links = set()
        for page in self.pages:
            soup = BeautifulSoup(page.get("raw_html", ""), "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.startswith("http") or href.startswith("/") or href.startswith("."):
                    all_links.add((page.get("url", self.url), href))
        if not all_links:
            return {"checked": 0, "broken": [], "broken_count": 0}

        async def run():
            broken = []
            async with aiohttp.ClientSession(headers=self.headers) as session:
                tasks = [self._async_check_link(session, pu, href) for pu, href in all_links]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in results:
                    if isinstance(r, dict) and r:
                        broken.append(r)
            return broken

        try:
            broken = asyncio.run(run())
        except Exception:
            broken = []
        return {"checked": len(all_links), "broken": broken[:20], "broken_count": len(broken)}

    def _scrape_page(self, page_url: str, template_type: str, fetcher: RenderedPageFetcher) -> Dict[str, Any]:
        try:
            html, engine, _ = fetcher.fetch(page_url, self.use_playwright)
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return {"url": page_url, "template_type": template_type, "error": "fetch_failed", "trust": {}, "conversion": {}, "seo": {}, "content": {}, "technical": {}, "raw_html": ""}
        page_data = {"url": page_url, "template_type": template_type, "rendering_engine": engine, "raw_html": html}
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
        # Inject real measurements into aggregated data
        if self.data.get("mobile_test", {}).get("tested"):
            self.data["conversion"]["mobile_real"] = self.data["mobile_test"]["pass"]
        if self.data.get("lighthouse"):
            l = self.data["lighthouse"]
            self.data["conversion"]["speed_lighthouse"] = l.get("lcp", 999) < 2.5
        if self.data.get("ssl_valid"):
            self.data["trust"]["ssl_valid"] = self.data["ssl_valid"].get("valid", False)
        if self.data.get("security_headers"):
            self.data["technical"]["security_headers"] = self.data["security_headers"].get("pass", False)
        if self.data.get("broken_links_full"):
            bl = self.data["broken_links_full"]
            self.data["technical"]["broken_links"] = bl.get("broken_count", 0) == 0
            self.data["technical"]["broken_count"] = bl.get("broken_count", 0)

    def _extract_visual_features(self, html: str, soup: BeautifulSoup) -> Dict[str, Any]:
        hex_colors = re.findall(r"#[0-9a-fA-F]{3,6}\b", html)
        normalized = []
        for c in hex_colors:
            c = c.lower()
            if len(c) == 4:
                c = "#" + "".join([c[1]*2, c[2]*2, c[3]*2])
            normalized.append(c)
        dominant_colors = [c for c, _ in Counter(normalized).most_common(3)]
        font_families = set()
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
        d = {}
        d["ssl"] = page_url.startswith("https")
        d["contact"] = bool(soup.find(string=re.compile(r"contact|email|phone", re.I)))
        d["about"] = bool(soup.find("a", href=re.compile(r"about", re.I)))
        d["privacy"] = bool(soup.find("a", href=re.compile(r"privacy", re.I)))
        d["terms"] = bool(soup.find("a", href=re.compile(r"term", re.I)))
        d["reviews"] = bool(soup.find(string=re.compile(r"review|testimonial", re.I)))
        d["team_photos"] = len(soup.find_all("img", src=re.compile(r"team|staff|about", re.I))) > 0
        return d

    def _extract_conversion_signals(self, soup: BeautifulSoup, page_url: str) -> Dict[str, Any]:
        d = {}
        d["cta"] = bool(soup.find(string=re.compile(r"book|schedule|quote|contact|call", re.I)))
        d["mobile"] = "viewport" in str(soup.find("meta", attrs={"name": "viewport"}))
        d["phone_clickable"] = bool(soup.find("a", href=re.compile(r"tel:")))
        d["email_capture"] = bool(soup.find("input", attrs={"type": "email"}))
        d["pricing"] = bool(soup.find(string=re.compile(r"price|cost|rate|fee", re.I)))
        d["testimonials"] = bool(soup.find(string=re.compile(r"testimonial|review|client", re.I)))
        return d

    def _extract_seo_signals(self, soup: BeautifulSoup, page_url: str) -> Dict[str, Any]:
        d = {}
        title = soup.find("title")
        d["title"] = bool(title and len(title.get_text()) > 10)
        desc = soup.find("meta", attrs={"name": "description"})
        d["meta_desc"] = bool(desc and len(desc.get("content", "")) > 50)
        d["h1"] = len(soup.find_all("h1")) == 1
        d["alt_text"] = all(img.get("alt") for img in soup.find_all("img")[:5])
        d["schema"] = bool(soup.find("script", attrs={"type": "application/ld+json"}))
        return d

    def _extract_content_signals(self, soup: BeautifulSoup, page_url: str) -> Dict[str, Any]:
        d = {}
        text = soup.get_text()
        d["word_count"] = len(text.split())
        d["unique"] = len(set(text.split())) / max(len(text.split()), 1) > 0.6
        # REAL readability using textstat
        try:
            d["flesch_ease"] = textstat.flesch_reading_ease(text)
            d["flesch_grade"] = textstat.flesch_kincaid_grade(text)
            d["gunning_fog"] = textstat.gunning_fog(text)
            d["smog"] = textstat.smog_index(text)
            d["readability_pass"] = d["flesch_ease"] >= 50
        except Exception:
            d["readability_pass"] = False
        d["services"] = bool(soup.find(string=re.compile(r"service|offering|solution", re.I)))
        d["blog"] = bool(soup.find("a", href=re.compile(r"blog|news|article", re.I)))
        d["faq"] = bool(soup.find(string=re.compile(r"faq|frequently", re.I)))
        return d

    def _extract_technical_signals(self, soup: BeautifulSoup, page_url: str) -> Dict[str, Any]:
        d = {}
        d["canonical"] = bool(soup.find("link", attrs={"rel": "canonical"}))
        d["structured"] = bool(soup.find("script", attrs={"type": "application/ld+json"}))
        d["favicon"] = bool(soup.find("link", rel=re.compile(r"icon|shortcut icon", re.I)))
        # Legacy shallow check — overridden by async full check
        links = soup.find_all("a", href=True)[:10]
        broken = 0
        for link in links:
            try:
                r = requests.head(urljoin(page_url, link["href"]), timeout=5, allow_redirects=True)
                if r.status_code >= 400:
                    broken += 1
            except Exception:
                broken += 1
        d["broken_links_legacy"] = broken
        return d
