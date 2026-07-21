"""
Revenue Readiness Scorer — Configuration
Single source of truth for all constants, thresholds, and templates.
"""

import os
from typing import List, Dict, Any, Set

# ── Core counts ───────────────────────────────────────────────────────────────
TOTAL_CHECKS: int = 35
CATEGORY_COUNT: int = 5
CATEGORY_NAMES: List[str] = [
    "trust_signals",
    "conversion_ready", 
    "seo_foundation",
    "content_quality",
    "technical_health",
]
TIER_NAMES: List[str] = ["free", "paid", "admin"]

# ── Delivery & pricing ─────────────────────────────────────────────────────────
DELIVERY_TIME_FREE: str = "10 seconds"
DELIVERY_TIME_PAID: str = "24 hours"
PRICING: Dict[str, int] = {"free": 0, "paid": 149, "roadmap": 299, "retainer": 997}

# ── Crawler limits ─────────────────────────────────────────────────────────────
MAX_PAGES_FREE: int = 8
MAX_PAGES_PAID: int = 30
MIN_PAGES_PER_TEMPLATE_PAID: int = 3

# ── Request / fetch limits ─────────────────────────────────────────────────────
REQUEST_TIMEOUT: int = 15
MAX_DOWNLOAD_SIZE: int = 10 * 1024 * 1024
PLAYWRIGHT_TIMEOUT: int = 30
BLOCKED_PORTS: List[int] = [22, 25, 3306, 5432, 6379, 27017, 3389, 5900]

# ── Private / reserved IP ranges ────────────────────────────────────────────────
PRIVATE_IP_RANGES: List[str] = [
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "127.0.0.0/8", "169.254.0.0/16", "0.0.0.0/32",
    "::1/128", "fc00::/7", "fe80::/10",
]

# ── Rate limiting ──────────────────────────────────────────────────────────────
RATE_LIMIT_FREE: str = "10/minute"
RATE_LIMIT_PAID: str = "100/minute"
REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# ── Stripe & Email ─────────────────────────────────────────────────────────────
STRIPE_WEBHOOK_SECRET: str = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
SMTP_HOST: str = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER: str = os.environ.get("SMTP_USER", "")
SMTP_PASS: str = os.environ.get("SMTP_PASS", "")
ALERT_EMAIL: str = os.environ.get("ALERT_EMAIL", "onlyonearpit@gmail.com")
RESEND_API_KEY: str = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM: str = os.environ.get("EMAIL_FROM", "RRS Alerts <onboarding@resend.dev>")
SCAN_PASS_SECRET: str = os.environ.get("SCAN_PASS_SECRET", "")
OWN_DOMAINS: Set[str] = {d.strip().lower() for d in os.environ.get("OWN_DOMAINS", "trilloka.com,www.trilloka.com").split(",") if d.strip()}

# ── Template type patterns ───────────────────────────────────────────────────────
TEMPLATE_PATTERNS: Dict[str, str] = {
    r"^/$|^/index\\.": "home",
    r"product|shop|item|sku|buy|store": "product",
    r"service|solution|offering|capabilities": "service",
    r"blog|article|news|post|story": "blog",
    r"location|near-me|city|branch|office|find-us": "location",
    r"contact|reach|get-in-touch|help": "contact",
    r"checkout|cart|payment|billing|order": "checkout",
    r"privacy|terms|policy|refund|shipping|legal|disclaimer": "policy",
}

# ── 35 Checkpoints ───────────────────────────────────────────────────────────
CHECKPOINTS: Dict[str, Dict[str, Any]] = {
    "trust_signals": {
        "weight": 0.25,
        "items": [
            {"name": "SSL Certificate", "weight": 2, "method": "check_ssl"},
            {"name": "Contact Info Visible", "weight": 3, "method": "check_contact"},
            {"name": "About Page Exists", "weight": 2, "method": "check_about"},
            {"name": "Team Photos Real", "weight": 3, "method": "check_team_photos"},
            {"name": "Social Proof", "weight": 3, "method": "check_reviews"},
            {"name": "Privacy Policy", "weight": 2, "method": "check_privacy"},
            {"name": "Terms of Service", "weight": 2, "method": "check_terms"},
            {"name": "Domain Age", "weight": 3, "method": "check_domain_age"},
        ]
    },
    "conversion_ready": {
        "weight": 0.30,
        "items": [
            {"name": "Clear CTA Above Fold", "weight": 4, "method": "check_cta"},
            {"name": "Mobile Responsive", "weight": 5, "method": "check_mobile"},
            {"name": "Page Load Speed", "weight": 5, "method": "check_speed"},
            {"name": "Booking/Quote System", "weight": 4, "method": "check_booking"},
            {"name": "Phone Number Clickable", "weight": 3, "method": "check_phone"},
            {"name": "Email Capture Form", "weight": 3, "method": "check_email_capture"},
            {"name": "Pricing Visible", "weight": 3, "method": "check_pricing"},
            {"name": "Testimonials Section", "weight": 3, "method": "check_testimonials"},
        ]
    },
    "seo_foundation": {
        "weight": 0.20,
        "items": [
            {"name": "Title Tags Optimized", "weight": 3, "method": "check_title"},
            {"name": "Meta Descriptions", "weight": 3, "method": "check_meta"},
            {"name": "H1 Hierarchy", "weight": 2, "method": "check_h1"},
            {"name": "Image Alt Text", "weight": 2, "method": "check_alt"},
            {"name": "Schema Markup", "weight": 3, "method": "check_schema"},
            {"name": "Internal Linking", "weight": 2, "method": "check_internal_links"},
            {"name": "XML Sitemap", "weight": 2, "method": "check_sitemap"},
            {"name": "Robots.txt", "weight": 1, "method": "check_robots"},
        ]
    },
    "content_quality": {
        "weight": 0.15,
        "items": [
            {"name": "Unique Content", "weight": 3, "method": "check_unique"},
            {"name": "No AI-Generated Patterns", "weight": 4, "method": "check_ai_patterns"},
            {"name": "Service Descriptions", "weight": 3, "method": "check_services"},
            {"name": "Blog/Updates", "weight": 2, "method": "check_blog"},
            {"name": "FAQ Section", "weight": 2, "method": "check_faq"},
            {"name": "Local SEO Content", "weight": 2, "method": "check_local"},
        ]
    },
    "technical_health": {
        "weight": 0.10,
        "items": [
            {"name": "No Broken Links", "weight": 3, "method": "check_broken"},
            {"name": "HTTPS Redirects", "weight": 2, "method": "check_redirects"},
            {"name": "Canonical Tags", "weight": 2, "method": "check_canonical"},
            {"name": "Structured Data", "weight": 3, "method": "check_structured"},
            {"name": "Favicon Present", "weight": 1, "method": "check_favicon"},
        ]
    }
}

