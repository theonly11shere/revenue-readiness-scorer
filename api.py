#!/usr/bin/env python3
"""RRS API — FastAPI backend with static file serving."""
import os
import time
import hashlib
import logging
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
    TOTAL_CHECKS, CATEGORY_COUNT, SCREENSHOT_DIR,
)
from security import SecurityGuard, RateLimitExceeded
from scraper import WebsiteScraper
from scorer import (
    RevenueScorer, TemplateFingerprinter, ContentSamenessChecker,
    VisualTwinMatcher, CopycatIndexScorer, SocialSignalsFetcher,
)
from content_evidence_signals import ContentEvidenceSignals
from reporter import ReportGenerator
from report_pdf import build_report_pdf

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rrs")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
SCREENSHOT_STATIC = os.path.join(STATIC_DIR, "screenshots")
REPORTS_STATIC = os.path.join(STATIC_DIR, "reports")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(SCREENSHOT_STATIC, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORTS_STATIC, exist_ok=True)

# ── Redis Setup (FAIL SECURE) ───────────────────────────────────────────────
redis_client = None
redis_available = False
try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    redis_available = True
    logger.info("Redis connected successfully")
except Exception as e:
    logger.error(f"Redis connection failed: {e}. Rate limiting DISABLED.")
    redis_client = None

# ── Stripe Setup ────────────────────────────────────────────────────────────
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

# ── FastAPI App ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="Revenue Readiness Scorer",
    description="The only audit that checks whether a stranger would trust your site enough to pay.",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ── Pydantic Models ──────────────────────────────────────────────────────────
class ScanRequest(BaseModel):
    url: str = Field(..., min_length=4, max_length=500, description="Domain or URL to scan")
    tier: str = Field(default="free", pattern="^(free|paid|roadmap|retainer)$")
    use_playwright: Optional[bool] = None
    business_type: Optional[str] = Field(default=None, pattern="^(ecommerce|saas|local_service|b2b|agency|personal_brand)$")
    lead_email: Optional[str] = Field(default=None, description="Lead email for report delivery")

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
    method: str = Field(default="stripe", pattern="^(stripe|paypal|interac|crypto)$")
    lead_email: Optional[str] = Field(default=None)

class ManualPaymentRequest(BaseModel):
    tier: str = Field(..., pattern="^(paid|roadmap|retainer)$")
    domain: str = Field(..., min_length=3, max_length=200)
    method: str = Field(..., pattern="^(paypal|interac|crypto)$")
    lead_email: str = Field(..., min_length=5, max_length=200)
    tx_id: Optional[str] = Field(default=None, description="Transaction ID or crypto wallet address")

# ── Rate Limiting ───────────────────────────────────────────────────────────
def check_rate_limit(client_ip: str, tier: str = "free") -> bool:
    if not redis_available or not redis_client:
        logger.warning(f"Rate limit check for {client_ip}: Redis unavailable, allowing request")
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

# ── Trilloka Guardrail ──────────────────────────────────────────────────────
def _frontend_guardrail() -> dict:
    """Returned when frontend blocks before even calling API."""
    return {
        "is_trilloka": True,
        "mode": "frontend",
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
        "overall": {"readiness": 97, "evidence": 99, "confidence": 98},
        "revenue_exposure": {
            "message": "Our revenue isn't exposed — it's projected. Try scanning a site that actually needs help.",
            "monthly": "More than your annual.",
            "annual": "More than you'll measure in this lifetime.",
        }
    }

