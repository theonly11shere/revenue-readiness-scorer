#!/usr/bin/env python3
"""RRS Scraper — WebsiteScraper class matching api.py contract."""
import os
import re
import ssl
import socket
import time
import asyncio
import hashlib
from urllib.parse import urljoin, urlparse
from typing import Optional, Dict, Any, List

import requests
from bs4 import BeautifulSoup

# Graceful Playwright import
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class WebsiteScraper:
    """Sync-style scraper that api.py expects."""

    def __init__(self, url: str, tier: str = "free", use_playwright: Optional[bool] = None):
        self.url = url.rstrip("/")
        self.domain = urlparse(self.url).netloc.replace("www.", "")
        self.tier = tier
        self.use_playwright = use_playwright if use_playwright is not None else (tier == "paid")
        self.raw_html = ""
        self.soup = None
        self.browser = None
        self.playwright = None

    # ── Public API ──────────────────────────────────────────────────────────

    def scrape(self) -> Dict[str, Any]:
        """Synchronous entry point called by api.py"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("loop closed")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(self._scrape_async())

    # ── Async Core ──────────────────────────────────────────────────────────

    async def _scrape_async(self) -> Dict[str, Any]:
        # 1. Static fetch (always do this as baseline)
        try:
            resp = requests.get(
                self.url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.0"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=30,
                allow_redirects=True,
            )
            self.raw_html = resp.text
            self.soup = BeautifulSoup(self.raw_html, "html.parser")
            status_code = resp.status_code
            headers = resp.headers
        except Exception as e:
            return {"url": self.url, "error": str(e), "domain": self.domain}

        # 2. Build base data
        pages = [{"url": self.url, "raw_text": self.soup.get_text(separator=" ", strip=True)[:8000]}]

        data = {
            "url": self.url,
            "domain": self.domain,
            "raw_html": self.raw_html,
            "pages": pages,
            "pages_sampled": 1,
            "rendering_engine": "static",
            "detected_framework": self._detect_framework(),
            "template_fingerprint": self._template_fingerprint(),
            "content_sameness": self._content_sameness(),
            "visual_fingerprint": self._visual_fingerprint(),
            "ssl_valid": self._check_ssl(),
            "security_headers": self._check_security_headers(headers),
            "broken_links_full": self._check_broken_links() if self.tier == "paid" else {},
            "screenshot_path": None,
            "lighthouse": {},
            "mobile_test": {},
            "business_type": self._detect_business_type(),
        }

        # 3. Playwright features (screenshot, lighthouse, mobile)
        if self.use_playwright and PLAYWRIGHT_AVAILABLE:
            pw_ok = await self._init_browser()
            if pw_ok:
                try:
                    screenshot_path = await self._take_screenshot()
                    data["screenshot_path"] = screenshot_path
                    # CRITICAL: also put it inside visual_fingerprint so VisualTwinMatcher can find it
                    data["visual_fingerprint"]["screenshot_path"] = screenshot_path
                    data["visual_fingerprint"]["screenshot"] = screenshot_path

                    data["lighthouse"] = await self._run_lighthouse()
                    data["mobile_test"] = await self._test_mobile()
                    data["rendering_engine"] = "playwright"
                except Exception as e:
                    data["lighthouse"] = {"status": "failed", "error": str(e)}
                    data["mobile_test"] = {"status": "failed", "error": str(e)}
                finally:
                    await self._close_browser()

        return data

    # ── Playwright Helpers ──────────────────────────────────────────────────

    async def _init_browser(self) -> bool:
        if not PLAYWRIGHT_AVAILABLE:
            return False
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-breakpad",
                    "--disable-component-extensions-with-background-pages",
                    "--disable-features=TranslateUI,BlinkGenPropertyTrees",
                    "--disable-ipc-flooding-protection",
                    "--disable-renderer-backgrounding",
                    "--force-color-profile=srgb",
                    "--metrics-recording-only",
                ],
            )
            return True
        except Exception as e:
            print(f"[scraper] Browser init failed: {e}")
            return False

    async def _close_browser(self):
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None

    async def _take_screenshot(self) -> Optional[str]:
        if not self.browser:
            return None
        ctx = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
        )
        page = await ctx.new_page()
        try:
            await page.goto(self.url, wait_until="networkidle", timeout=30000)
            os.makedirs("/tmp/screenshots", exist_ok=True)
            path = f"/tmp/screenshots/{self.domain.replace('.', '_')}_{int(time.time())}.png"
            await page.screenshot(path=path, full_page=True)
            return path
        except Exception as e:
            print(f"[scraper] Screenshot failed: {e}")
            return None
        finally:
            await ctx.close()

    async def _run_lighthouse(self) -> Dict[str, Any]:
        if not self.browser:
            return {"status": "failed", "error": "Browser not available"}
        ctx = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        page = await ctx.new_page()
        try:
            start = time.time()
            await page.goto(self.url, wait_until="networkidle", timeout=30000)
            load_time = round(time.time() - start, 2)

            timing = await page.evaluate("""() => {
                const t = performance.timing;
                return {
                    dns_lookup: t.domainLookupEnd - t.domainLookupStart,
                    tcp_connection: t.connectEnd - t.connectStart,
                    server_response: t.responseEnd - t.requestStart,
                    dom_processing: t.domComplete - t.domLoading,
                    total_load: t.loadEventEnd - t.navigationStart,
                };
            }""")

            resources = await page.evaluate("""() =>
                performance.getEntriesByType('resource').map(r => ({
                    name: r.name,
                    type: r.initiatorType,
                    size: r.transferSize,
                    duration: r.duration,
                }))
            """)

            total_size = sum(r.get("size", 0) for r in resources)
            issues = []
            large_imgs = [r for r in resources if r.get("type") == "img" and r.get("size", 0) > 500000]
            if large_imgs:
                issues.append(f"Found {len(large_imgs)} images > 500KB")
            blocking = [r for r in resources if r.get("name", "").endswith((".css", ".js")) and r.get("size", 0) > 100000]
            if blocking:
                issues.append(f"Found {len(blocking)} large render-blocking resources")

            score = self._calc_perf_score(timing, load_time, len(issues))

            return {
                "status": "success",
                "performance": {
                    "load_time_seconds": load_time,
                    "timing": timing,
                    "total_transfer_size_kb": round(total_size / 1024, 2),
                    "resource_count": len(resources),
                },
                "issues": issues,
                "score": score,
            }
        except Exception as e:
            return {"status": "failed", "error": str(e)}
        finally:
            await ctx.close()

    async def _test_mobile(self) -> Dict[str, Any]:
        if not self.browser:
            return {"status": "failed", "error": "Browser not available"}

        devices = [
            {"name": "iPhone 12 Pro", "width": 390, "height": 844, "scale": 3},
            {"name": "iPad Air", "width": 820, "height": 1180, "scale": 2},
            {"name": "Pixel 5", "width": 393, "height": 851, "scale": 2.75},
            {"name": "Desktop", "width": 1920, "height": 1080, "scale": 1},
        ]
        results = []

        for dev in devices:
            ctx = await self.browser.new_context(
                viewport={"width": dev["width"], "height": dev["height"]},
                device_scale_factor=dev["scale"],
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
            )
            page = await ctx.new_page()
            try:
                await page.goto(self.url, wait_until="networkidle", timeout=30000)
                has_viewport = await page.query_selector("meta[name=viewport]") is not None
                has_scroll = await page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
                results.append({
                    "device": dev["name"],
                    "viewport": f"{dev['width']}x{dev['height']}",
                    "has_viewport_meta": has_viewport,
                    "has_horizontal_scroll": has_scroll,
                    "is_responsive": not has_scroll,
                })
            except Exception as e:
                results.append({"device": dev["name"], "error": str(e), "is_responsive": False})
            finally:
                await ctx.close()

        responsive = sum(1 for r in results if r.get("is_responsive"))
        score = round((responsive / len(devices)) * 100, 1) if devices else 0
        return {
            "status": "success",
            "devices_tested": len(devices),
            "responsive_devices": responsive,
            "overall_score": score,
            "device_results": results,
            "is_fully_responsive": score == 100,
        }

    # ── Static Analysis Helpers ─────────────────────────────────────────────

    def _detect_framework(self) -> Optional[str]:
        html = self.raw_html.lower()
        indicators = {
            "Shopify": ["cdn.shopify.com", "myshopify", "shopify.theme"],
            "WordPress": ["/wp-content/", "/wp-includes/", "wordpress"],
            "Wix": ["wix.com", "wixsite", "static.wixstatic.com"],
            "Squarespace": ["squarespace.com", "static1.squarespace.com"],
            "Webflow": ["webflow.com", "data-wf-"],
            "React": ["reactroot", "data-reactroot", "__next", "_next/static"],
            "Next.js": ["__next", "_next/static", "/_next/"],
            "Vue": ["__vue__", "data-v-"],
            "Gatsby": ["___gatsby", "gatsby-focus-wrapper"],
            "Framer": ["framer.com", "framerusercontent"],
            "Django": ["csrfmiddlewaretoken", "django"],
            "Rails": ["csrf-param", "csrf-token", "ruby"],
        }
        scores = {name: sum(1 for ind in inds if ind in html) for name, inds in indicators.items()}
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else None

    def _template_fingerprint(self) -> Dict[str, Any]:
        html = self.raw_html.lower()
        platforms = []
        if "cdn.shopify.com" in html or "myshopify" in html:
            platforms.append("Shopify")
        if "/wp-content/" in html:
            platforms.append("WordPress")
        if "wix.com" in html or "wixsite" in html:
            platforms.append("Wix")
        if "squarespace.com" in html:
            platforms.append("Squarespace")
        if "webflow.com" in html:
            platforms.append("Webflow")

        generic_signals = 0
        generic_phrases = [
            "welcome to our website", "powered by", "all rights reserved",
            "contact us today", "get in touch", "about us", "our services",
            "lorem ipsum", "placeholder", "template by",
        ]
        text = self.soup.get_text(separator=" ", strip=True).lower() if self.soup else ""
        for phrase in generic_phrases:
            if phrase in text:
                generic_signals += 1

        score = min(100, generic_signals * 12 + len(platforms) * 15)
        return {
            "generic_score": score,
            "detected_template": platforms[0] if platforms else "Unknown",
            "platforms": platforms,
            "sites_using_similar": 0,
            "is_custom": score < 30 and len(platforms) == 0,
        }

    def _content_sameness(self) -> Dict[str, Any]:
        text = self.soup.get_text(separator=" ", strip=True).lower() if self.soup else ""
        cliché_phrases = [
            "we are a leading", "best in class", "world-class", "industry-leading",
            "cutting-edge", "innovative solutions", "passionate about",
            "dedicated to", "committed to excellence", "years of experience",
            "customer satisfaction", "quality service", "trusted by",
        ]
        matched = [p for p in cliché_phrases if p in text]
        score = min(100, len(matched) * 10)
        return {
            "score": score,
            "matched_phrases": matched[:10],
            "sites_with_same_voice": 0,
        }

    def _visual_fingerprint(self) -> Dict[str, Any]:
        """Returns visual fingerprint data for VisualTwinMatcher in scorer.py"""
        if not self.soup:
            return {}

        img_count = len(self.soup.find_all("img"))
        video_count = len(self.soup.find_all("video"))
        has_hero = bool(self.soup.find("header")) or bool(self.soup.find(class_=re.compile("hero|banner", re.I)))
        has_cta = bool(self.soup.find("button")) or bool(self.soup.find(class_=re.compile("cta|btn", re.I)))
        colors = self._extract_colors()
        layout = self._extract_layout()

        return {
            "domain": self.domain,
            "url": self.url,
            "img_count": img_count,
            "video_count": video_count,
            "has_hero_section": has_hero,
            "has_cta": has_cta,
            "colors": colors,
            "layout": layout,
            "screenshot_path": None,
            "screenshot": None,
            "hash": hashlib.md5(self.raw_html.encode()).hexdigest()[:16],
            # Also include keys scorer.py expects for fallback matching
            "dominant_colors": colors,
            "font_families": self._extract_fonts(),
            "layout_ratios": {
                "has_hero": has_hero,
                "has_grid": layout.get("has_grid", False),
                "grid_columns": layout.get("div_count", 0) // 10,
                "sections": layout.get("section_count", 0),
            },
        }

    def _extract_colors(self) -> List[str]:
        colors = set()
        if not self.soup:
            return []
        for tag in self.soup.find_all(style=True):
            style = tag["style"]
            found = re.findall(r'#([0-9a-fA-F]{6})', style)
            colors.update([f"#{c}" for c in found])
        meta = self.soup.find("meta", attrs={"name": "theme-color"})
        if meta and meta.get("content"):
            colors.add(meta["content"])
        return list(colors)[:10]

    def _extract_fonts(self) -> List[str]:
        fonts = set()
        if not self.soup:
            return []
        for tag in self.soup.find_all(style=True):
            style = tag["style"]
            found = re.findall(r'''font-family:\s*['"]?([^;'"]+)''', style)
            fonts.update(found)
        for link in self.soup.find_all("link", rel="stylesheet"):
            href = link.get("href", "")
            if "fonts.googleapis.com" in href:
                found = re.findall(r'family=([^&:]+)', href)
                fonts.update(f.replace("+", " ") for f in found)
        return list(fonts)[:5]

    def _extract_layout(self) -> Dict[str, Any]:
        if not self.soup:
            return {}
        return {
            "has_nav": bool(self.soup.find("nav")),
            "has_footer": bool(self.soup.find("footer")),
            "has_sidebar": bool(self.soup.find("aside")),
            "has_grid": bool(self.soup.find(class_=re.compile("grid|row|col", re.I))),
            "section_count": len(self.soup.find_all("section")),
            "div_count": len(self.soup.find_all("div")),
        }

    def _check_ssl(self) -> Dict[str, Any]:
        try:
            hostname = self.domain.split(":")[0]
            context = ssl.create_default_context()
            with socket.create_connection((hostname, 443), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()
                    cipher = ssock.cipher()
                    version = ssock.version()
                    return {
                        "valid": True,
                        "issuer": cert.get("issuer", []),
                        "not_after": cert.get("notAfter"),
                        "version": version,
                        "cipher": cipher[0] if cipher else None,
                    }
        except Exception as e:
            return {"valid": False, "error": str(e)}

    def _check_security_headers(self, headers) -> Dict[str, Any]:
        headers_lower = {k.lower(): v for k, v in headers.items()}
        important = [
            "strict-transport-security",
            "content-security-policy",
            "x-frame-options",
            "x-content-type-options",
            "referrer-policy",
            "permissions-policy",
        ]
        present = {h: h in headers_lower for h in important}
        score = sum(present.values())
        return {
            "score": score,
            "max": len(important),
            "missing": [h for h, ok in present.items() if not ok],
            "present": {h: headers_lower.get(h, "") for h in important if h in headers_lower},
        }

    def _check_broken_links(self) -> Dict[str, Any]:
        if not self.soup:
            return {}
        links = set()
        for a in self.soup.find_all("a", href=True):
            href = a["href"]
            full = urljoin(self.url, href)
            if urlparse(full).netloc == self.domain:
                links.add(full)

        broken = []
        checked = 0
        for link in list(links)[:20]:
            try:
                r = requests.head(link, timeout=5, allow_redirects=True)
                if r.status_code >= 400:
                    broken.append({"url": link, "status": r.status_code})
                checked += 1
            except Exception:
                broken.append({"url": link, "status": "timeout/error"})
                checked += 1

        return {
            "checked": checked,
            "broken_count": len(broken),
            "broken": broken,
        }

    def _detect_business_type(self) -> Dict[str, Any]:
        text = self.soup.get_text(separator=" ", strip=True).lower() if self.soup else ""
        html = self.raw_html.lower()

        signals = {
            "ecommerce": ["cart", "checkout", "shop", "product", "buy now", "add to cart", "price", "shipping"],
            "saas": ["sign up", "free trial", "pricing plans", "dashboard", "login", "api", "software"],
            "local_service": ["book now", "appointment", "call us", "visit us", "hours", "location", "map"],
            "b2b": ["enterprise", "solution", "partners", "case study", "request a demo", "sales team"],
            "agency": ["portfolio", "clients", "our work", "hire us", "services", "creative"],
            "personal_brand": ["about me", "my story", "follow me", "subscribe", "blog", "coach"],
        }

        scores = {k: sum(1 for s in v if s in text or s in html) for k, v in signals.items()}
        best = max(scores, key=scores.get)
        confidence = min(100, scores[best] * 20)

        return {
            "detected_type": best if scores[best] > 0 else "unknown",
            "confidence": confidence,
            "signals": {k: v for k, v in scores.items() if v > 0},
        }

    def _calc_perf_score(self, timing: dict, load_time: float, issues: int) -> int:
        score = 100
        if load_time > 3:
            score -= 25
        elif load_time > 1.5:
            score -= 10
        score -= issues * 10
        srv = timing.get("server_response", 0)
        if srv > 1000:
            score -= 15
        return max(0, min(100, score))


# ── Backward compatibility alias ───────────────────────────────────────────
WebScraper = WebsiteScraper