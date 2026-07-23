#!/usr/bin/env python3
"""Report Generator — builds free and paid reports from scraped data."""
from typing import Any, Dict, List, Optional

from config import (
    TOTAL_CHECKS, SEVERITY, FUTURE_PREDICTIONS,
    DEFAULT_TRAFFIC, DEFAULT_CONVERSION_RATE, DEFAULT_AOV, DEFAULT_PROFIT_MARGIN,
    CALCULATOR_LABEL, FREE_REPORT_CTA, BUSINESS_TYPE_CHECKS,
)
from scorer import RevenueScorer
from content_evidence_signals import ContentEvidenceSignals


class ReportGenerator:
    def __init__(
        self,
        url: str,
        revenue_scorer: RevenueScorer,
        content_evidence: ContentEvidenceSignals,
        data: Dict[str, Any],
        top_failures: List[Dict[str, Any]],
        calculator_inputs: Optional[Dict[str, Any]] = None,
    ):
        self.url = url
        self.revenue_scorer = revenue_scorer
        self.content_evidence = content_evidence
        self.data = data
        self.top_failures = top_failures
        self.calculator_inputs = calculator_inputs

    def _scan_quality(self) -> str:
        pages_sampled = self.data.get("pages_sampled", 0)
        has_errors = "error" in self.data
        html_length = self.data.get("html_length", 0)
        raw_html = self.data.get("raw_html", "")
        if has_errors or pages_sampled < 1 or html_length < 3000 or len(raw_html) < 3000:
            return "insufficient"
        categories = ["trust", "conversion", "seo", "content", "technical"]
        total_signals = 0
        for cat in categories:
            cat_data = self.data.get(cat, {})
            if isinstance(cat_data, dict):
                total_signals += len([v for v in cat_data.values() if v is not None and v != ""])
        if total_signals < 3:
            return "insufficient"
        return "good"

    def _severity_label(self, readiness: int, quality: str) -> Dict[str, str]:
        if quality == "insufficient":
            return {
                "key": "unknown",
                "label": "Scan Limited",
                "desc": "We couldn't fully analyze this site. It may use enterprise bot protection. Try a small business site for full results.",
            }
        if readiness >= 75:
            return {"key": "good", "label": "Revenue Ready", "desc": "Your site has strong foundations. Minor tweaks can unlock more revenue."}
        elif readiness >= 50:
            return {"key": "warning", "label": "Needs Work", "desc": "Several revenue-critical elements are missing or weak. Fixes will improve conversions."}
        elif readiness >= 25:
            return {"key": "poor", "label": "At Risk", "desc": "Major revenue blockers detected. Immediate fixes recommended."}
        else:
            return {"key": "critical", "label": "Critical", "desc": "Your site is losing revenue every day. Immediate action required."}

    def _future_prediction(self, readiness: int) -> Dict[str, int]:
        return {"3": min(readiness + 25, 100), "6": min(readiness + 45, 100), "12": min(readiness + 60, 100)}

    def _revenue_teaser(self) -> Dict[str, Any]:
        traffic = self.calculator_inputs.get("traffic", DEFAULT_TRAFFIC) if self.calculator_inputs else DEFAULT_TRAFFIC
        conversion_rate = self.calculator_inputs.get("conversion_rate", DEFAULT_CONVERSION_RATE) if self.calculator_inputs else DEFAULT_CONVERSION_RATE
        aov = self.calculator_inputs.get("aov", DEFAULT_AOV) if self.calculator_inputs else DEFAULT_AOV
        profit_margin = self.calculator_inputs.get("profit_margin", DEFAULT_PROFIT_MARGIN) if self.calculator_inputs else DEFAULT_PROFIT_MARGIN
        monthly_revenue = traffic * conversion_rate * aov
        monthly_profit = monthly_revenue * profit_margin
        annual_exposure = monthly_profit * 12
        readiness_gap = 1.0 - (self.revenue_scorer.get_readiness_score() / 100.0)
        return {
            "label": CALCULATOR_LABEL,
            "assumptions_banner": "Values shown are conservative industry estimates. Provide your actual numbers for a personalized projection.",
            "conservative_scenario": {
                "traffic": traffic,
                "conversion_rate": conversion_rate,
                "aov": aov,
                "profit_margin": profit_margin,
                "monthly_revenue": round(monthly_revenue, 2),
                "monthly_profit": round(monthly_profit, 2),
                "annual_exposure": round(annual_exposure, 2),
                "readiness_gap": round(readiness_gap, 2),
            },
        }

    def generate_free(self) -> Dict[str, Any]:
        scores = self.revenue_scorer.get_scores()
        readiness = scores.get("readiness_score", 0)
        quality = self._scan_quality()
        severity = self._severity_label(readiness, quality)
        failure_summary = []
        for f in self.top_failures[:20]:
            failure_summary.append({
                "category": f.get("category", "unknown"),
                "item": f.get("item", "unknown"),
                "severity": f.get("severity", "medium"),
                "one_liner": f.get("one_liner", ""),
                "completed": False,
            })
        evidence_signals = []
        if hasattr(self.content_evidence, 'signals'):
            for sig in self.content_evidence.signals:
                evidence_signals.append({
                    "name": sig.get("name", ""),
                    "status": sig.get("status", "unknown"),
                    "detail": sig.get("detail", ""),
                })
        report = {
            "type": "free",
            "url": self.url,
            "timestamp": self.data.get("timestamp", ""),
            "scan_quality": quality,
            "scores": scores,
            "severity": severity,
            "content_evidence_signals": evidence_signals,
            "future_prediction": self._future_prediction(readiness),
            "visible_failures": self.top_failures[:5],
            "failure_summary": failure_summary,
            "hidden_failure_count": max(0, TOTAL_CHECKS - len(failure_summary)),
            "upgrade_cta": FREE_REPORT_CTA,
            "pages_sampled": self.data.get("pages_sampled", 0),
            "template_breakdown": self.data.get("template_breakdown", {}),
            "template_fingerprint": self.data.get("template_fingerprint", {}),
            "content_sameness": self.data.get("content_sameness", {}),
            "visual_twin": self.data.get("visual_twin", {}),
            "revenue_exposure_teaser": self._revenue_teaser(),
            "business_type": self.data.get("business_type", {}),
            "performance": self.data.get("performance", {}),
        }
        if quality == "insufficient":
            report["insufficient_scan_message"] = (
                "We couldn't fully analyze this website. It may use enterprise-grade bot protection. "
                "Try scanning a small business website instead for full results."
            )
            report["can_show_preview"] = False
        else:
            report["can_show_preview"] = True
        return report

    def generate_paid(self) -> Dict[str, Any]:
        free_report = self.generate_free()
        free_report["type"] = "paid"
        free_report["upgrade_cta"] = "Full report with actionable fix steps."
        fix_steps = []
        btype = self.data.get("business_type", {}).get("detected_type", "unknown")
        for f in self.top_failures:
            fix_steps.append({
                "category": f.get("category", ""),
                "item": f.get("item", ""),
                "severity": f.get("severity", ""),
                "fix_steps": self._generate_fix_steps(f, btype),
            })
        free_report["fix_steps"] = fix_steps
        return free_report

    def generate_roadmap(self) -> Dict[str, Any]:
        report = self.generate_paid()
        report["type"] = "roadmap"
        report["upgrade_cta"] = "Full report with week-by-week fix roadmap."
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        ordered = sorted(self.top_failures, key=lambda f: sev_order.get(str(f.get("severity", "low")).lower(), 3))
        buckets = [
            ("Week 1", "Stop the bleeding - critical revenue blockers first", ordered[0:6]),
            ("Week 2", "Build trust and credibility", ordered[6:12]),
            ("Week 3", "Content and search depth", ordered[12:18]),
            ("Week 4", "Polish, speed, and measurement", ordered[18:]),
        ]
        weeks = []
        btype = self.data.get("business_type", {}).get("detected_type", "unknown")
        for name, focus, items in buckets:
            if not items:
                continue
            weeks.append({
                "week": name,
                "focus": focus,
                "items": [{"item": f.get("item", ""), "severity": f.get("severity", ""),
                           "steps": self._generate_fix_steps(f, btype)} for f in items],
            })
        report["roadmap"] = weeks
        return report

    def _generate_fix_steps(self, failure: Dict[str, Any], business_type: str = "unknown") -> List[str]:
        item = failure.get("item", "").lower()
        # Business-type specific overrides
        if business_type == "ecommerce":
            ecommerce_steps = {
                "page load speed": [
                    "Compress product images to WebP (aim <200KB each)",
                    "Enable lazy loading for below-fold product images",
                    "Use a CDN for static assets (Cloudflare, BunnyCDN)",
                    "Minify CSS/JS and defer non-critical scripts",
                ],
                "clear cta above fold": [
                    "Add 'Add to Cart' button visible without scrolling on product pages",
                    "Use sticky 'Buy Now' bar on mobile product pages",
                    "Highlight free shipping threshold above the fold",
                ],
                "mobile responsive": [
                    "Test checkout flow on actual iPhone/Android devices",
                    "Ensure product image zoom works with pinch gestures",
                    "Make filter/sort controls thumb-friendly (min 44px tap targets)",
                ],
            }
            if item in ecommerce_steps:
                return ecommerce_steps[item]
        elif business_type == "saas":
            saas_steps = {
                "page load speed": [
                    "Code-split your React/Vue bundle to reduce initial JS load",
                    "Use server-side rendering (SSR) for landing pages",
                    "Optimize hero LCP image (preload, proper sizing)",
                    "Implement edge caching for marketing pages",
                ],
                "clear cta above fold": [
                    "Replace 'Learn More' with 'Start Free Trial' or 'Get Demo'",
                    "Add social proof ( logos, G2/Capterra badges) next to CTA",
                    "Use contrasting color for primary CTA button",
                ],
                "mobile responsive": [
                    "Ensure pricing table is swipeable on mobile",
                    "Test signup form autofill on mobile keyboards",
                    "Verify video embeds don't break mobile layout",
                ],
            }
            if item in saas_steps:
                return saas_steps[item]
        elif business_type == "local_service":
            local_steps = {
                "page load speed": [
                    "Compress before/after gallery images",
                    "Embed Google Maps efficiently (static image fallback)",
                    "Minimize third-party booking widget scripts",
                ],
                "clear cta above fold": [
                    "Add 'Book Appointment' button with calendar integration",
                    "Display phone number as prominent click-to-call button",
                    "Show 'Accepting New Patients/Clients' badge",
                ],
                "mobile responsive": [
                    "Ensure click-to-call button is thumb-sized and sticky",
                    "Test online booking form on mobile (date picker, dropdowns)",
                    "Verify driving directions link opens native maps app",
                ],
            }
            if item in local_steps:
                return local_steps[item]
        # Generic fallback steps
        steps = {
            "page load speed": [
                "Compress images using WebP format",
                "Enable browser caching via .htaccess or nginx config",
                "Use a CDN for static assets",
                "Minify CSS and JavaScript files",
            ],
            "clear cta above fold": [
                "Add a prominent call-to-action button in the hero section",
                "Use contrasting colors for the CTA button",
                "Keep CTA text action-oriented (e.g., 'Get Quote', 'Book Now')",
            ],
            "mobile responsive": [
                "Test site on actual mobile devices, not just browser resize",
                "Use responsive breakpoints for common screen sizes",
                "Ensure touch targets are at least 44px wide",
            ],
            "contact info visible": [
                "Add phone number and email to header or footer",
                "Include a contact page link in main navigation",
                "Display business hours prominently",
            ],
            "social proof": [
                "Add 3-5 customer testimonials to homepage",
                "Include client logos if B2B",
                "Display review counts from Google/Yelp",
            ],
            "title tags optimized": [
                "Keep titles under 60 characters",
                "Include primary keyword near the beginning",
                "Make each page title unique",
            ],
            "meta descriptions": [
                "Write compelling descriptions under 160 characters",
                "Include a call-to-action in the description",
                "Use unique descriptions for every page",
            ],
        }
        return steps.get(item, [
            f"Review and improve {item.replace('_', ' ')}",
            "Check competitor sites for best practices",
            "Implement changes and test conversion impact",
        ])