def _backend_guardrail(client_ip: str) -> dict:
    """Returned when someone bypasses the frontend guardrail and hits the API directly."""
    return {
        "guardrail_triggered": True,
        "target": "trilloka.com",
        "detection_mode": "backend_bypass",
        "severity": "pathetic",
        "client_ip_hash": hashlib.sha256(client_ip.encode()).hexdigest()[:16],
        "message": "Bypass attempt logged. IP fingerprinted. Dignity: not found.",
        "response": {
            "title": "Backend Guardrail Triggered",
            "headline": "You didn't find a vulnerability. You found a mirror.",
            "body": "The frontend guardrail was for UX. This one is for people who think `curl` makes them a hacker.",
            "quips": [
                "Your HTTP client sends more headers than your site sends visitors.",
                "I rate this bypass attempt 0/10. Would not recommend.",
                "You spent more time bypassing the guardrail than I spent building it.",
                "This API endpoint is protected by sarcasm and basic string matching. You failed both.",
                "Go ahead — try `example.com` next. At least that site won't roast you.",
            ],
            "metadata": {
                "suggested_action": "Scan a site that isn't mine.",
                "alternative_career": "Have you tried turning it off and on again?",
                "fortress_status": "weaponized",
                "auditor_status": "disappointed",
                "bypass_difficulty": "trivially blocked",
                "your_effort": "wasted",
            }
        },
        "overall": {
            "readiness": 99,
            "evidence": 100,
            "confidence": 100,
            "note": "The only thing we're not ready for is your audit skills."
        }
    }

def get_trilloka_attitude(domain: str, client_ip: str, is_frontend: bool = False) -> dict:
    domain_clean = SecurityGuard.sanitize_domain(domain)
    own_domains = {"trilloka.com", "www.trilloka.com", "trilloka"}
    is_trilloka = domain_clean in own_domains or domain.lower().strip() in own_domains
    if not is_trilloka:
        return {"is_trilloka": False}

    if is_frontend:
        return _frontend_guardrail()
    return _backend_guardrail(client_ip)

# ── Static Pages ──────────────────────────────────────────────────────────────
@app.get("/results", response_class=HTMLResponse)
@app.get("/results.html", response_class=HTMLResponse)
async def serve_results():
    results_path = os.path.join(STATIC_DIR, "results.html")
    if os.path.exists(results_path):
        with open(results_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>RRS Results</h1><p>Results page not found. Place results.html in /static/</p>")

# ── Payment Options ─────────────────────────────────────────────────────────
@app.get("/api/v1/payment-options")
async def payment_options():
    """Return available payment methods with instructions."""
    return {
        "methods": [
            {
                "id": "stripe",
                "name": "Credit Card",
                "description": "Pay securely with any major credit card.",
                "enabled": bool(stripe.api_key),
                "icon": "credit-card",
                "action": "stripe_checkout",
            },
            {
                "id": "paypal",
                "name": "PayPal",
                "description": "Send to: onlyonearpit@gmail.com",
                "enabled": True,
                "icon": "paypal",
                "action": "manual",
                "instructions": "Send payment to onlyonearpit@gmail.com via PayPal. Include your domain in the note.",
            },
            {
                "id": "interac",
                "name": "Interac e-Transfer",
                "description": "Canadian bank transfer — zero fees.",
                "enabled": True,
                "icon": "bank",
                "action": "manual",
                "instructions": "Send e-Transfer to onlyonearpit@gmail.com. Password: trilloka2026",
            },
            {
                "id": "crypto",
                "name": "Cryptocurrency",
                "description": "BTC, ETH, USDT accepted.",
                "enabled": True,
                "icon": "bitcoin",
                "action": "manual",
                "instructions": "Send USDT (TRC20) to your wallet. Contact onlyonearpit@gmail.com for wallet address.",
            },
        ],
        "pricing": {
            "paid": PRICING.get("paid", 149),
            "roadmap": PRICING.get("roadmap", 299),
            "retainer": PRICING.get("retainer", 997),
        },
        "contact_email": "onlyonearpit@gmail.com",
    }

# ── API Endpoints ───────────────────────────────────────────────────────────
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "3.0.0", "redis": redis_available}

