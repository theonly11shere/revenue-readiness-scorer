#!/usr/bin/env python3
"""
RRS API — FastAPI backend with static file serving.
"""

import os
import time
import hashlib
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator
import redis
import stripe

from config import (
    PRICING, DELIVERY_TIME_FREE, DELIVERY_TIME_PAID,
    RATE_LIMIT_FREE, RATE_LIMIT_PAID, REDIS_URL,
    STRIPE_WEBHOOK_SECRET, OWN_DOMAINS,
    TOTAL_CHECKS, CATEGORY_COUNT,
)
from security import SecurityGuard, RateLimitExceeded
from scraper import WebsiteScraper
from scorer import (
    RevenueScorer, TemplateFingerprinter, ContentSamenessChecker,
    VisualTwinMatcher, CopycatIndexScorer, SocialSignalsFetcher,
)
from content_evidence_signals import ContentEvidenceSignals
from reporter import ReportGenerator

# ── Paths ─────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# ── Redis Setup ───────────────────────────────────────────
try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
except Exception:
    redis_client = None

# ── Stripe Setup ──────────────────────────────────────────
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

# ── FastAPI App ───────────────────────────────────────────
app = FastAPI(
    title="Revenue Readiness Scorer",
    description="The only audit that checks whether a stranger would trust your site enough to pay.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files directory
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ── Pydantic Models ───────────────────────────────────────

class ScanRequest(BaseModel):
    url: str = Field(..., min_length=4, max_length=500, description="Domain or URL to scan")
    tier: str = Field(default="free", pattern="^(free|paid)$")
    use_playwright: Optional[bool] = None

    @validator("url")
    def validate_url(cls, v):
        v = v.strip().lower()
        if not v.startswith("http"):
            v = f"https://{v}"
        is_valid, error = SecurityGuard.validate_url(v)
        if not is_valid:
            raise ValueError(error)
        return v


class CalculatorRequest(BaseModel):
    traffic: int = Field(default=1000, ge=0, le=100_000_000)
    conversion_rate: float = Field(default=0.02, ge=0.0, le=1.0)
    average_order_value: float = Field(default=75.0, ge=0.0)
    profit_margin: float = Field(default=0.30, ge=0.0, le=1.0)


class PaymentRequest(BaseModel):
    tier: str = Field(..., pattern="^(paid|roadmap|retainer)$")
    domain: str = Field(..., min_length=3, max_length=200)
    success_url: str
    cancel_url: str


# ── Rate Limiting ─────────────────────────────────────────

def check_rate_limit(client_ip: str, tier: str = "free") -> bool:
    if not redis_client:
        return True
    key = f"rate_limit:{tier}:{client_ip}"
    limit = 10 if tier == "free" else 100
    current = redis_client.get(key)
    if current and int(current) >= limit:
        return False
    pipe = redis_client.pipeline()
    pipe.incr(key)
    pipe.expire(key, 60)
    pipe.execute()
    return True


async def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Trilloka Guardrail ────────────────────────────────────

def get_trilloka_attitude(domain: str) -> dict:
    """Special response when someone tries to scan Trilloka itself."""
    domain_clean = SecurityGuard.sanitize_domain(domain)
    own_domains = {"trilloka.com", "www.trilloka.com", "trilloka"}
    is_trilloka = domain_clean in own_domains or domain.lower().strip() in own_domains

    if not is_trilloka:
        return {"is_trilloka": False}

    return {
        "is_trilloka": True,
        "attitude": "supreme",
        "message": "Nice try. Scanning the architect's own work? Bold move.",
        "quips": [
            "We wrote the rules you're trying to grade us by.",
            "This is like bringing a ruler to measure a skyscraper.",
            "While you were reading this, we already updated the algorithm.",
            "Nice try. But we know every heuristic we built — because we built them.",
            "Our template trap score is negative because we ARE the trap.",
        ],
        "scores": {
            "template_trap": {"score": 2, "label": "Architect", "note": "We don't use templates. We build them. Then watch others copy."},
            "sameness": {"score": 3, "label": "Originator", "note": "You can't be cliché when you wrote the language everyone else is speaking."},
            "visual_twin": {"score": 1, "label": "Unique", "note": "Zero visual matches. Our orbital layout is patented in arrogance."},
            "presence": {"score": 100, "label": "Omnipresent", "note": "We don't chase presence. Presence chases us."},
        },
        "overall": {
            "readiness": 97,
            "evidence": 99,
            "confidence": 98,
        },
        "revenue_exposure": {
            "message": "Our revenue isn't exposed — it's projected. Try scanning a site that actually needs help.",
            "monthly": "More than your annual.",
            "annual": "More than you'll measure in this lifetime.",
        }
    }


# ── Static Pages ──────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the landing page."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>RRS API</h1><p>Landing page not found. Place index.html in /static/</p>")


@app.get("/results", response_class=HTMLResponse)
@app.get("/results.html", response_class=HTMLResponse)
async def serve_results():
    """Serve the results dashboard."""
    results_path = os.path.join(STATIC_DIR, "results.html")
    if os.path.exists(results_path):
        with open(results_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>RRS Results</h1><p>Results page not found. Place results.html in /static/</p>")


# ── API Endpoints ─────────────────────────────────────────



@app.get("/vlog", response_class=HTMLResponse)
@app.get("/vlog.html", response_class=HTMLResponse)
async def serve_vlog():
    """Serve the vlog page."""
    vlog_path = os.path.join(STATIC_DIR, "vlog.html")
    if os.path.exists(vlog_path):
        with open(vlog_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Vlog</h1><p>Vlog page not found.</p>")


@app.get("/contact", response_class=HTMLResponse)
@app.get("/contact.html", response_class=HTMLResponse)
async def serve_contact():
    """Serve the contact page."""
    contact_path = os.path.join(STATIC_DIR, "contact.html")
    if os.path.exists(contact_path):
        with open(contact_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Contact</h1><p>Contact page not found.</p>")

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "2.0.0"}


@app.post("/api/v1/scan")
async def scan_website(request: Request, scan_req: ScanRequest):
    """Main scan endpoint — returns the 4 Doppelgänger metrics."""
    client_ip = await get_client_ip(request)

    if not check_rate_limit(client_ip, scan_req.tier):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again in a minute.")

    domain = SecurityGuard.sanitize_domain(scan_req.url)

    # Trilloka guardrail
    trilloka = get_trilloka_attitude(domain)
    if trilloka.get("is_trilloka"):
        return JSONResponse(content=trilloka)

    # Normal scan flow
    try:
        scraper = WebsiteScraper(scan_req.url, tier=scan_req.tier, use_playwright=scan_req.use_playwright)
        data = scraper.scrape()

        if "error" in data:
            raise HTTPException(status_code=422, detail=f"Scan failed: {data['error']}")

        # Run scoring
        revenue_scorer = RevenueScorer(data)
        scores = revenue_scorer.calculate_scores()
        top_failures = revenue_scorer.get_top_failures(n=10)

        # Extract Doppelgänger metrics
        template_fp = data.get("template_fingerprint", {})
        content_same = data.get("content_sameness", {})
        visual_twin = data.get("visual_twin", {})

        # Social signals
        brand = domain.split(".")[0]
        social = SocialSignalsFetcher(brand, domain)
        social_data = social.scan(max_signals=4)

        # Content evidence
        soup_text = ""
        if "raw_html" in data:
            from bs4 import BeautifulSoup
            soup_text = BeautifulSoup(data["raw_html"], "html.parser").get_text()
        all_texts = [soup_text] + [p.get("raw_text", "") for p in data.get("pages", [])]
        evidence = ContentEvidenceSignals(
            BeautifulSoup(data.get("raw_html", ""), "html.parser"),
            scan_req.url,
            all_texts,
        )

        # Build the 4-metric response
        response = {
            "domain": domain,
            "timestamp": datetime.now().isoformat(),
            "tier": scan_req.tier,
            "scan_quality": "good" if data.get("pages_sampled", 0) > 0 else "insufficient",
            "rendering_engine": data.get("rendering_engine", "static"),
            "detected_framework": data.get("detected_framework"),
            "pages_sampled": data.get("pages_sampled", 0),

            # The 4 Doppelgänger Metrics
            "metrics": {
                "template_trap": {
                    "score": template_fp.get("generic_score", 50),
                    "label": _template_label(template_fp.get("generic_score", 50)),
                    "detected_template": template_fp.get("detected_template", "Unknown"),
                    "platforms": template_fp.get("platforms", []),
                    "sites_using_similar": template_fp.get("sites_using_similar", 0),
                    "is_custom": template_fp.get("is_custom", False),
                },
                "sameness": {
                    "score": content_same.get("score", 0),
                    "label": _sameness_label(content_same.get("score", 0)),
                    "matched_phrases": content_same.get("matched_phrases", []),
                    "sites_with_same_voice": content_same.get("sites_with_same_voice", 0),
                },
                "visual_twin": {
                    "similarity_percent": visual_twin.get("similarity_percent", 0),
                    "label": _visual_label(visual_twin.get("similarity_percent", 0)),
                    "closest_match_url": visual_twin.get("closest_match_url"),
                    "matching_elements": visual_twin.get("matching_elements", []),
                },
                "presence": {
                    "score": social_data.get("presence_score", 0),
                    "label": social_data.get("verdict_label", "Unknown"),
                    "mentions_found": social_data.get("mentions_found", 0),
                    "complaints_found": social_data.get("complaints_found", 0),
                    "signals": social_data.get("signals", []),
                },
            },

            # Three-Score System
            "scores": scores,

            # Evidence signals
            "content_evidence": {
                "score": evidence.get_score(),
                "signals": evidence.get_signals(),
            },

            # Failures
            "top_failures": top_failures[:5] if scan_req.tier == "free" else top_failures,
            "hidden_failure_count": max(0, TOTAL_CHECKS - len(top_failures)),

            # Revenue exposure teaser
            "revenue_exposure": _build_revenue_teaser(scores.get("readiness_score", 0)),

            # CTA
            "upgrade_cta": "Upgrade for full evidence, root cause, and fix steps." if scan_req.tier == "free" else None,
        }

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scan error: {str(e)}")


@app.post("/api/v1/calculate")
async def calculate_revenue(calc: CalculatorRequest):
    """Revenue exposure calculator with three scenarios."""
    traffic = calc.traffic
    conversion = calc.conversion_rate
    aov = calc.average_order_value
    margin = calc.profit_margin

    def calc_revenue(t, c, a, m):
        monthly = t * c * a
        profit = monthly * m
        annual = profit * 12
        return round(monthly, 2), round(profit, 2), round(annual, 2)

    cons_monthly, cons_profit, cons_annual = calc_revenue(
        traffic * 0.5, max(conversion * 0.5, 0.005), aov * 0.7, margin * 0.8
    )
    exp_monthly, exp_profit, exp_annual = calc_revenue(traffic, conversion, aov, margin)
    high_monthly, high_profit, high_annual = calc_revenue(
        traffic * 2, min(conversion * 1.5, 0.5), aov * 1.3, margin
    )

    return {
        "label": "Illustrative Revenue Exposure — Not Measured Loss.",
        "assumptions_banner": "Values shown are estimates. Provide your actual numbers for a personalized projection.",
        "scenarios": {
            "conservative": {
                "traffic": int(traffic * 0.5),
                "conversion_rate": round(max(conversion * 0.5, 0.005), 4),
                "aov": round(aov * 0.7, 2),
                "profit_margin": round(margin * 0.8, 2),
                "monthly_revenue": cons_monthly,
                "monthly_profit": cons_profit,
                "annual_exposure": cons_annual,
            },
            "expected": {
                "traffic": traffic,
                "conversion_rate": conversion,
                "aov": aov,
                "profit_margin": margin,
                "monthly_revenue": exp_monthly,
                "monthly_profit": exp_profit,
                "annual_exposure": exp_annual,
            },
            "high_exposure": {
                "traffic": int(traffic * 2),
                "conversion_rate": round(min(conversion * 1.5, 0.5), 4),
                "aov": round(aov * 1.3, 2),
                "profit_margin": margin,
                "monthly_revenue": high_monthly,
                "monthly_profit": high_profit,
                "annual_exposure": high_annual,
            },
        },
    }


@app.post("/api/v1/create-checkout")
async def create_checkout(payment: PaymentRequest):
    """Create Stripe checkout session."""
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Payment system not configured")

    price = PRICING.get(payment.tier, 0)
    if price == 0:
        raise HTTPException(status_code=400, detail="Invalid tier")

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"RRS {payment.tier.title()} Report — {payment.domain}"},
                    "unit_amount": price * 100,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=payment.success_url,
            cancel_url=payment.cancel_url,
            metadata={"domain": payment.domain, "tier": payment.tier},
        )
        return {"session_id": session.id, "url": session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Payment error: {str(e)}")


@app.post("/api/v1/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhooks with signature verification."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        domain = session.get("metadata", {}).get("domain", "")
        tier = session.get("metadata", {}).get("tier", "paid")
        if redis_client:
            redis_client.setex(f"paid:{domain}", 86400 * 30, tier)

    return {"status": "success"}


# ── Helper Functions ──────────────────────────────────────

def _template_label(score: int) -> str:
    if score >= 80: return "Generic Trap"
    if score >= 50: return "Templated"
    if score >= 25: return "Semi-Custom"
    return "Architect"

def _sameness_label(score: int) -> str:
    if score >= 70: return "Cliché Factory"
    if score >= 40: return "Cookie-Cutter"
    if score >= 20: return "Some Originality"
    return "Distinct Voice"

def _visual_label(similarity: int) -> str:
    if similarity >= 80: return "Clone Detected"
    if similarity >= 50: return "Similar Layout"
    if similarity >= 20: return "Some Overlap"
    return "Unique Visual"

def _build_revenue_teaser(readiness: int) -> dict:
    gap = 1.0 - (readiness / 100.0)
    return {
        "readiness_gap_percent": round(gap * 100, 1),
        "message": f"Your site is letting {round(gap*100)}% of potential revenue walk away.",
        "cta": "See exactly how much with the Revenue Exposure Calculator.",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
