import os
import json
import time
import asyncio
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin, urlparse

# Graceful Playwright import
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

class WebScraper:
    def __init__(self):
        self.results = {}
        self.browser = None
        self.playwright = None
        
    async def init_browser(self, headless: bool = True):
        """Initialize browser with graceful fallback"""
        if not PLAYWRIGHT_AVAILABLE:
            print("WARNING: Playwright not available. Browser features disabled.")
            return False
            
        try:
            self.playwright = await async_playwright().start()
            
            # Docker/Railway-friendly launch args
            launch_args = {
                'headless': headless,
                'args': [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-software-rasterizer',
                    '--disable-extensions',
                    '--disable-background-networking',
                    '--disable-background-timer-throttling',
                    '--disable-backgrounding-occluded-windows',
                    '--disable-breakpad',
                    '--disable-component-extensions-with-background-pages',
                    '--disable-features=TranslateUI,BlinkGenPropertyTrees',
                    '--disable-ipc-flooding-protection',
                    '--disable-renderer-backgrounding',
                    '--force-color-profile=srgb',
                    '--metrics-recording-only',
                ]
            }
            
            self.browser = await self.playwright.chromium.launch(**launch_args)
            return True
            
        except Exception as e:
            print(f"ERROR: Failed to launch browser: {e}")
            self.browser = None
            return False
    
    async def close_browser(self):
        """Clean up browser resources"""
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
    
    async def scrape_page(self, url: str, take_screenshot: bool = False) -> Dict[str, Any]:
        """Scrape a single page with metadata extraction"""
        if not self.browser:
            await self.init_browser()
            
        if not self.browser:
            return {
                'url': url,
                'error': 'Browser not available',
                'status': 'failed'
            }
        
        page = None
        try:
            page = await self.browser.new_page(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0'
            )
            
            # Set extra headers to avoid bot detection
            await page.set_extra_http_headers({
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            })
            
            response = await page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Extract metadata
            title = await page.title()
            
            # Get meta description
            description = ''
            meta_desc = await page.query_selector('meta[name="description"]')
            if meta_desc:
                description = await meta_desc.get_attribute('content') or ''
            
            # Get all links
            links = await page.eval_on_selector_all('a[href]', 
                'elements => elements.map(e => ({href: e.href, text: e.innerText.trim()}))')
            
            # Get headings
            h1_tags = await page.eval_on_selector_all('h1', 
                'elements => elements.map(e => e.innerText.trim())')
            
            result = {
                'url': url,
                'status': 'success',
                'title': title,
                'description': description,
                'status_code': response.status if response else None,
                'links_found': len(links),
                'links': links[:20],  # Limit to first 20
                'h1_tags': h1_tags,
                'timestamp': time.time()
            }
            
            # Take screenshot if requested
            if take_screenshot:
                screenshot_path = f'/tmp/screenshot_{int(time.time())}.png'
                await page.screenshot(path=screenshot_path, full_page=True)
                result['screenshot_path'] = screenshot_path
            
            return result
            
        except Exception as e:
            return {
                'url': url,
                'error': str(e),
                'status': 'failed'
            }
        finally:
            if page:
                await page.close()
    
    async def run_lighthouse(self, url: str) -> Dict[str, Any]:
        """
        Run Lighthouse-like performance analysis using Playwright
        (Graceful fallback if browser unavailable)
        """
        if not self.browser:
            success = await self.init_browser()
            if not success:
                return {
                    'url': url,
                    'error': 'Browser not available for Lighthouse analysis',
                    'status': 'failed'
                }
        
        page = None
        try:
            page = await self.browser.new_page()
            
            # Collect performance metrics
            start_time = time.time()
            
            response = await page.goto(url, wait_until='networkidle', timeout=30000)
            load_time = time.time() - start_time
            
            # Get performance timing via JS
            timing = await page.evaluate('''() => {
                const t = performance.timing;
                return {
                    dns_lookup: t.domainLookupEnd - t.domainLookupStart,
                    tcp_connection: t.connectEnd - t.connectStart,
                    server_response: t.responseEnd - t.requestStart,
                    dom_processing: t.domComplete - t.domLoading,
                    total_load: t.loadEventEnd - t.navigationStart
                };
            }''')
            
            # Get resource count and size
            resources = await page.evaluate('''() => {
                return performance.getEntriesByType('resource').map(r => ({
                    name: r.name,
                    type: r.initiatorType,
                    size: r.transferSize,
                    duration: r.duration
                }));
            }''')
            
            total_size = sum(r.get('size', 0) for r in resources)
            
            # Check for common issues
            issues = []
            
            # Check for large images
            large_images = [r for r in resources if r.get('type') == 'img' and r.get('size', 0) > 500000]
            if large_images:
                issues.append(f"Found {len(large_images)} images larger than 500KB")
            
            # Check render-blocking resources
            render_blocking = [r for r in resources if r.get('name', '').endswith(('.css', '.js')) and r.get('size', 0) > 100000]
            if render_blocking:
                issues.append(f"Found {len(render_blocking)} large render-blocking resources")
            
            return {
                'url': url,
                'status': 'success',
                'performance': {
                    'load_time_seconds': round(load_time, 2),
                    'timing': timing,
                    'total_transfer_size_kb': round(total_size / 1024, 2),
                    'resource_count': len(resources)
                },
                'issues': issues,
                'score': self._calculate_score(timing, load_time, len(issues))
            }
            
        except Exception as e:
            return {
                'url': url,
                'error': str(e),
                'status': 'failed'
            }
        finally:
            if page:
                await page.close()
    
    async def test_mobile_responsive(self, url: str) -> Dict[str, Any]:
        """
        Test mobile responsiveness by emulating different devices
        """
        if not self.browser:
            success = await self.init_browser()
            if not success:
                return {
                    'url': url,
                    'error': 'Browser not available for mobile testing',
                    'status': 'failed'
                }
        
        devices = [
            {'name': 'iPhone 12 Pro', 'width': 390, 'height': 844, 'device_scale_factor': 3},
            {'name': 'iPad Air', 'width': 820, 'height': 1180, 'device_scale_factor': 2},
            {'name': 'Pixel 5', 'width': 393, 'height': 851, 'device_scale_factor': 2.75},
            {'name': 'Desktop', 'width': 1920, 'height': 1080, 'device_scale_factor': 1}
        ]
        
        results = []
        
        for device in devices:
            page = None
            try:
                context = await self.browser.new_context(
                    viewport={'width': device['width'], 'height': device['height']},
                    device_scale_factor=device['device_scale_factor'],
                    user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15'
                )
                page = await context.new_page()
                
                await page.goto(url, wait_until='networkidle', timeout=30000)
                
                # Check for viewport meta tag
                viewport_meta = await page.query_selector('meta[name="viewport"]')
                has_viewport = viewport_meta is not None
                
                # Check for horizontal scroll (indicates non-responsive)
                has_horizontal_scroll = await page.evaluate('''() => {
                    return document.documentElement.scrollWidth > window.innerWidth;
                }''')
                
                # Take screenshot
                screenshot_path = f'/tmp/mobile_{device["name"].replace(" ", "_")}_{int(time.time())}.png'
                await page.screenshot(path=screenshot_path)
                
                results.append({
                    'device': device['name'],
                    'viewport': f"{device['width']}x{device['height']}",
                    'has_viewport_meta': has_viewport,
                    'has_horizontal_scroll': has_horizontal_scroll,
                    'is_responsive': not has_horizontal_scroll,
                    'screenshot': screenshot_path
                })
                
                await context.close()
                
            except Exception as e:
                results.append({
                    'device': device['name'],
                    'error': str(e),
                    'is_responsive': False
                })
            finally:
                if page:
                    await page.close()
        
        # Calculate overall score
        responsive_count = sum(1 for r in results if r.get('is_responsive', False))
        score = (responsive_count / len(devices)) * 100 if devices else 0
        
        return {
            'url': url,
            'status': 'success',
            'devices_tested': len(devices),
            'responsive_devices': responsive_count,
            'overall_score': round(score, 1),
            'device_results': results,
            'is_fully_responsive': score == 100
        }
    
    def _calculate_score(self, timing: dict, load_time: float, issues_count: int) -> int:
        """Calculate a simple performance score (0-100)"""
        score = 100
        
        # Deduct for slow load
        if load_time > 3:
            score -= 20
        elif load_time > 1.5:
            score -= 10
        
        # Deduct for issues
        score -= issues_count * 10
        
        # Deduct for slow server response
        server_time = timing.get('server_response', 0)
        if server_time > 1000:
            score -= 15
        
        return max(0, min(100, score))
    
    async def crawl_site(self, start_url: str, max_pages: int = 10) -> List[Dict[str, Any]]:
        """Crawl a site starting from a URL"""
        if not self.browser:
            await self.init_browser()
            
        if not self.browser:
            return [{'error': 'Browser not available', 'url': start_url}]
        
        visited = set()
        to_visit = [start_url]
        results = []
        
        while to_visit and len(visited) < max_pages:
            url = to_visit.pop(0)
            if url in visited:
                continue
                
            visited.add(url)
            result = await self.scrape_page(url)
            results.append(result)
            
            # Add new links to queue
            if result.get('status') == 'success':
                for link in result.get('links', []):
                    href = link.get('href', '')
                    if href and href.startswith(start_url) and href not in visited:
                        to_visit.append(href)
        
        return results


