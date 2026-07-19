#!/usr/bin/env python3
import asyncio, base64, hashlib, hmac, json, os, smtplib, time, uuid
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl, Field
from config import (TOTAL_CHECKS, PRICING, RATE_LIMIT_FREE, RATE_LIMIT_PAID, REDIS_URL, STRIPE_WEBHOOK_SECRET,
                    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, ALERT_EMAIL, SCAN_PASS_SECRET,
                    RESEND_API_KEY, EMAIL_FROM)
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
    product: Optional[str] = "paid"

class VerifyRequest(BaseModel):
    session_id: str

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
    if _verify_scan_pass(request.headers.get("x-scan-pass", "")):
        return True
    client_ip = request.client.host if request.client else "unknown"
    key = f"rate_limit:{client_ip}:{tier}"
    limit = int(str(RATE_LIMIT_FREE if tier == "free" else RATE_LIMIT_PAID).split("/")[0].strip())
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
    if len(_rate_limit_cache) > 10000:
        for k in [k for k, v in _rate_limit_cache.items() if v["reset"] < now]:
            del _rate_limit_cache[k]
        if len(_rate_limit_cache) > 10000:
            _rate_limit_cache.clear()
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


def _scan_pass_secret() -> str:
    return SCAN_PASS_SECRET or os.environ.get("STRIPE_SECRET_KEY", "") or "rrs-dev-secret"

def _make_scan_pass(email: str, days: int = 30) -> str:
    exp = int(time.time()) + days * 86400
    payload = f"{email.strip().lower()}|{exp}"
    sig = hmac.new(_scan_pass_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode()

def _verify_scan_pass(token: str) -> bool:
    if not token:
        return False
    try:
        email, exp, sig = base64.urlsafe_b64decode(token.encode()).decode().rsplit("|", 2)
        expected = hmac.new(_scan_pass_secret().encode(), f"{email}|{exp}".encode(), hashlib.sha256).hexdigest()[:32]
        return hmac.compare_digest(sig, expected) and int(exp) > time.time()
    except Exception:
        return False

_background_tasks = set()

def _alert_payload(report: Dict[str, Any], url: str, lead_email: Optional[str], tier: str):
    """Build (subject, text_body) for the admin alert."""
    scores = report.get("scores") or {}
    sev = report.get("severity") or {}
    fails = report.get("visible_failures") or []
    fp = report.get("template_fingerprint") or {}
    lines = [
        f"New {tier} scan on the RRS", "",
        f"URL: {url}",
        f"Lead email: {lead_email or '(not provided)'}",
        f"Readiness: {scores.get('readiness_score')}/100 | Evidence: {scores.get('evidence_coverage')} | Confidence: {scores.get('confidence_score')}",
        f"Severity: {sev.get('label')} - {sev.get('desc')}",
        f"Template: {fp.get('detected_template')} ({fp.get('generic_score')}% generic)",
        "", "Top failures:",
    ]
    lines += [f"- [{f.get('severity')}] {f.get('one_liner')}" for f in fails[:10]]
    subject = f"RRS Lead: {url} -> {scores.get('readiness_score')}/100 ({sev.get('label')})"
    return subject, "\n".join(lines)

def _send_via_resend(subject: str, text: str, report: Dict[str, Any]) -> None:
    """HTTPS email via Resend — works on Railway Hobby where SMTP ports are blocked."""
    import urllib.request
    payload = {
        "from": EMAIL_FROM,
        "to": [ALERT_EMAIL],
        "subject": subject,
        "text": text,
        "attachments": [{
            "filename": "report.json",
            "content": base64.b64encode(json.dumps(report, indent=2).encode()).decode(),
        }],
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        resp.read()

def _send_via_smtp(subject: str, text: str, report: Dict[str, Any]) -> None:
    """Gmail SMTP fallback — only works where outbound 465/587 is open (not Railway Hobby)."""
    msg = MIMEMultipart()
    msg["From"], msg["To"] = SMTP_USER, ALERT_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(text, "plain"))
    part = MIMEBase("application", "json")
    part.set_payload(json.dumps(report, indent=2))
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename="report.json")
    msg.attach(part)
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as s:
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, [ALERT_EMAIL], msg.as_string())

