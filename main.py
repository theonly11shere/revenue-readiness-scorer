"""
Revenue Readiness Scorer — Entry Point
Usage: python main.py <url> --type [free|paid|admin]
"""

import argparse
import json
from typing import Optional

from config import TOTAL_CHECKS, PRICING, TIER_NAMES, DELIVERY_TIME_FREE, DELIVERY_TIME_PAID
from scraper import WebsiteScraper
from scorer import RevenueScorer
from content_evidence_signals import ContentEvidenceSignals
from reporter import ReportGenerator


def main():
    parser = argparse.ArgumentParser(description="Revenue Readiness Scorer")
    parser.add_argument("url", help="Website URL to analyze")
    parser.add_argument(
        "--type",
        choices=TIER_NAMES,
        default="free",
        help="Report type",
    )
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--admin-output", help="Admin alert output file path")

    # Optional revenue calculator inputs
    parser.add_argument("--traffic", type=int, help="Monthly visitors")
    parser.add_argument("--conversion-rate", type=float, help="Conversion rate (0.0-1.0)")
    parser.add_argument("--aov", type=float, help="Average order value ($)")
    parser.add_argument("--profit-margin", type=float, help="Profit margin (0.0-1.0)")

    args = parser.parse_args()

    calc_inputs = {}
    if args.traffic is not None:
        calc_inputs["traffic"] = args.traffic
    if args.conversion_rate is not None:
        calc_inputs["conversion_rate"] = args.conversion_rate
    if args.aov is not None:
        calc_inputs["aov"] = args.aov
    if args.profit_margin is not None:
        calc_inputs["profit_margin"] = args.profit_margin

    print(f"\nAnalyzing: {args.url}")
    print("=" * 50)

    # Step 1: Scrape
    scraper = WebsiteScraper(args.url, tier=args.type)
    data = scraper.scrape()

    if "error" in data:
        print(f"❌ Error: {data['error']}")
        return

    # Step 2: Score
    revenue_scorer = RevenueScorer(data)
    scores = revenue_scorer.calculate_scores()

    content_evidence = ContentEvidenceSignals(data)
    content_evidence.analyze()

    top_failures = revenue_scorer.get_top_failures(10)

    # Step 3: Generate report
    reporter = ReportGenerator(
        args.url,
        revenue_scorer,
        content_evidence,
        data,
        top_failures,
        calculator_inputs=calc_inputs if calc_inputs else None,
    )

    if args.type == "free":
        report = reporter.generate_free()
        print(f"\nScores: {scores}")
        print(f"   Readiness Score:    {scores['readiness_score']}/100")
        print(f"   Evidence Coverage:  {scores['evidence_coverage']}/100")
        print(f"   Confidence Score:   {scores['confidence_score']}/100")
        print(f"Severity: {report['severity']['label']}")
        print(f"\nFuture Predictions (if nothing changes):")
        for months, loss in report["future_prediction"].items():
            print(f"   {months} months: {loss}% traffic loss")
        print(f"\nHidden failures: {report['hidden_failure_count']} (unlock with paid report)")
        print(f"\nVisible failures:")
        for f in report["visible_failures"]:
            print(f"   - {f['item']} (Weight: {f['weight']})")
        print(f"\n{report['upgrade_cta']}")

        # Auto-generate admin alert
        admin_report = reporter.generate_admin()
        if args.admin_output:
            with open(args.admin_output, "w") as f:
                json.dump(admin_report, f, indent=2)
            print(f"\nAdmin alert saved to: {args.admin_output}")
        else:
            print(f"\nAdmin alert generated (not saved — use --admin-output)")

    elif args.type == "paid":
        report = reporter.generate_paid()
        print(f"\nThree-Score Readiness Report")
        print(f"   Readiness Score:    {scores['readiness_score']}/100")
        print(f"   Evidence Coverage:  {scores['evidence_coverage']}/100")
        print(f"   Confidence Score:   {scores['confidence_score']}/100")
        print(f"\nAll {TOTAL_CHECKS} Checkpoints:")
        for f in report["all_checkpoints"]:
            print(f"   - {f['item']} (Weight: {f['weight']})")
        print(f"\nRevenue Exposure (Illustrative):")
        exp = report["revenue_exposure"]
        print(f"   Label: {exp['label']}")
        print(f"   Conservative annual exposure: ${exp['conservative']['annual_exposure']:,.2f}")
        print(f"   Expected annual exposure:     ${exp['expected']['annual_exposure']:,.2f}")
        print(f"   High-exposure scenario:       ${exp['high_exposure']['annual_exposure']:,.2f}")
        print(f"\nAction Plan:")
        for task in report["action_plan"]:
            print(f"   {task['priority']}. {task['task']} (Effort: {task['effort']}, Impact: {task['impact']})")

    elif args.type == "admin":
        report = reporter.generate_admin()
        print(f"\nADMIN REPORT — LOCKED")
        print(f"URL: {report['url']}")
        print(f"Scores: {report['scores']}")
        print(f"\nThreat Analysis:")
        for t in report["threat_analysis"]:
            print(f"   - {t['checkpoint']}: {t['threat']}")
        print(f"\nHuman Gist: {report['human_gist']}")
        print(f"Research Time: {report['estimated_research_time']}")
        print(f"\nSuggested Fixes:")
        for fix in report["suggested_fixes"]:
            print(f"   - {fix['issue']}: {fix['fix']}")

    # Save output
    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\n💾 Report saved to: {args.output}")


if __name__ == "__main__":
    main()
