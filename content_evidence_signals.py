"""
Content Evidence Signals — replaces the old Google AI Scorer.
Analyzes E-E-A-T and content-quality signals instead of flagging "AI content."
Returns pass/fail/partial status per signal with descriptive text.
"""

import re
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin, urlparse

from config import CONTENT_EVIDENCE_CHECKS


class ContentEvidenceSignals:
    def __init__(self, scraped_data: Dict[str, Any]):
        self.data = scraped_data
        self.signals: List[Dict[str, Any]] = []

    def analyze(self) -> Dict[str, Any]:
        """Run all evidence checks and return a structured report."""
        self.signals = []
        self._check_author_byline()
        self._check_original_images()
        self._check_firsthand_experience()
        self._check_source_citations()
        self._check_publication_dates()
        self._check_organization_info()
        self._check_templated_passages()
        self._check_faq_structured_data()

        pass_count = sum(1 for s in self.signals if s["status"] == "pass")
        fail_count = sum(1 for s in self.signals if s["status"] == "fail")
        partial_count = sum(1 for s in self.signals if s["status"] == "partial")

        return {
            "signals": self.signals,
            "summary": self._build_summary(pass_count, fail_count, partial_count),
            "pass_count": pass_count,
            "fail_count": fail_count,
            "partial_count": partial_count,
        }

    # ── Individual signal checks ────────────────────────────────────────────────

    def _check_author_byline(self) -> None:
        pages = self.data.get("pages", [])
        found_author = False
        detail = []
        for page in pages:
            soup_text = page.get("_soup_text", "")
            # Look for author meta or byline classes
            if re.search(r"author|byline|written by|posted by", soup_text, re.I):
                found_author = True
                detail.append(f"Author mention found on {page.get('url', 'page')}")
            # Check JSON-LD for Person schema (heuristic via text)
            if re.search(r'"@type"\s*:\s*"Person"', soup_text, re.I):
                found_author = True
                detail.append(f"Person schema detected on {page.get('url', 'page')}")

        status = "pass" if found_author else "fail"
        self.signals.append({
            "name": "Author Byline / Authorship Schema",
            "status": status,
            "detail": "; ".join(detail) if detail else "No author byline or Person schema found on any sampled page.",
        })

    def _check_original_images(self) -> None:
        pages = self.data.get("pages", [])
        stock_patterns = re.compile(r"shutterstock|gettyimages|istock|stockphoto|placeholder|dummy", re.I)
        total_images = 0
        stock_images = 0
        detail = []

        for page in pages:
            # We don't have raw soup here, so we inspect page data heuristically
            # In a real implementation we'd pass soup or img list; for now we use text heuristics
            text = page.get("_soup_text", "")
            if stock_patterns.search(text):
                stock_images += 1
            # Count img tags via simple regex (approximate)
            total_images += len(re.findall(r"<img", text, re.I))

        if total_images == 0:
            status = "partial"
            detail_text = "No images detected on sampled pages."
        elif stock_images > 0:
            status = "partial"
            detail_text = f"{stock_images} page(s) may contain stock/placeholder image references."
        else:
            status = "pass"
            detail_text = f"{total_images} image(s) found; no obvious stock patterns detected."

        self.signals.append({
            "name": "Original Images (not stock-only)",
            "status": status,
            "detail": detail_text,
        })

    def _check_firsthand_experience(self) -> None:
        pages = self.data.get("pages", [])
        metric_pattern = re.compile(r"\b\d+\s*(%|percent|x|times|years?|months?|days?|\$|USD|km|mi|lbs?|kg)\b", re.I)
        date_pattern = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b", re.I)
        location_pattern = re.compile(r"\b(in|at|near|serving)\s+[A-Z][a-zA-Z]+(?:,\s+[A-Z]{2})?\b")
        pronoun_pattern = re.compile(r"\b(we|our team|our company|my experience|I personally)\b", re.I)

        found_any = False
        detail = []
        for page in pages:
            text = page.get("_soup_text", "")
            has_metric = bool(metric_pattern.search(text))
            has_date = bool(date_pattern.search(text))
            has_location = bool(location_pattern.search(text))
            has_pronoun = bool(pronoun_pattern.search(text))
            if has_metric or has_date or has_location or has_pronoun:
                found_any = True
                parts = []
                if has_metric:
                    parts.append("metrics")
                if has_date:
                    parts.append("dates")
                if has_location:
                    parts.append("locations")
                if has_pronoun:
                    parts.append("first-hand pronouns")
                detail.append(f"{page.get('url', 'page')}: {', '.join(parts)}")

        status = "pass" if found_any else "fail"
        self.signals.append({
            "name": "First-Hand Experience Language",
            "status": status,
            "detail": "; ".join(detail) if detail else "No specific metrics, dates, locations, or first-hand pronouns detected.",
        })

    def _check_source_citations(self) -> None:
        pages = self.data.get("pages", [])
        auth_domains = re.compile(r"\.(edu|gov|org|who|cdc|nih|wikipedia)\b", re.I)
        found = False
        detail = []
        for page in pages:
            text = page.get("_soup_text", "")
            if auth_domains.search(text):
                found = True
                detail.append(f"Outbound authority links suspected on {page.get('url', 'page')}")
        status = "pass" if found else "partial"
        self.signals.append({
            "name": "Source Citations / Outbound Authority Links",
            "status": status,
            "detail": "; ".join(detail) if detail else "No clear outbound citations to .edu, .gov, or recognized authority domains detected.",
        })

    def _check_publication_dates(self) -> None:
        pages = self.data.get("pages", [])
        found = False
        detail = []
        for page in pages:
            text = page.get("_soup_text", "")
            if re.search(r'datePublished|dateModified|published|updated', text, re.I):
                found = True
                detail.append(f"Date metadata found on {page.get('url', 'page')}")
        status = "pass" if found else "fail"
        self.signals.append({
            "name": "Publication & Last-Modified Dates",
            "status": status,
            "detail": "; ".join(detail) if detail else "No publication or modification dates visible in markup.",
        })

    def _check_organization_info(self) -> None:
        pages = self.data.get("pages", [])
        found_about = False
        found_org_schema = False
        detail = []
        for page in pages:
            text = page.get("_soup_text", "")
            if re.search(r'about us|about me|our story|company history', text, re.I):
                found_about = True
                detail.append("About-style content detected")
            if re.search(r'"@type"\s*:\s*"Organization"', text, re.I):
                found_org_schema = True
                detail.append("Organization schema detected")
        status = "pass" if (found_about or found_org_schema) else "fail"
        self.signals.append({
            "name": "Organization Info / About Page",
            "status": status,
            "detail": "; ".join(detail) if detail else "No About page content or Organization schema found.",
        })

    def _check_templated_passages(self) -> None:
        pages = self.data.get("pages", [])
        if len(pages) < 2:
            self.signals.append({
                "name": "Templated / Repetitive Passages",
                "status": "partial",
                "detail": "Only one page sampled — cannot assess repetition across pages.",
            })
            return

        # Simple paragraph-level similarity
        paragraphs_by_page = []
        for page in pages:
            text = page.get("_soup_text", "")
            paras = [p.strip().lower() for p in re.split(r"\n\n+", text) if len(p.strip()) > 40]
            paragraphs_by_page.append(set(paras))

        all_paras = set()
        repeated = set()
        for pset in paragraphs_by_page:
            for para in pset:
                if para in all_paras:
                    repeated.add(para)
                else:
                    all_paras.add(para)

        total = sum(len(s) for s in paragraphs_by_page)
        repeat_count = len(repeated)
        if total == 0:
            status = "partial"
            detail = "No substantial paragraphs to compare."
        elif repeat_count / total > 0.30:
            status = "fail"
            detail = f"{repeat_count}/{total} paragraph blocks appear on multiple pages (possible templated content)."
        elif repeat_count > 0:
            status = "partial"
            detail = f"{repeat_count}/{total} paragraph blocks are repeated (minor templating)."
        else:
            status = "pass"
            detail = "No significant repetitive passages detected across sampled pages."

        self.signals.append({
            "name": "Templated / Repetitive Passages",
            "status": status,
            "detail": detail,
        })

    def _check_faq_structured_data(self) -> None:
        pages = self.data.get("pages", [])
        found_faq = False
        found_schema = False
        detail = []
        for page in pages:
            text = page.get("_soup_text", "")
            if re.search(r'faq|frequently asked', text, re.I):
                found_faq = True
                detail.append(f"FAQ section visible on {page.get('url', 'page')}")
            if re.search(r'"@type"\s*:\s*"FAQPage"', text, re.I):
                found_schema = True
                detail.append(f"FAQPage schema on {page.get('url', 'page')}")
        status = "pass" if (found_faq or found_schema) else "fail"
        self.signals.append({
            "name": "FAQ & Structured Data Accuracy",
            "status": status,
            "detail": "; ".join(detail) if detail else "No FAQ section or FAQPage schema detected.",
        })

    def _build_summary(self, pass_count: int, fail_count: int, partial_count: int) -> str:
        total = pass_count + fail_count + partial_count
        return (
            f"Content Evidence: {pass_count}/{total} passed, "
            f"{fail_count} failed, {partial_count} partial."
        )
