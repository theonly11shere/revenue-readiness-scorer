"""
Report generator — creates free, paid, and admin reports.
Includes RevenueExposureCalculator, transparent failure reporting,
Content Evidence Signals, and three-score display.
"""

import html
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import (
    THREAT_TEMPLATES,
    TOTAL_CHECKS,
    PRICING,
    CALCULATOR_LABEL,
    DEFAULT_TRAFFIC,
    DEFAULT_CONVERSION_RATE,
    DEFAULT_AOV,
    DEFAULT_PROFIT_MARGIN,
    FREE_REPORT_CTA,
    get_failure_severity,
)


class RevenueExposureCalculator:
    """
    Illustrative revenue exposure calculator.
    Accepts user-editable inputs; defaults to conservative industry estimates.
    """

    def __init__(
        self,
        readiness_score: int,
        traffic: Optional[int] = None,
        conversion_rate: Optional[float] = None,
        aov: Optional[float] = None,
        profit_margin: Optional[float] = None,
    ):
        self.readiness_score = readiness_score
        self.user_provided = {
            "traffic": traffic is not None,
            "conversion_rate": conversion_rate is not None,
            "aov": aov is not None,
            "profit_margin": profit_margin is not None,
        }
        self.traffic = traffic if traffic is not None else DEFAULT_TRAFFIC
        self.conversion_rate = conversion_rate if conversion_rate is not None else DEFAULT_CONVERSION_RATE
        self.aov = aov if aov is not None else DEFAULT_AOV
        self.profit_margin = profit_margin if profit_margin is not None else DEFAULT_PROFIT_MARGIN

    def _scenario(self, traffic_mult: float, conv_mult: float, aov_mult: float, pm_mult: float) -> Dict[str, Any]:
        t = int(self.traffic * traffic_mult)
        c = min(self.conversion_rate * conv_mult, 1.0)
        a = self.aov * aov_mult
        pm = min(self.profit_margin * pm_mult, 1.0)
        monthly_revenue = t * c * a
        monthly_profit = monthly_revenue * pm
        readiness_gap = max(0, 1 - self.readiness_score / 100)
        annual_exposure = monthly_profit * 12 * readiness_gap
        return {
            "traffic": t,
            "conversion_rate": round(c, 4),
            "aov": round(a, 2),
            "profit_margin": round(pm, 4),
            "monthly_revenue": round(monthly_revenue, 2),
            "monthly_profit": round(monthly_profit, 2),
            "annual_exposure": round(annual_exposure, 2),
            "readiness_gap": round(readiness_gap, 4),
        }

    def calculate(self) -> Dict[str, Any]:
        return {
            "label": CALCULATOR_LABEL,
            "user_provided": self.user_provided,
            "assumptions_banner": (
                "Values shown are conservative industry estimates. "
                "Provide your actual numbers for a personalized projection."
                if not any(self.user_provided.values())
                else "Based on your provided business data."
            ),
            "assumptions": {
                "traffic_per_month": self.traffic,
                "conversion_rate": self.conversion_rate,
                "average_order_value": self.aov,
                "profit_margin": self.profit_margin,
            },
            "conservative": self._scenario(0.5, 0.5, 0.5, 0.5),
            "expected": self._scenario(1.0, 1.0, 1.0, 1.0),
            "high_exposure": self._scenario(2.0, 1.5, 1.5, 1.0),
        }