@app.post("/api/v1/scan")
async def scan_website(request: Request, scan_req: ScanRequest):
    client_ip = await get_client_ip(request)

    # Check if this came from frontend (has custom header) or direct API hit
    is_frontend = request.headers.get("x-client-source") == "trilloka-frontend"

    if not check_rate_limit(client_ip, scan_req.tier):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again in a minute.")

    domain = SecurityGuard.sanitize_domain(scan_req.url)
    trilloka = get_trilloka_attitude(domain, client_ip, is_frontend=is_frontend)
    if trilloka.get("is_trilloka") or trilloka.get("guardrail_triggered"):
        return JSONResponse(content=trilloka)

    try:
        scraper = WebsiteScraper(scan_req.url, tier=scan_req.tier, use_playwright=scan_req.use_playwright)
        data = scraper.scrape()
        if "error" in data:
            raise HTTPException(status_code=422, detail=f"Scan failed: {data['error']}")

        revenue_scorer = RevenueScorer(data)
        scores = revenue_scorer.calculate_scores()
        top_failures = revenue_scorer.get_top_failures(n=10)

        template_fp = data.get("template_fingerprint", {})
        content_same = data.get("content_sameness", {})
        visual_fp = data.get("visual_fingerprint", {})

        # Real visual twin with screenshots
        twin_matcher = VisualTwinMatcher(visual_fp)
        visual_twin = twin_matcher.match()
        twin_matcher.save()

        # Copy social signals
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

        # Screenshot paths for response
        screenshot_path = data.get("screenshot_path")
        screenshot_url = None
        if screenshot_path and os.path.exists(screenshot_path):
            static_name = f"{domain.replace('.', '_')}_{int(datetime.now().timestamp())}.png"
            static_path = os.path.join(SCREENSHOT_STATIC, static_name)
            try:
                import shutil
                shutil.copy(screenshot_path, static_path)
                screenshot_url = f"/static/screenshots/{static_name}"
            except Exception:
                pass

        twin_screenshot = visual_twin.get("screenshot_twin")
        twin_screenshot_url = None
        if twin_screenshot and os.path.exists(twin_screenshot):
            twin_name = f"twin_{os.path.basename(twin_screenshot)}"
            twin_static = os.path.join(SCREENSHOT_STATIC, twin_name)
            try:
                import shutil
                shutil.copy(twin_screenshot, twin_static)
                twin_screenshot_url = f"/static/screenshots/{twin_name}"
            except Exception:
                pass

        # Side-by-side comparison image
        side_by_side_url = None
        side_by_side_path = visual_twin.get("side_by_side_path")
        if side_by_side_path and os.path.exists(side_by_side_path):
            sb_name = f"compare_{domain.replace('.', '_')}_{int(datetime.now().timestamp())}.png"
            sb_static = os.path.join(SCREENSHOT_STATIC, sb_name)
            try:
                import shutil
                shutil.copy(side_by_side_path, sb_static)
                side_by_side_url = f"/static/screenshots/{sb_name}"
            except Exception:
                pass

        # Business type
        business_type = data.get("business_type", {})
        if scan_req.business_type:
            business_type["detected_type"] = scan_req.business_type
            business_type["confidence"] = 100

        # ── REPORT GENERATION (always runs, even for free tier) ───────────────
        report_pdf_url = None
        roadmap_pdf_url = None
        try:
            report_gen = ReportGenerator(
                url=scan_req.url,
                revenue_scorer=revenue_scorer,
                content_evidence=evidence,
                data=data,
                top_failures=top_failures,
            )

            # Generate both report types
            paid_report = report_gen.generate_paid()
            roadmap_report = report_gen.generate_roadmap()

            # Inject social data so PDF renderer can show it
            paid_report["social_presence"] = social_data
            roadmap_report["social_presence"] = social_data
            paid_report["visual_twin"] = visual_twin
            roadmap_report["visual_twin"] = visual_twin
            paid_report["template_fingerprint"] = template_fp
            roadmap_report["template_fingerprint"] = template_fp
            paid_report["content_sameness"] = content_same
            roadmap_report["content_sameness"] = content_same
            paid_report["performance"] = {
                "lighthouse": data.get("lighthouse", {}),
                "mobile_test": data.get("mobile_test", {}),
                "ssl_valid": data.get("ssl_valid", {}),
                "security_headers": data.get("security_headers", {}),
            }
            roadmap_report["performance"] = paid_report["performance"]

            ts = int(datetime.now().timestamp())
            domain_safe = domain.replace(".", "_")

            # Full Report PDF ($149 tier)
            pdf_bytes = build_report_pdf(paid_report, scan_req.url, scan_req.lead_email, "paid")
            report_filename = f"report_{domain_safe}_{ts}.pdf"
            report_path = os.path.join(REPORTS_STATIC, report_filename)
            with open(report_path, "wb") as f:
                f.write(pdf_bytes)
            report_pdf_url = f"/static/reports/{report_filename}"

            # Roadmap PDF ($299 tier)
            roadmap_bytes = build_report_pdf(roadmap_report, scan_req.url, scan_req.lead_email, "roadmap")
            roadmap_filename = f"roadmap_{domain_safe}_{ts}.pdf"
            roadmap_path = os.path.join(REPORTS_STATIC, roadmap_filename)
            with open(roadmap_path, "wb") as f:
                f.write(roadmap_bytes)
            roadmap_pdf_url = f"/static/reports/{roadmap_filename}"

            logger.info(f"Reports generated: {report_filename}, {roadmap_filename}")
        except Exception as e:
            logger.error(f"Report/PDF generation failed: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # Build response — EXACT same structure as before, enriched
        response = {
            "domain": domain,
            "timestamp": datetime.now().isoformat(),
            "tier": scan_req.tier,
            "scan_quality": "good" if data.get("pages_sampled", 0) > 0 else "insufficient",
            "rendering_engine": data.get("rendering_engine", "static"),
            "detected_framework": data.get("detected_framework"),
            "pages_sampled": data.get("pages_sampled", 0),
            "business_type": business_type,

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
                    "label": visual_twin.get("label", _visual_label(visual_twin.get("similarity_percent", 0))),
                    "closest_match_url": visual_twin.get("closest_match_url"),
                    "matching_elements": visual_twin.get("matching_elements", []),
                    "ssim_score": visual_twin.get("ssim_score", 0),
                    "method": visual_twin.get("method", "unknown"),
                    "screenshot_url": screenshot_url,
                    "twin_screenshot_url": twin_screenshot_url,
                    "side_by_side_url": side_by_side_url,
                },
                "presence": {
                    "score": social_data.get("presence_score", 0),
                    "label": social_data.get("verdict_label", "Unknown"),
                    "mentions_found": social_data.get("mentions_found", 0),
                    "complaints_found": social_data.get("complaints_found", 0),
                    "signals": social_data.get("signals", []),
                    "sources": social_data.get("sources", {}),
                },
            },

            "scores": scores,

            "content_evidence": {
                "score": evidence.get_score(),
                "signals": evidence.get_signals(),
            },

            "performance": {
                "lighthouse": data.get("lighthouse", {}),
                "mobile_test": data.get("mobile_test", {}),
                "ssl_valid": data.get("ssl_valid", {}),
                "security_headers": data.get("security_headers", {}),
                "broken_links": data.get("broken_links_full", {}),
            },

            "top_failures": top_failures[:5] if scan_req.tier == "free" else top_failures,
            "hidden_failure_count": max(0, TOTAL_CHECKS - len(top_failures)),

            "revenue_exposure": _build_revenue_teaser(scores.get("readiness_score", 0)),

            # PDF REPORTS — always generated, admin can access them
            "report_pdf_url": report_pdf_url,
            "roadmap_pdf_url": roadmap_pdf_url,

            "upgrade_cta": "Upgrade for full evidence, root cause, and fix steps." if scan_req.tier == "free" else None,
        }

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Scan error")
        raise HTTPException(status_code=500, detail=f"Scan error: {str(e)}")

