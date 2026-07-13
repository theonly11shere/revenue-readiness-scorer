"""
Rule-based scoring engine with three-score output.
No AI. No LLM. Hardcoded weights and logic.
"""

from typing import Dict, Any, List, TypedDict
from config import CHECKPOINTS, SEVERITY, FUTURE_PREDICTIONS, TOTAL_CHECKS, get_failure_severity


class Scores(TypedDict):
    readiness_score: int          # 0-100 based only on checks that successfully ran
    evidence_coverage: int        # 0-100 (completed_checks / total_intended_checks)
    confidence_score: int         # 0-100 weighted by category data completeness


class RevenueScorer:
    def __init__(self, scraped_data: Dict[str, Any]):
        self.data = scraped_data
        self.scores: Scores = {"readiness_score": 0, "evidence_coverage": 0, "confidence_score": 0}
        self.failures: List[Dict[str, Any]] = []
        self.severity: Dict[str, Any] = {}
        self.completed_checks = 0
        self.skipped_checks = 0

    def calculate_scores(self) -> Scores:
        total = 0.0
        max_total = 0.0
        completed_by_category: Dict[str, int] = {}
        total_by_category: Dict[str, int] = {}

        for category, config in CHECKPOINTS.items():
            cat_data = self.data.get(category, {})
            cat_score = 0.0
            cat_max = 0.0
            cat_completed = 0

            for item in config["items"]:
                key = item["method"].replace("check_", "")
                value = cat_data.get(key)

                # A check is "completed" if the key exists in scraped data (even if False/0)
                was_completed = value is not None
                if was_completed:
                    cat_completed += 1
                    self.completed_checks += 1
                else:
                    self.skipped_checks += 1

                if isinstance(value, bool):
                    points = item["weight"] if value else 0
                elif isinstance(value, (int, float)):
                    points = min(float(value), float(item["weight"]))
                else:
                    points = 0.0

                cat_score += points
                cat_max += item["weight"]

                # Flag as failure if value is falsy or below half weight
                is_failure = False
                if not was_completed:
                    is_failure = True
                elif isinstance(value, bool):
                    is_failure = not value
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    is_failure = value < item["weight"] * 0.5
                else:
                    is_failure = True  # unexpected type

                if is_failure:
                    self.failures.append({
                        "category": category,
                        "item": item["name"],
                        "weight": item["weight"],
                        "method": item["method"],
                        "value": value,
                        "severity": get_failure_severity(item["weight"]),
                        "completed": was_completed,
                    })

            total += cat_score * config["weight"]
            max_total += cat_max * config["weight"]
            completed_by_category[category] = cat_completed
            total_by_category[category] = len(config["items"])

        # readiness_score: based only on checks that ran
        readiness = int((total / max_total) * 100) if max_total > 0 else 0

        # evidence_coverage: completed / total intended checks
        evidence = int((self.completed_checks / TOTAL_CHECKS) * 100) if TOTAL_CHECKS > 0 else 0

        # confidence_score: weighted by categories with complete data
        confidence_num = 0.0
        confidence_den = 0.0
        for category, config in CHECKPOINTS.items():
            weight = config["weight"]
            confidence_den += weight
            if completed_by_category.get(category, 0) > 0:
                confidence_num += weight
        confidence = int((confidence_num / confidence_den) * 100) if confidence_den > 0 else 0

        self.scores = {
            "readiness_score": max(0, min(100, readiness)),
            "evidence_coverage": max(0, min(100, evidence)),
            "confidence_score": max(0, min(100, confidence)),
        }

        self._determine_severity()
        return self.scores

    @property
    def score(self) -> int:
        """Backward-compatible single score alias."""
        return self.scores["readiness_score"]

    def _determine_severity(self) -> None:
        readiness = self.scores["readiness_score"]
        for key, (low, high, label, desc) in SEVERITY.items():
            if low <= readiness <= high:
                self.severity = {"key": key, "label": label, "desc": desc}
                break

    def get_future_prediction(self) -> Dict[int, int]:
        key = self.severity.get("key", "fair")
        return FUTURE_PREDICTIONS.get(key, {})

    def get_top_failures(self, n: int = 3) -> List[Dict[str, Any]]:
        sorted_failures = sorted(
            self.failures,
            key=lambda x: (x["weight"], x["severity"] == "critical"),
            reverse=True,
        )
        return sorted_failures[:n]

    def get_failure_summary(self) -> List[Dict[str, Any]]:
        """Return all failures with severity for transparent reporting."""
        return [
            {
                "category": f["category"],
                "item": f["item"],
                "severity": f["severity"],
                "one_liner": f"{f['item']} is missing or below threshold.",
                "completed": f["completed"],
            }
            for f in self.failures
        ]