# Synchronous wrapper for easy use
class ScraperSync:
    def __init__(self):
        self.scraper = WebScraper()
        self._loop = None
    
    def _get_loop(self):
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop
    
    def scrape(self, url: str, **kwargs):
        """Synchronous scrape wrapper"""
        loop = self._get_loop()
        return loop.run_until_complete(self.scraper.scrape_page(url, **kwargs))
    
    def lighthouse(self, url: str):
        """Synchronous Lighthouse wrapper"""
        loop = self._get_loop()
        return loop.run_until_complete(self.scraper.run_lighthouse(url))
    
    def mobile_test(self, url: str):
        """Synchronous mobile test wrapper"""
        loop = self._get_loop()
        return loop.run_until_complete(self.scraper.test_mobile_responsive(url))
    
    def crawl(self, url: str, max_pages: int = 10):
        """Synchronous crawl wrapper"""
        loop = self._get_loop()
        return loop.run_until_complete(self.scraper.crawl_site(url, max_pages))
    
    def close(self):
        """Clean up resources"""
        if self.scraper.browser:
            loop = self._get_loop()
            loop.run_until_complete(self.scraper.close_browser())
        if self._loop and not self._loop.is_closed():
            self._loop.close()


# Example usage
if __name__ == '__main__':
    scraper = ScraperSync()
    try:
        # Test basic scrape
        result = scraper.scrape('https://example.com')
        print(json.dumps(result, indent=2))
        
        # Test Lighthouse
        lighthouse = scraper.lighthouse('https://example.com')
        print(json.dumps(lighthouse, indent=2))
        
        # Test mobile
        mobile = scraper.mobile_test('https://example.com')
        print(json.dumps(mobile, indent=2))
        
    finally:
        scraper.close()

# Alias for backward compatibility
WebsiteScraper = WebScraper