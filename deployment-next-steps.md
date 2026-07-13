# Next Steps: Deploy & Paste the URL on the Website

This is the remaining roadmap to make the Revenue Readiness Scorer a public, usable website.

## Step 1 — Deploy the API

Pick a host and deploy the Python API.

### Option A — Render (recommended for beginners)
1. Push the project to GitHub.
2. Go to [render.com](https://render.com) and create a new **Web Service**.
3. Connect your GitHub repo.
4. Set:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python start.py`
5. Add environment variables (see Step 2).
6. Render gives you a URL like `https://your-service.onrender.com`.

### Option B — Railway
1. Push the project to GitHub.
2. Go to [railway.app](https://railway.app) and deploy the repo.
3. Add environment variables.
4. Railway gives you a public URL.

### Option C — Fly.io
1. Install Fly CLI: `winget install Fly-io.flyctl`
2. Run `fly launch` in the project folder.
3. Add environment variables with `fly secrets set`.

## Step 2 — Set Required Environment Variables

Add these in your hosting dashboard:

```text
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
RRS_LEADS_FILE=leads.jsonl
REDIS_URL=redis://...        # optional, only for rate limiting
PORT=8000                    # most hosts set this automatically
```

To get Stripe keys:
1. Go to [stripe.com](https://stripe.com).
2. Copy your **Secret key** from Developers → API keys.
3. Create a webhook endpoint pointing to `https://your-api.com/webhooks/stripe`.
4. Copy the **Signing secret**.

## Step 3 — Update frontend.html with the Live API URL

Open `frontend.html` and change line 97:

```javascript
const API_URL = 'http://127.0.0.1:8000/api/v1/score/free';
```

to your deployed URL:

```javascript
const API_URL = 'https://your-service.onrender.com/api/v1/score/free';
```

## Step 4 — Build the Pricing / Checkout Flow

The frontend currently links to `/pricing`, which does not exist.

### Simplest version
1. Create `pricing.html` in the same folder.
2. Add a "Buy Full Report — $149" button.
3. That button calls your API:
   ```javascript
   const res = await fetch('https://your-service.onrender.com/api/v1/checkout', {
     method: 'POST',
     headers: { 'Content-Type': 'application/json' },
     body: JSON.stringify({
       url: scannedUrl,
       success_url: 'https://your-domain.com/success.html',
       cancel_url: 'https://your-domain.com/cancel.html'
     })
   });
   const data = await res.json();
   window.location.href = data.checkout_url;
   ```

## Step 5 — Deliver the Paid Report

After payment, choose one:

- **Email delivery:** collect email during checkout, then send the paid report via email.
- **Success page:** redirect to `success.html` and call a secure endpoint to fetch the paid report.
- **Download link:** generate a PDF and give a temporary download URL.

## Step 6 — Add Required Pages

Stripe requires:
- **Privacy Policy** (`privacy.html`)
- **Terms of Service** (`terms.html`)

Also recommended:
- **About / How it works**
- **Contact / Support**

## Step 7 — Harden for Production

In `api.py`:
- Replace `allow_origins=["*"]` with your actual domain.
- Ensure Redis is running if you want rate limiting.
- Remove or protect the `/webhooks/stripe` endpoint properly.

## Quick Summary

| Task | Status |
|------|--------|
| Local API working | Done |
| Frontend email capture | Done |
| Lead logging to `leads.jsonl` | Done |
| Deploy API | Next |
| Update frontend API URL | After deploy |
| Stripe checkout | Next |
| Paid report delivery | Next |
| Privacy / Terms | Next |
| Production hardening | Next |
