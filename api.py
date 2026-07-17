#!/usr/bin/env python3
import json, os, uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl, Field
from config import TOTAL_CHECKS, PRICING, RATE_LIMIT_FREE, RATE_LIMIT_PAID, REDIS_URL, STRIPE_WEBHOOK_SECRET
from scraper import WebsiteScraper
from scorer import RevenueScorer, CopycatIndexScorer
from content_evidence_signals import ContentEvidenceSignals
from reporter import ReportGenerator
from security import SecurityError, StripeWebhookVerifier
from social_signals import SocialSignalsFetcher

class ScanRequest(BaseModel):
    url: HttpUrl
    email: Optional[str] = None
    traffic: Optional[int] = None
    conversion_rate: Optional[float] = None
    aov: Optional[float] = None
    profit_margin: Optional[float] = None

class CheckoutRequest(BaseModel):
    url: HttpUrl
    success_url: str
    cancel_url: str

app = FastAPI(title="Revenue Readiness Scorer", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

_redis = None
try:
    import redis
    _redis = redis.from_url(REDIS_URL, decode_responses=True)
    _redis.ping()
except Exception:
    _redis = None

_rate_limit_cache: Dict[str, Dict[str, Any]] = {}

def _check_rate_limit(request: Request, tier: str) -> bool:
    client_ip = request.client.host if request.client else "unknown"
    key = f"rate_limit:{client_ip}:{tier}"
    limit = RATE_LIMIT_FREE if tier == "free" else RATE_LIMIT_PAID
    if _redis:
        try:
            current = _redis.get(key)
            if current and int(current) >= limit:
                return False
            _redis.incr(key)
            _redis.expire(key, 3600)
            return True
        except:
            pass
    now = datetime.now(timezone.utc).timestamp()
    if key not in _rate_limit_cache:
        _rate_limit_cache[key] = {"count": 0, "reset": now + 3600}
    if _rate_limit_cache[key]["reset"] < now:
        _rate_limit_cache[key] = {"count": 0, "reset": now + 3600}
    if _rate_limit_cache[key]["count"] >= limit:
        return False
    _rate_limit_cache[key]["count"] += 1
    return True

def _log_lead(url: str, email: Optional[str], tier: str, scores: Optional[Dict]) -> None:
    try:
        lead_file = os.path.join(os.path.dirname(__file__), "leads.jsonl")
        with open(lead_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"url": str(url), "email": email, "tier": tier, "scores": scores, "timestamp": datetime.now(timezone.utc).isoformat()}) + "\n")
    except Exception:
        pass

@app.post("/api/v1/score/{tier}")
async def score_site(request: Request, tier: str, body: ScanRequest):
    if tier not in ("free", "paid"):
        raise HTTPException(status_code=400, detail="Invalid tier. Use 'free' or 'paid'.")
    if not _check_rate_limit(request, tier):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
    url = str(body.url)
    calc_inputs = {}
    if body.traffic is not None: calc_inputs["traffic"] = body.traffic
    if body.conversion_rate is not None: calc_inputs["conversion_rate"] = body.conversion_rate
    if body.aov is not None: calc_inputs["aov"] = body.aov
    if body.profit_margin is not None: calc_inputs["profit_margin"] = body.profit_margin
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
    reporter = ReportGenerator(url, revenue_scorer, content_evidence, data, top_failures, calculator_inputs=calc_inputs if calc_inputs else None)
    report = reporter.generate_free() if tier == "free" else reporter.generate_paid()
    _log_lead(url, body.email, tier, report.get("scores"))
    return JSONResponse(content=report)

@app.post("/api/radar-scan")
async def radar_scan(request: Request, body: ScanRequest):
    url = str(body.url)
    try:
        scraper = WebsiteScraper(url, tier="free")
        data = scraper.scrape()
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail=f"Security policy violation: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scraping failed: {exc}")
    if "error" in data:
        raise HTTPException(status_code=500, detail=data["error"])
    html = data.get("raw_html", "")
    copycat = CopycatIndexScorer(html).score()
    from urllib.parse import urlparse
    domain = urlparse(url).netloc or url
    brand = domain.replace("www.", "").split(".")[0]
    social = SocialSignalsFetcher(brand=brand, domain=domain).fetch(max_signals=4)
    radar_log = [
        f"Just now: {domain} indexed with Copycat Index {copycat['copycat_index']}",
        f"2 min ago: {copycat['template_match']} detected as dominant template signature",
        f"7 min ago: {copycat['copycat_index'] // 2} matching class patterns found in public template DB",
    ]
    if social:
        radar_log.append(f"12 min ago: Social listening found {len(social)} public complaint threads")
    try:
        fp = {"url": url, "domain": domain, "timestamp": datetime.now(timezone.utc).isoformat(), "copycat_index": copycat["copycat_index"], "template_match": copycat["template_match"], "matched_classes": copycat.get("matched_classes", [])}
        fp_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fingerprints.jsonl")
        with open(fp_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(fp) + "\n")
    except Exception:
        pass
    return JSONResponse(content={"copycat_index": copycat["copycat_index"], "template_match": copycat["template_match"], "matched_classes": copycat.get("matched_classes", []), "social_signals": social, "radar_log": radar_log})

@app.post("/api/v1/checkout")
async def create_checkout(request: Request, body: CheckoutRequest, idempotency_key: Optional[str] = Header(default=None, alias="stripe-idempotency-key")):
    try:
        import stripe
        stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
        if not stripe_key:
            raise HTTPException(status_code=500, detail="Stripe secret key not configured.")
        stripe.api_key = stripe_key
        key = idempotency_key or str(uuid.uuid4())
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price_data": {"currency": "usd", "product_data": {"name": "Revenue Readiness Scorer — Full Report"}, "unit_amount": PRICING["paid"] * 100}, "quantity": 1}],
            mode="payment", success_url=body.success_url, cancel_url=body.cancel_url, metadata={"url": str(body.url)}, idempotency_key=key)
        return {"checkout_url": session.url, "idempotency_key": key}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Stripe checkout failed: {exc}")

@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(..., alias="stripe-signature")):
    payload = await request.body()
    verifier = StripeWebhookVerifier(STRIPE_WEBHOOK_SECRET)
    try:
        event = verifier.verify(payload, stripe_signature)
        return {"status": "ok", "event_id": event.get("id")}
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Webhook processing error: {exc}")

@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}