# ── Severity thresholds ──────────────────────────────────────────────────────────
SEVERITY: Dict[str, tuple] = {
    "critical": (0, 34, "Critical", "Your site is losing revenue every day. Immediate action required."),
    "poor": (35, 54, "Poor", "Major gaps exist. Competitors are capturing your leads."),
    "fair": (55, 74, "Fair", "Functional but not competitive. Room for significant improvement."),
    "good": (75, 89, "Good", "Solid foundation. Fine-tuning will unlock growth."),
    "excellent": (90, 100, "Excellent", "Industry-leading. Maintain and optimize."),
}

# ── Future predictions ─────────────────────────────────────────────────────────
FUTURE_PREDICTIONS: Dict[str, Dict[int, int]] = {
    "critical": {3: 25, 6: 50, 12: 75},
    "poor": {3: 15, 6: 35, 12: 60},
    "fair": {3: 10, 6: 20, 12: 40},
    "good": {3: 5, 6: 10, 12: 20},
    "excellent": {3: 0, 6: 0, 12: 5},
}

# ── Content Evidence Signals checks ──────────────────────────────────────────────
CONTENT_EVIDENCE_CHECKS: List[Dict[str, Any]] = [
    {"name": "Author Byline / Authorship Schema", "weight": 3},
    {"name": "Original Images (not stock-only)", "weight": 3},
    {"name": "First-Hand Experience Language", "weight": 4},
    {"name": "Source Citations / Outbound Authority Links", "weight": 3},
    {"name": "Publication & Last-Modified Dates", "weight": 2},
    {"name": "Organization Info / About Page", "weight": 3},
    {"name": "Templated / Repetitive Passages", "weight": 3},
    {"name": "FAQ & Structured Data Accuracy", "weight": 2},
]

# ── Revenue Exposure Calculator defaults ───────────────────────────────────────
DEFAULT_TRAFFIC: int = 1000
DEFAULT_CONVERSION_RATE: float = 0.02
DEFAULT_AOV: float = 75.0
DEFAULT_PROFIT_MARGIN: float = 0.30
CALCULATOR_LABEL: str = "Illustrative Revenue Exposure — Not Measured Loss."
FREE_REPORT_CTA: str = "Upgrade for full evidence, root cause, and fix steps."

# ── Failure severity mapping ─────────────────────────────────────────────────
FAILURE_SEVERITY_BY_WEIGHT: Dict[int, str] = {
    1: "low", 2: "medium", 3: "high", 4: "critical", 5: "critical",
}

# ── JS framework signatures ────────────────────────────────────────────────────
JS_FRAMEWORK_SIGNATURES: Dict[str, str] = {
    "__NEXT_DATA__": "Next.js", "_next": "Next.js",
    "data-reactroot": "React", "react": "React",
    "vue": "Vue", "__VUE__": "Vue",
    "ng-app": "Angular", "angular": "Angular",
    "data-svelte": "Svelte", "svelte": "Svelte",
    "window.gatsby": "Gatsby", "___GATSBY": "Gatsby",
}

# ── Doppelgänger — Generic phrases ─────────────────────────────────────────────
GENERIC_PHRASES: List[str] = [
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

# ── Template fingerprints ──────────────────────────────────────────────────────
TEMPLATE_SIGNATURES: List[tuple] = [
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

# ── Social complaint keywords ────────────────────────────────────────────────────
COMPLAINT_KEYWORDS: tuple = (
    "broken", "not working", "doesn't work", "slow", "scam", "ripoff",
    "terrible", "worst", "avoid", "awful", "useless", "never again",
    "down", "error", "complaint", "bad experience", "unresponsive",
)


def get_total_checks() -> int:
    return sum(len(cfg["items"]) for cfg in CHECKPOINTS.values())


def get_category_check_count(category: str) -> int:
    return len(CHECKPOINTS.get(category, {}).get("items", []))


def get_failure_severity(weight: int) -> str:
    return FAILURE_SEVERITY_BY_WEIGHT.get(weight, "medium")
