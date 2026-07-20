"""
Branded PDF renderer for the Revenue Readiness Report.

Turns the raw report JSON into a clean, branded document the founder can
forward straight to the customer. Full truth, no softening — every failure,
every score, the doppelganger analysis, and a closing page with the two
next moves (roadmap + free one-time session, or hire the Architect).

Uses fpdf2 (pure Python — no system dependencies, Railway-safe).
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

GOLD = (212, 175, 55)
DARK = (13, 13, 13)
INK = (30, 30, 26)
MUTED = (110, 104, 88)
RED = (190, 24, 24)
AMBER = (190, 120, 0)
GREEN = (22, 130, 92)

_REPLACEMENTS = {
    "\u2014": "-", "\u2013": "-", "\u2019": "'", "\u2018": "'",
    "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u00b7": "-",
    "\u00e4": "a", "\u00e9": "e", "\u2713": "v", "\u2192": "->", "\u00d7": "x",
}


def _t(text: Any) -> str:
    """Make text safe for PDF core fonts (latin-1)."""
    out = str(text if text is not None else "")
    for k, v in _REPLACEMENTS.items():
        out = out.replace(k, v)
    return out.encode("latin-1", "replace").decode("latin-1")


def _band_color(score: float) -> Tuple[int, int, int]:
    if score >= 70:
        return GREEN
    if score >= 40:
        return AMBER
    return RED


def _presence_color(verdict: str) -> Tuple[int, int, int]:
    return {"discussed": GREEN, "quiet": AMBER, "invisible": RED, "own": GOLD}.get(verdict, MUTED)


class _ReportPDF:
    def __init__(self, report: Dict[str, Any], url: str, lead_email: Optional[str], tier: str):
        from fpdf import FPDF  # fpdf2 — pure python

        self.report = report
        self.url = url
        self.lead_email = lead_email
        self.tier = tier
        self.pdf = FPDF(orientation="P", unit="mm", format="A4")
        self.pdf.set_margins(15, 22, 15)
        self.pdf.set_auto_page_break(auto=True, margin=18)

        # register per-page brand header/footer
        pdf = self.pdf

        def _header():
            pdf.set_fill_color(*DARK)
            pdf.rect(0, 0, 210, 14, "F")
            pdf.set_xy(15, 3.5)
            pdf.set_font("helvetica", "B", 10)
            pdf.set_text_color(*GOLD)
            pdf.cell(120, 7, "TRILLOKA  //  REVENUE READINESS REPORT")
            pdf.set_font("helvetica", "", 8)
            pdf.set_text_color(245, 230, 200)
            pdf.cell(0, 7, "trilloka.com", align="R")
            pdf.set_xy(15, 22)  # hand content flow back to the top margin

        def _footer():
            pdf.set_y(-14)
            pdf.set_draw_color(*GOLD)
            pdf.set_line_width(0.2)
            pdf.line(15, pdf.get_y(), 195, pdf.get_y())
            pdf.set_y(-11)
            pdf.set_font("helvetica", "", 8)
            pdf.set_text_color(*MUTED)
            pdf.cell(120, 6, "Prepared by The Architect - trilloka.com")
            pdf.cell(0, 6, f"Page {pdf.page_no()}", align="R")

        self.pdf.header = _header  # type: ignore[attr-defined]
        self.pdf.footer = _footer  # type: ignore[attr-defined]

    # ---------- layout helpers ----------
    def _section(self, title: str) -> None:
        pdf = self.pdf
        pdf.ln(4)
        pdf.set_font("helvetica", "B", 11)
        pdf.set_text_color(*GOLD)
        pdf.cell(0, 7, _t(title.upper()), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(220, 214, 196)
        pdf.set_line_width(0.2)
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())
        pdf.ln(2)

    def _kv(self, key: str, value: str, value_color: Tuple[int, int, int] = INK, bold_value: bool = True) -> None:
        pdf = self.pdf
        pdf.set_font("helvetica", "", 10)
        pdf.set_text_color(*MUTED)
        pdf.cell(62, 6, _t(key))
        pdf.set_font("helvetica", "B" if bold_value else "", 10)
        pdf.set_text_color(*value_color)
        pdf.multi_cell(0, 6, _t(value), new_x="LMARGIN", new_y="NEXT")

    def _para(self, text: str, size: int = 10, color: Tuple[int, int, int] = INK, bold: bool = False) -> None:
        pdf = self.pdf
        pdf.set_font("helvetica", "B" if bold else "", size)
        pdf.set_text_color(*color)
        pdf.multi_cell(0, 5.4, _t(text), new_x="LMARGIN", new_y="NEXT")

    def _bullet(self, text: str, color: Tuple[int, int, int] = INK, prefix: str = "- ") -> None:
        pdf = self.pdf
        pdf.set_font("helvetica", "", 9.5)
        pdf.set_text_color(*color)
        pdf.multi_cell(0, 5.2, _t(prefix + text), new_x="LMARGIN", new_y="NEXT")

    # ---------- sections ----------
    def _cover(self) -> None:
        from urllib.parse import urlparse
        pdf = self.pdf
        domain = urlparse(self.url).hostname or self.url
        when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        tier_label = {"free": "Free Scan", "paid": "Full Report", "roadmap": "Full Report + Fix Roadmap"}.get(self.tier, self.tier)

        pdf.ln(10)
        pdf.set_font("helvetica", "B", 22)
        pdf.set_text_color(*DARK)
        pdf.multi_cell(0, 9, _t(domain), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 6, _t(f"{tier_label}  |  {when}" + (f"  |  Lead: {self.lead_email}" if self.lead_email else "")),
                 new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    def _scores(self) -> None:
        pdf = self.pdf
        scores = self.report.get("scores") or {}
        sev = self.report.get("severity") or {}
        self._section("The Score")
        for label, key in (("Revenue Readiness", "readiness_score"),
                           ("Evidence Coverage", "evidence_coverage"),
                           ("Confidence", "confidence_score")):
            v = scores.get(key)
            if v is None:
                continue
            self._kv(label, f"{v} / 100", _band_color(v))
        label = sev.get("label") or ""
        desc = sev.get("desc") or ""
        if label:
            pdf.ln(1)
            self._para(f"Verdict: {label}", size=12, color=DARK, bold=True)
        if desc:
            self._para(f'"{desc}"', color=MUTED)

    def _doppelganger(self) -> None:
        fp = self.report.get("template_fingerprint") or {}
        cs = self.report.get("content_sameness") or {}
        vt = self.report.get("visual_twin") or {}
        sp = self.report.get("social_presence") or {}
        if not (fp or cs or vt or sp):
            return
        self._section("Doppelganger Analysis - how much you blend in")
        if fp:
            detected = fp.get("detected_template") or "Custom / Unknown"
            self._kv("Template fingerprint", f"{detected} ({fp.get('generic_score', 0)}% generic)", RED if (fp.get("generic_score") or 0) >= 70 else INK)
            if fp.get("is_custom"):
                self._kv("Template footprint", "No common template detected", GREEN)
            elif fp.get("template_reported_installs"):
                self._kv("Template footprint", f"{fp['template_reported_installs']} active installs (vendor-reported)")
        if cs:
            self._kv("Content sameness", f"{cs.get('score', 0)} / 100", RED if (cs.get("score") or 0) >= 70 else INK)
            matched = cs.get("matched_phrases") or []
            if matched:
                self._kv("Cliches found", f"{cs.get('matched_count', len(matched))} of {cs.get('tracked_count', 36)} tracked cliches: " + ", ".join(matched[:8]))
        if vt:
            twin = vt.get("closest_match_url") or "none yet"
            self._kv("Visual twin", f"{vt.get('similarity_percent', 0)}% layout match - {twin}", RED if (vt.get("similarity_percent") or 0) >= 70 else INK)
            elems = vt.get("matching_elements") or []
            if elems:
                self._kv("Matching elements", ", ".join(elems))
        if sp:
            verdict = sp.get("verdict") or ""
            self._kv("Online presence", f"{sp.get('mentions_found', 0)} public mentions - {sp.get('verdict_label', '')}", _presence_color(verdict))
            for neg in sp.get("negative_examples") or []:
                self._bullet(neg, RED, prefix="- NEGATIVE: ")
            for pos in sp.get("positive_examples") or []:
                self._bullet(pos, GREEN, prefix="+ POSITIVE: ")

    def _failures(self) -> None:
        fails = self.report.get("visible_failures") or []
        fixes = self.report.get("fix_steps") or []
        hidden = self.report.get("hidden_failure_count") or 0
        if not fails and not fixes:
            return
        self._section("What is broken - every issue, no sugar-coating")
        if fixes:  # paid tiers: full detail with fix steps
            for f in fixes:
                self._bullet(f"[{str(f.get('severity', '')).upper()}] {f.get('item', '')}", RED if str(f.get("severity")) == "critical" else INK, prefix="")
                for step in (f.get("fix_steps") or []):
                    self._bullet(step, MUTED, prefix="    ")
        else:
            for f in fails:
                self._bullet(f"[{str(f.get('severity', '')).upper()}] {f.get('one_liner') or f.get('item', '')}",
                             RED if str(f.get('severity')) in ("critical", "high") else INK)
        if hidden:
            self.pdf.ln(1)
            self._para(f"+ {hidden} more issues are documented in the full report.", color=MUTED, bold=True)

    def _roadmap(self) -> None:
        weeks = self.report.get("roadmap") or []
        if not weeks:
            return
        self._section("Your 4-week fix roadmap")
        for w in weeks:
            self._para(f"{w.get('week', '')} - {w.get('focus', '')}", size=11, color=DARK, bold=True)
            for it in w.get("items") or []:
                self._bullet(f"[{str(it.get('severity', '')).upper()}] {it.get('item', '')}", INK, prefix="  - ")
                for step in (it.get("steps") or []):
                    self._bullet(step, MUTED, prefix="      ")

    def _cta(self) -> None:
        pdf = self.pdf
        # The whole CTA block (~100mm) must sit on one page — no orphan lines.
        if pdf.get_y() > 155:
            pdf.add_page()
        self._section("Your next move")
        self._para("You have two ways to fix what this report just showed you:", color=INK)
        pdf.ln(2)
        pdf.set_fill_color(245, 240, 226)
        pdf.set_draw_color(*GOLD)
        pdf.rect(15, pdf.get_y(), 180, 30, "DF")
        pdf.set_xy(20, pdf.get_y() + 4)
        self._para("OPTION A - The Fix Roadmap ($299) + a FREE one-time session", size=11, color=DARK, bold=True)
        pdf.set_x(20)
        self._para("Every fix ordered week by week - then a free one-time call with the Architect", color=MUTED)
        pdf.set_x(20)
        self._para("to walk you through it. Details: trilloka.com", color=MUTED)
        pdf.ln(13)
        pdf.set_fill_color(*DARK)
        pdf.rect(15, pdf.get_y(), 180, 30, "DF")
        pdf.set_xy(20, pdf.get_y() + 4)
        pdf.set_font("helvetica", "B", 11)
        pdf.set_text_color(*GOLD)
        pdf.cell(0, 6, "OPTION B - Hire the Architect (from $997/mo)", new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(20)
        pdf.set_font("helvetica", "", 10)
        pdf.set_text_color(245, 230, 200)
        pdf.multi_cell(170, 5.4, "We rebuild the site, kill the doppelganger, and make you genuinely visible online. Book: trilloka.com/contact  |  onlyonearpit@gmail.com", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(11)
        self._para("This report is the unedited truth about the scanned website - every number measured at scan time.", size=8, color=MUTED)

    def build(self) -> bytes:
        self.pdf.add_page()
        self._cover()
        self._scores()
        self._doppelganger()
        self._failures()
        self._roadmap()
        self._cta()
        return bytes(self.pdf.output())


def build_report_pdf(report: Dict[str, Any], url: str, lead_email: Optional[str] = None, tier: str = "free") -> bytes:
    """Render the report JSON to branded PDF bytes. Raises if fpdf2 is missing."""
    return _ReportPDF(report, url, lead_email, tier).build()