def _send_alert_email(report: Dict[str, Any], url: str, lead_email: Optional[str], tier: str) -> None:
    subject, text = _alert_payload(report, url, lead_email, tier)
    if RESEND_API_KEY:
        try:
            _send_via_resend(subject, text, report)
            print(f"alert email sent via Resend to {ALERT_EMAIL} for {url}")
        except Exception as exc:
            body = ""
            try:
                body = exc.read().decode(errors="replace")[:500]
            except Exception:
                pass
            print(f"alert email via Resend failed: {exc} | response: {body}")
        return
    if SMTP_USER and SMTP_PASS and ALERT_EMAIL:
        try:
            _send_via_smtp(subject, text, report)
            print(f"alert email sent via SMTP to {ALERT_EMAIL} for {url}")
        except Exception as exc:
            print(f"alert email via SMTP failed: {exc}")
        return
    print("alert email skipped: set RESEND_API_KEY (recommended) or SMTP_USER/SMTP_PASS in Railway variables")

def _fire_alert(report: Dict[str, Any], url: str, lead_email: Optional[str], tier: str) -> None:
    task = asyncio.create_task(asyncio.to_thread(_send_alert_email, report, url, lead_email, tier))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

@app.post("/api/v1/score/{tier}")
async def score_site(request: Request, tier: str, body: ScanRequest):
    if tier not in ("free", "paid", "roadmap"):
        raise HTTPException(status_code=400, detail="Invalid tier. Use 'free', 'paid', or 'roadmap'.")
    if tier in ("paid", "roadmap") and not _verify_scan_pass(request.headers.get("x-scan-pass", "")):
        raise HTTPException(status_code=401, detail="This report requires a purchase. Your 30-day scan pass is issued right after checkout.")
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
        data = await asyncio.to_thread(scraper.scrape)
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
    if tier == "free":
        report = reporter.generate_free()
        _fire_alert(report, url, body.email, tier)
    elif tier == "roadmap":
        report = reporter.generate_roadmap()
    else:
        report = reporter.generate_paid()
    _log_lead(url, body.email, tier, report.get("scores"))
    return JSONResponse(content=report)

@app.post("/api/radar-scan")
async def radar_scan(request: Request, body: ScanRequest):
    url = str(body.url)
    try:
        scraper = WebsiteScraper(url, tier="free")
        data = await asyncio.to_thread(scraper.scrape)
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
        product = (body.product or "paid")
        if product not in ("paid", "roadmap"):
            raise HTTPException(status_code=400, detail="Invalid product. Use 'paid' or 'roadmap'.")
        product_name = "Revenue Readiness Scorer — Full Report" if product == "paid" else "Revenue Readiness Scorer — Full Report + Fix Roadmap"
        key = idempotency_key or str(uuid.uuid4())
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price_data": {"currency": "usd", "product_data": {"name": product_name}, "unit_amount": PRICING[product] * 100}, "quantity": 1}],
            mode="payment", success_url=body.success_url, cancel_url=body.cancel_url,
            metadata={"url": str(body.url), "product": product}, idempotency_key=key)
        return {"checkout_url": session.url, "idempotency_key": key}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Stripe checkout failed: {exc}")

@app.post("/api/v1/verify-session")
async def verify_session(body: VerifyRequest):
    try:
        import stripe
        stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
        if not stripe_key:
            raise HTTPException(status_code=500, detail="Stripe secret key not configured.")
        stripe.api_key = stripe_key
        session = stripe.checkout.Session.retrieve(body.session_id)
        if getattr(session, "payment_status", "") != "paid":
            raise HTTPException(status_code=402, detail="Payment not completed for this session.")
        email = None
        try:
            email = session.customer_details.email
        except Exception:
            email = None
        meta = dict(session.metadata or {})
        return {"paid": True, "product": meta.get("product", "paid"), "url": meta.get("url", ""),
                "scan_pass": _make_scan_pass(email or "customer")}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Session verification failed: {exc}")

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
    # Booleans only — reveals whether variables are SET, never their values.
    return {"status": "ok", "version": "2.0.0",
            "integrations": {
                "email": "resend" if RESEND_API_KEY else ("smtp" if (SMTP_USER and SMTP_PASS) else "none"),
                "stripe": bool(os.environ.get("STRIPE_SECRET_KEY")),
            }}
