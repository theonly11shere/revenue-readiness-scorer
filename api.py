"""
FastAPI layer for the Revenue Readiness Scorer.
Provides /api/v1/score endpoints, Stripe checkout + webhooks,
Redis-backed rate limiting, and Pydantic input validation.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl, Field

from config import (
    TOTAL_CHECKS,
    PRICING,
    TIER_NAMES,
    RATE_LIMIT_FREE,
    RATE_LIMIT_PAID,
    REDIS_URL,
    STRIPE_WEBHOOK_SECRET,
)
from scraper import WebsiteScraper
from scorer import RevenueScorer
from content_evidence_signals import ContentEvidenceSignals
from reporter import ReportGenerator
from security import SecurityError, StripeWebhookVerifier

# ── Pydantic models ─────────────────────────────────────────────────────────────
class ScanRequest(BaseModel):
    url: HttpUrl
    email: Optional[str] = Field(default=None)
    tier: str = Field(default="free", pattern=r"^(free|paid)$")
    traffic: Optional[int] = Field(default=None, ge=0)
    conversion_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    aov: Optional[float] = Field(default=None, ge=0.0)
    profit_margin: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class CheckoutRequest(BaseModel):
    url: HttpUrl
    success_url: str
    cancel_url: str


# ── Redis / rate limiting (best-effort) ─────────────────────────────────────────
def _get_redis():
    try:
        import redis  # type: ignore
        r = redis.from_url(REDIS_URL, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


_redis = _get_redis()


_LEADS_FILE = os.environ.get("RRS_LEADS_FILE", "leads.jsonl")


def _log_lead(url: str, email: Optional[str], tier: str, scores: Optional[Dict[str, Any]] = None):
    """Append scan lead to a local JSONL file for the mailing list."""
    if not email:
        return
    try:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url": url,
            "email": email,
            "tier": tier,
            "scores": scores or {},
        }
        with open(_LEADS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        # Lead logging is best-effort; don't break the API if the file can't be written.
        pass


def _rate_limit_key(request: Request, tier: str) -> str:
    client_ip = request.client.host if request.client else "unknown"
    return f"rrs:ratelimit:{tier}:{client_ip}"


def _check_rate_limit(request: Request, tier: str) -> bool:
    if _redis is None:
        return True  # degrade gracefully if Redis down
    key = _rate_limit_key(request, tier)
    limit = int(RATE_LIMIT_FREE.split("/")[0]) if tier == "free" else int(RATE_LIMIT_PAID.split("/")[0])
    window = 60
    current = _redis.get(key)
    if current and int(current) >= limit:
        return False
    pipe = _redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, window)
    pipe.execute()
    return True


# ── FastAPI app ─────────────────────────────────────────────────────────────────
app = FastAPI(title="Revenue Readiness Scorer API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/v1/score/{tier}")
async def score_site(
    request: Request,
    tier: str,
    body: ScanRequest,
):
    if tier not in ("free", "paid"):
        raise HTTPException(status_code=400, detail="Invalid tier. Use 'free' or 'paid'.")

    if not _check_rate_limit(request, tier):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    url = str(body.url)
    calc_inputs = {}
    if body.traffic is not None:
        calc_inputs["traffic"] = body.traffic
    if body.conversion_rate is not None:
        calc_inputs["conversion_rate"] = body.conversion_rate
    if body.aov is not None:
        calc_inputs["aov"] = body.aov
    if body.profit_margin is not None:
        calc_inputs["profit_margin"] = body.profit_margin

    try:
        scraper = WebsiteScraper(url, tier=tier)
        data = scraper.scrape()
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail=f"Security policy violation: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scraping failed: {exc}")

    if "error" in data:
        err_msg = str(data["error"]).lower()
        if any(word in err_msg for word in ("timeout", "connection", "resolve", "refused")):
            raise HTTPException(status_code=400, detail=f"Could not reach the URL: {data['error']}")
        raise HTTPException(status_code=500, detail=data["error"])

    revenue_scorer = RevenueScorer(data)
    revenue_scorer.calculate_scores()

    content_evidence = ContentEvidenceSignals(data)
    content_evidence.analyze()

    top_failures = revenue_scorer.get_top_failures(TOTAL_CHECKS)
    reporter = ReportGenerator(
        url,
        revenue_scorer,
        content_evidence,
        data,
        top_failures,
        calculator_inputs=calc_inputs if calc_inputs else None,
    )

    if tier == "free":
        report = reporter.generate_free()
    else:
        report = reporter.generate_paid()

    _log_lead(url, body.email, tier, report.get("scores"))

    return JSONResponse(content=report)


@app.post("/api/v1/checkout")
async def create_checkout(
    request: Request,
    body: CheckoutRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="stripe-idempotency-key"),
):
    """Create a Stripe Checkout Session for the paid report."""
    try:
        import stripe  # type: ignore
        stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
        if not stripe_key:
            raise HTTPException(status_code=500, detail="Stripe secret key not configured.")
        stripe.api_key = stripe_key

        key = idempotency_key or str(uuid.uuid4())
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Revenue Readiness Scorer — Full Report"},
                    "unit_amount": PRICING["paid"] * 100,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=body.success_url,
            cancel_url=body.cancel_url,
            metadata={"url": str(body.url)},
            idempotency_key=key,
        )
        return {"checkout_url": session.url, "idempotency_key": key}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Stripe checkout failed: {exc}")


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(..., alias="stripe-signature")):
    """Receive and verify Stripe webhook events."""
    payload = await request.body()
    verifier = StripeWebhookVerifier(STRIPE_WEBHOOK_SECRET)
    try:
        event = verifier.verify(payload, stripe_signature)
        # TODO: handle event["type"] (e.g. payment_intent.succeeded)
        return {"status": "ok", "event_id": event.get("id")}
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Webhook processing error: {exc}")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}
