# Revenue Readiness Scorer

A rule-based website analysis tool that scores trustworthiness, revenue potential, and Google AI-era penalty risk.

## Features

- **40 checkpoints** across 5 categories (Trust, Conversion, SEO, Content, Technical)
- **Two scores**: Revenue Readiness Score + Google AI Scorer
- **Future predictions**: 3, 6, 12 month traffic loss projections
- **3 report types**: Free (lead gen), Paid ($149), Admin (locked)
- **No AI/ML/LLM**: Pure rule-based logic

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Free report (generates admin alert automatically)
python main.py https://example.com --type free --admin-output alert.json

# Paid report
python main.py https://example.com --type paid --output paid.json

# Admin report (locked)
python main.py https://example.com --type admin
```

## Business Model

| Tier | Price | What Customer Gets | What You Get |
|------|-------|-------------------|--------------|
| Free | $0 | Score + 2 failures + AI scorer + future | Lead + admin alert |
| Paid | $149 | Full 40-check report + methods + action plan | $149 + admin sources |
| Retainer | $997/mo | Implementation + monthly re-score | Recurring revenue |

## License

Private. Not for redistribution.