class ReportGenerator:
    def __init__(
        self,
        url: str,
        revenue_score: Any,
        content_evidence: Any,
        scraper_data: Dict[str, Any],
        top_failures: List[Dict[str, Any]],
        calculator_inputs: Optional[Dict[str, Any]] = None,
    ):
        self.url = url
        self.revenue_score = revenue_score
        self.content_evidence = content_evidence
        self.scraper_data = scraper_data
        self.top_failures = top_failures
        self.calculator_inputs = calculator_inputs or {}
        self.timestamp = datetime.now().isoformat()

    # ── Free report ──────────────────────────────────────────────────────────────
    def generate_free(self) -> Dict[str, Any]:
        # Transparent failure reporting: show existence of ALL critical/high failures
        all_summaries = self.revenue_score.get_failure_summary()
        critical_high = [f for f in all_summaries if f["severity"] in ("critical", "high")]
        visible_failures = self.top_failures[1:3] if len(self.top_failures) >= 3 else self.top_failures[1:]

        # Revenue exposure teaser (conservative only)
        calc = RevenueExposureCalculator(
            self.revenue_score.scores["readiness_score"],
            **self.calculator_inputs,
        )
        exposure = calc.calculate()

        return {
            "type": "free",
            "url": self.url,
            "timestamp": self.timestamp,
            "scores": self.revenue_score.scores,
            "severity": self.revenue_score.severity,
            "content_evidence_signals": self.content_evidence.signals,
            "future_prediction": self.revenue_score.get_future_prediction(),
            "visible_failures": visible_failures,
            "failure_summary": critical_high,  # existence only, no evidence
            "hidden_failure_count": len(all_summaries) - len(visible_failures),
            "upgrade_cta": FREE_REPORT_CTA,
            "pages_sampled": self.scraper_data.get("pages_sampled", 1),
            "template_breakdown": self.scraper_data.get("template_breakdown", {}),
            "revenue_exposure_teaser": {
                "label": exposure["label"],
                "assumptions_banner": exposure["assumptions_banner"],
                "conservative_scenario": exposure["conservative"],
            },
        }

    # ── Paid report ────────────────────────────────────────────────────────────
    def generate_paid(self) -> Dict[str, Any]:
        all_failures = self.top_failures
        calc = RevenueExposureCalculator(
            self.revenue_score.scores["readiness_score"],
            **self.calculator_inputs,
        )
        exposure = calc.calculate()

        return {
            "type": "paid",
            "url": self.url,
            "timestamp": self.timestamp,
            "scores": self.revenue_score.scores,
            "severity": self.revenue_score.severity,
            "content_evidence_signals": self.content_evidence.signals,
            "all_checkpoints": all_failures,
            "methods_only": True,
            "action_plan": self._generate_action_plan(),
            "revenue_exposure": exposure,
            "pages_sampled": self.scraper_data.get("pages_sampled", 1),
            "template_breakdown": self.scraper_data.get("template_breakdown", {}),
        }

    # ── Admin report ───────────────────────────────────────────────────────────
    def generate_admin(self) -> Dict[str, Any]:
        calc = RevenueExposureCalculator(
            self.revenue_score.scores["readiness_score"],
            **self.calculator_inputs,
        )
        return {
            "type": "admin",
            "url": self.url,
            "timestamp": self.timestamp,
            "scores": self.revenue_score.scores,
            "severity": self.revenue_score.severity,
            "content_evidence_signals": self.content_evidence.signals,
            "complete_sources": self.scraper_data,
            "all_failures": self.top_failures,
            "threat_analysis": self._analyze_threats(),
            "human_gist": self._generate_human_gist(),
            "estimated_research_time": self._estimate_research_time(),
            "suggested_fixes": self._suggest_fixes(),
            "revenue_exposure": calc.calculate(),
            "pages_sampled": self.scraper_data.get("pages_sampled", 1),
            "template_breakdown": self.scraper_data.get("template_breakdown", {}),
        }

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _generate_action_plan(self) -> List[Dict[str, Any]]:
        plan = []
        for i, failure in enumerate(self.top_failures[:5], 1):
            plan.append({
                "priority": i,
                "task": f"Fix: {failure['item']}",
                "effort": "Medium" if failure["weight"] < 4 else "High",
                "impact": "High" if failure["weight"] >= 4 else "Medium",
            })
        return plan

    def _analyze_threats(self) -> List[Dict[str, Any]]:
        threats = []
        for failure in self.top_failures[:3]:
            key = failure["method"].replace("check_", "")
            if key in THREAT_TEMPLATES:
                threats.append({
                    "checkpoint": failure["item"],
                    "threat": THREAT_TEMPLATES[key],
                    "source": failure["method"],
                })
        return threats

    def _generate_human_gist(self) -> str:
        sev = self.revenue_score.severity
        top = self.top_failures[0]["item"] if self.top_failures else "None"
        return f"{sev['label']}: {sev['desc']}. Top threat: {top}. Recommend human report if score < 55."

    def _estimate_research_time(self) -> str:
        return f"{len(self.top_failures) * 15} minutes"

    def _suggest_fixes(self) -> List[Dict[str, Any]]:
        fixes = []
        for failure in self.top_failures[:3]:
            fixes.append({
                "issue": failure["item"],
                "fix": f"Implement {failure['item'].lower()} using standard web practices.",
                "method": failure["method"],
            })
        return fixes