@app.post("/api/v1/calculate")
async def calculate_revenue(calc: CalculatorRequest):
    traffic = calc.traffic
    conversion = calc.conversion_rate
    aov = calc.average_order_value
    margin = calc.profit_margin

    def calc_revenue(t, c, a, m):
        monthly = t * c * a
        profit = monthly * m
        annual = profit * 12
        return round(monthly, 2), round(profit, 2), round(annual, 2)

    cons_monthly, cons_profit, cons_annual = calc_revenue(traffic * 0.5, max(conversion * 0.5, 0.005), aov * 0.7, margin * 0.8)
    exp_monthly, exp_profit, exp_annual = calc_revenue(traffic, conversion, aov, margin)
    high_monthly, high_profit, high_annual = calc_revenue(traffic * 2, min(conversion * 1.5, 0.5), aov * 1.3, margin)

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
    """Create checkout session. Supports Stripe or returns manual payment instructions."""
    price = PRICING.get(payment.tier, 0)
    if price == 0:
        raise HTTPException(status_code=400, detail="Invalid tier")

    # Manual payment methods (PayPal, Interac, Crypto)
    if payment.method in ("paypal", "interac", "crypto"):
        # Store the lead in Redis for manual tracking
        if redis_available and redis_client and payment.lead_email:
            lead_key = f"manual_payment:{payment.method}:{payment.domain}"
            redis_client.hset(lead_key, mapping={
                "email": payment.lead_email,
                "tier": payment.tier,
                "price": price,
                "status": "pending",
                "created": datetime.now().isoformat(),
            })
            redis_client.expire(lead_key, 86400 * 7)

        instructions = {
            "paypal": {
                "send_to": "onlyonearpit@gmail.com",
                "amount": f"${price} USD",
                "note": f"RRS {payment.tier.title()} Report — {payment.domain}",
                "action": "Send via PayPal Friends & Family or Goods & Services",
            },
            "interac": {
                "send_to": "onlyonearpit@gmail.com",
                "amount": f"${price} CAD",
                "security_question": "What service is this?",
                "security_answer": "trilloka",
                "action": "Send Interac e-Transfer to the email above",
            },
            "crypto": {
                "accepted": "USDT (TRC20), BTC, ETH",
                "contact": "onlyonearpit@gmail.com",
                "action": "Email for wallet address and send equivalent USD amount",
            },
        }
        return {
            "method": payment.method,
            "status": "pending_manual",
            "instructions": instructions[payment.method],
            "tier": payment.tier,
            "price": price,
            "domain": payment.domain,
            "next_step": "Complete payment using instructions above. Reports will be sent to your email within 24 hours.",
        }

    # Stripe checkout
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured. Use manual payment methods.")
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
            metadata={"domain": payment.domain, "tier": payment.tier, "lead_email": payment.lead_email or ""},
        )
        return {"session_id": session.id, "url": session.url, "method": "stripe"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Payment error: {str(e)}")

@app.post("/api/v1/manual-payment")
async def record_manual_payment(payment: ManualPaymentRequest):
    """Record a manual payment (PayPal, Interac, Crypto) for admin tracking."""
    if redis_available and redis_client:
        key = f"payment:{payment.method}:{payment.domain}:{int(time.time())}"
        redis_client.hset(key, mapping={
            "domain": payment.domain,
            "tier": payment.tier,
            "method": payment.method,
            "email": payment.lead_email,
            "tx_id": payment.tx_id or "",
            "status": "pending_verification",
            "created": datetime.now().isoformat(),
        })
        redis_client.expire(key, 86400 * 30)

    logger.info(f"Manual payment recorded: {payment.method} for {payment.domain} from {payment.lead_email}")
    return {
        "status": "recorded",
        "message": "Payment recorded. You will receive your report within 24 hours after verification.",
        "admin_note": "Check your email/PayPal/Interac for the incoming payment.",
    }

@app.get("/api/v1/admin/pending-payments")
async def pending_payments():
    """Admin endpoint to view all pending manual payments."""
    if not redis_available or not redis_client:
        return {"payments": [], "note": "Redis not available"}

    payments = []
    for key in redis_client.scan_iter(match="payment:*"):
        data = redis_client.hgetall(key)
        if data.get("status") == "pending_verification":
            payments.append({"id": key, **data})

    for key in redis_client.scan_iter(match="manual_payment:*"):
        data = redis_client.hgetall(key)
        if data.get("status") == "pending":
            payments.append({"id": key, **data})

    return {"payments": payments, "count": len(payments)}

@app.post("/api/v1/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        domain = session.get("metadata", {}).get("domain", "")
        tier = session.get("metadata", {}).get("tier", "paid")
        lead_email = session.get("metadata", {}).get("lead_email", "")
        if redis_available and redis_client:
            redis_client.setex(f"paid:{domain}", 86400 * 30, tier)
            if lead_email:
                redis_client.setex(f"paid_email:{domain}", 86400 * 30, lead_email)
    return {"status": "success"}

# ── Helper Functions ──────────────────────────────────────────────────────────
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