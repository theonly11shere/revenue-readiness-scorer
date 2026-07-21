#!/usr/bin/env python3
"""
Content Evidence Signals — Replaces AI Detection with real trust signals.
Checks for authorship, originality, citations, dates, and organizational presence.
"""

import re
from typing import Dict, Any, List, Optional, Set
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse


class ContentEvidenceSignals:
    """
    Evaluates content quality through evidence-based signals.
    Returns pass/fail/partial with descriptive reasoning.
    """

    def __init__(self, soup: BeautifulSoup, url: str, all_pages_text: List[str] = None):
        self.soup = soup
        self.url = url
        self.domain = urlparse(url).netloc.lower()
        self.all_pages_text = all_pages_text or []
        self.signals: List[Dict[str, Any]] = []
        self._analyze()

    def _analyze(self) -> None:
        """Run all evidence signal checks."""
        self._check_author_byline()
        self._check_original_images()
        self._check_first_hand_experience()
        self._check_source_citations()
        self._check_publication_dates()
        self._check_organization_info()
        self._check_templated_passages()
        self._check_faq_structured_data()

    def _check_author_byline(self) -> None:
        """Check for author byline or authorship schema markup."""
        text = self.soup.get_text(separator=" ", strip=True).lower()

        # Check for author schema
        author_schema = self.soup.find("script", attrs={"type": "application/ld+json"})
        has_author_schema = False
        if author_schema:
            schema_text = author_schema.get_text()
            has_author_schema = '"author"' in schema_text.lower() or '"person"' in schema_text.lower()

        # Check for byline patterns
        byline_patterns = [
            r'by\s+[A-Z][a-z]+\s+[A-Z][a-z]+',
            r'written\s+by\s+[A-Z][a-z]+',
            r'author:\s*[A-Z][a-z]+',
        ]
        has_byline = any(re.search(p, text, re.I) for p in byline_patterns)

        # Check for author meta tag
        author_meta = self.soup.find("meta", attrs={"name": "author"})
        has_author_meta = author_meta is not None and author_meta.get("content")

        if has_author_schema or has_byline or has_author_meta:
            status = "pass"
            detail = "Author attribution found (byline or schema markup)."
        else:
            status = "fail"
            detail = "No author byline or authorship schema detected. Google EEAT requires clear authorship."

        self.signals.append({
            "name": "Author Byline / Authorship Schema",
            "status": status,
            "detail": detail,
            "weight": 3,
        })

    def _check_original_images(self) -> None:
        """Check if images appear original vs stock-only."""
        images = self.soup.find_all("img")
        if not images:
            self.signals.append({
                "name": "Original Images (not stock-only)",
                "status": "fail",
                "detail": "No images found on page. Visual content is critical for trust.",
                "weight": 3,
            })
            return

        stock_patterns = [
            r'shutterstock', r'istock', r'getty', r'adobestock', r'depositphotos',
            r'unsplash', r'pexels', r'pixabay', r'freepik',
            r'stock\s*photo', r'placeholder',
        ]
        stock_count = 0
        total_with_src = 0

        for img in images:
            src = img.get("src", "")
            alt = img.get("alt", "").lower()
            if not src:
                continue
            total_with_src += 1
            combined = (src + " " + alt).lower()
            if any(re.search(p, combined) for p in stock_patterns):
                stock_count += 1

        if total_with_src == 0:
            stock_ratio = 0
        else:
            stock_ratio = stock_count / total_with_src

        if stock_ratio > 0.7:
            status = "fail"
            detail = f"{int(stock_ratio*100)}% of images appear to be stock photos. Visitors trust real photos of real work."
        elif stock_ratio > 0.3:
            status = "partial"
            detail = f"{int(stock_ratio*100)}% stock imagery detected. Mix in original photos for credibility."
        else:
            status = "pass"
            detail = "Most images appear original. Good visual trust signal."

        self.signals.append({
            "name": "Original Images (not stock-only)",
            "status": status,
            "detail": detail,
            "weight": 3,
        })

    def _check_first_hand_experience(self) -> None:
        """Check for first-hand experience language: specific metrics, dates, locations."""
        text = self.soup.get_text(separator=" ", strip=True)

        # Patterns indicating first-hand experience
        specific_metrics = len(re.findall(r'\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:percent|%|x|times|years?|months?|days?|hours?|minutes?|dollars?|\$|clients?|projects?)', text, re.I))
        dates = len(re.findall(r'(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}', text))
        dates += len(re.findall(r'\d{1,2}/\d{1,2}/\d{2,4}', text))
        locations = len(re.findall(r'(?:in|at|near|serving|located in)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?,\s*(?:[A-Z]{2}|USA|Canada|UK)', text))

        score = min(100, (specific_metrics * 5 + dates * 10 + locations * 15))

        if score >= 60:
            status = "pass"
            detail = f"Strong first-hand signals: {specific_metrics} metrics, {dates} dates, {locations} locations mentioned."
        elif score >= 30:
            status = "partial"
            detail = f"Some specificity found ({specific_metrics} metrics, {dates} dates), but could be more detailed."
        else:
            status = "fail"
            detail = "No specific metrics, dates, or locations found. Content reads as generic/generic. Add real numbers and real stories."

        self.signals.append({
            "name": "First-Hand Experience Language",
            "status": status,
            "detail": detail,
            "weight": 4,
        })

    def _check_source_citations(self) -> None:
        """Check for outbound links to authoritative sources."""
        links = self.soup.find_all("a", href=True)
        outbound = []

        for link in links:
            href = link.get("href", "")
            if href.startswith("http") and self.domain not in href.lower():
                outbound.append(href)

        # Check for citation patterns
        text = self.soup.get_text()
        citation_patterns = [
            r'according to', r'cited in', r'references?', r'sources?',
            r'study by', r'research from', r'report by', r'data from',
            r'\[\d+\]', r'\(\d{4}\)',
        ]
        citation_count = sum(len(re.findall(p, text, re.I)) for p in citation_patterns)

        if len(outbound) >= 3 and citation_count >= 2:
            status = "pass"
            detail = f"{len(outbound)} outbound authority links, {citation_count} citation patterns. Content is well-sourced."
        elif len(outbound) >= 1 or citation_count >= 1:
            status = "partial"
            detail = f"Some sourcing ({len(outbound)} outbound links, {citation_count} citations), but could be stronger."
        else:
            status = "fail"
            detail = "No outbound authority links or citations. Unsourced claims reduce EEAT score."

        self.signals.append({
            "name": "Source Citations / Outbound Authority Links",
            "status": status,
            "detail": detail,
            "weight": 3,
        })

    def _check_publication_dates(self) -> None:
        """Check for publication and last-modified dates."""
        # Check meta tags
        published = self.soup.find("meta", attrs={"property": "article:published_time"})
        modified = self.soup.find("meta", attrs={"property": "article:modified_time"})

        # Check visible dates
        text = self.soup.get_text()
        visible_date = re.search(r'(?:published|posted|updated|modified)[\s:]+\s*(?:on\s+)?([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', text, re.I)

        has_published = published is not None or bool(visible_date)
        has_modified = modified is not None

        if has_published and has_modified:
            status = "pass"
            detail = "Both published and last-modified dates present. Freshness signal strong."
        elif has_published:
            status = "partial"
            detail = "Publication date found, but no last-modified date. Add modified time for freshness signals."
        else:
            status = "fail"
            detail = "No publication or modification dates visible. Google and users question content freshness."

        self.signals.append({
            "name": "Publication & Last-Modified Dates",
            "status": status,
            "detail": detail,
            "weight": 2,
        })

    def _check_organization_info(self) -> None:
        """Check for About page and Organization schema."""
        # Check for About link
        about_link = self.soup.find("a", href=re.compile(r'about', re.I))
        has_about = about_link is not None

        # Check for Organization schema
        org_schema = False
        schema_scripts = self.soup.find_all("script", attrs={"type": "application/ld+json"})
        for script in schema_scripts:
            text = script.get_text()
            if '"@type"' in text and ('Organization' in text or 'LocalBusiness' in text or 'Corporation' in text):
                org_schema = True
                break

        # Check for business name mentions
        text = self.soup.get_text()
        business_mentions = len(re.findall(r'we\s+(?:are|have|do|serve|specialize)', text, re.I))

        if has_about and org_schema:
            status = "pass"
            detail = "About page linked and Organization schema present. Strong entity signal."
        elif has_about or org_schema:
            status = "partial"
            detail = "Some organization info present, but incomplete. Add both About page and schema markup."
        else:
            status = "fail"
            detail = "No About page or Organization schema. Visitors (and Google) can't verify you're a real business."

        self.signals.append({
            "name": "Organization Info / About Page",
            "status": status,
            "detail": detail,
            "weight": 3,
        })

    def _check_templated_passages(self) -> None:
        """Check for templated/repetitive passages across pages."""
        if len(self.all_pages_text) < 2:
            self.signals.append({
                "name": "Templated / Repetitive Passages",
                "status": "partial",
                "detail": "Only one page analyzed. Need multiple pages to detect templated content.",
                "weight": 3,
            })
            return

        # Find common phrases across pages
        from collections import Counter

        all_phrases = []
        for page_text in self.all_pages_text:
            # Extract 5-word phrases
            words = page_text.split()
            for i in range(len(words) - 4):
                phrase = " ".join(words[i:i+5]).lower()
                # Filter out common/generic phrases
                if len(phrase) > 20 and not all(w in {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"} for w in phrase.split()):
                    all_phrases.append(phrase)

        phrase_counts = Counter(all_phrases)
        repeated = [(p, c) for p, c in phrase_counts.items() if c > 1]

        if len(repeated) > 10:
            status = "fail"
            detail = f"{len(repeated)} repeated 5-word phrases across pages. Heavy templating detected."
        elif len(repeated) > 3:
            status = "partial"
            detail = f"{len(repeated)} repeated phrases. Some templating, but mostly unique."
        else:
            status = "pass"
            detail = "Content appears unique across pages. Low templating detected."

        self.signals.append({
            "name": "Templated / Repetitive Passages",
            "status": status,
            "detail": detail,
            "weight": 3,
        })

    def _check_faq_structured_data(self) -> None:
        """Check for FAQ page and structured data accuracy."""
        # Check for FAQ link or section
        faq_link = self.soup.find("a", href=re.compile(r'faq|frequently', re.I))
        faq_section = self.soup.find(string=re.compile(r'FAQ|Frequently Asked', re.I))
        has_faq = faq_link is not None or faq_section is not None

        # Check for FAQ schema
        faq_schema = False
        schema_scripts = self.soup.find_all("script", attrs={"type": "application/ld+json"})
        for script in schema_scripts:
            text = script.get_text()
            if 'FAQPage' in text:
                faq_schema = True
                break

        if has_faq and faq_schema:
            status = "pass"
            detail = "FAQ section present with structured data markup. Rich result eligible."
        elif has_faq:
            status = "partial"
            detail = "FAQ content found, but no FAQPage schema. Add structured data for rich snippets."
        else:
            status = "fail"
            detail = "No FAQ section found. FAQs capture long-tail search intent and build trust."

        self.signals.append({
            "name": "FAQ & Structured Data Accuracy",
            "status": status,
            "detail": detail,
            "weight": 2,
        })

    def get_signals(self) -> List[Dict[str, Any]]:
        """Return all evidence signals."""
        return self.signals

    def get_score(self) -> int:
        """Calculate overall evidence score (0-100)."""
        if not self.signals:
            return 0
        total_weight = sum(s["weight"] for s in self.signals)
        earned = sum(s["weight"] for s in self.signals if s["status"] == "pass")
        earned += sum(s["weight"] * 0.5 for s in self.signals if s["status"] == "partial")
        return min(100, int((earned / total_weight) * 100))
