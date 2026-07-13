"""
Demo script — shows all 3 report types with the new three-score system,
content evidence signals, and transparent failure reporting.
"""

import os
import sys

from config import TOTAL_CHECKS, TIER_NAMES, PRICING
from scraper import WebsiteScraper
from scorer import RevenueScorer
from content_evidence_signals import ContentEvidenceSignals
from reporter import ReportGenerator


# Configurable admin unlock code. Change the default here or set env var RRS_ADMIN_CODE.
ADMIN_CODE = os.environ.get("RRS_ADMIN_CODE", "TheOne1sHere")


def run_demo():
    args = sys.argv[1:]
    test_url = args[0] if args else "https://example.com"
    admin_mode = ADMIN_CODE in args

    print(f"Demo URL: {test_url}")
    print(f"Admin mode: {'ON' if admin_mode else 'OFF'} (code: {ADMIN_CODE})")

    print("=" * 60)
    print("REVENUE READINESS SCORER — DEMO")
    print("=" * 60)

    # Scrape
    scraper = WebsiteScraper(test_url, tier="free")
    data = scraper.scrape()

    # Score
    revenue_scorer = RevenueScorer(data)
    revenue_scorer.calculate_scores()

    content_evidence = ContentEvidenceSignals(data)
    content_evidence.analyze()

    top_failures = revenue_scorer.get_top_failures(10)
    reporter = ReportGenerator(
        test_url,
        revenue_scorer,
        content_evidence,
        data,
        top_failures,
    )

    # Free report
    print("\n" + "=" * 60)
    print("FREE REPORT (what customer sees)")
    print("=" * 60)
    free = reporter.generate_free()
    print(f"Scores: {free['scores']}")
    print(f"Severity: {free['severity']['label']}")
    print(f"Pages sampled: {free['pages_sampled']}")
    print(f"Template breakdown: {free['template_breakdown']}")
    print(f"Visible failures: {len(free['visible_failures'])}")
    print(f"Failure summary (critical/high): {len(free['failure_summary'])}")
    print(f"Hidden failures: {free['hidden_failure_count']}")
    print(f"Content Evidence Signals: {len(free['content_evidence_signals'])} checks")
    for s in free['content_evidence_signals']:
        print(f"   [{s['status'].upper()}] {s['name']}: {s['detail'][:80]}...")
    print(f"CTA: {free['upgrade_cta']}")

    if admin_mode:
        # Paid report
        print("\n" + "=" * 60)
        print(f"PAID REPORT (${PRICING['paid']} — what customer gets)")
        print("=" * 60)
        paid = reporter.generate_paid()
        print(f"Scores: {paid['scores']}")
        print(f"All checkpoints: {len(paid['all_checkpoints'])}")
        print(f"Revenue exposure label: {paid['revenue_exposure']['label']}")
        print(f"  Conservative: ${paid['revenue_exposure']['conservative']['annual_exposure']:,.2f}")
        print(f"  Expected:     ${paid['revenue_exposure']['expected']['annual_exposure']:,.2f}")
        print(f"  High Exposure: ${paid['revenue_exposure']['high_exposure']['annual_exposure']:,.2f}")
        print(f"Action plan items: {len(paid['action_plan'])}")

        # Admin report
        print("\n" + "=" * 60)
        print("ADMIN REPORT (locked — owner only)")
        print("=" * 60)
        admin = reporter.generate_admin()
        print(f"Scores: {admin['scores']}")
        print(f"Threats: {len(admin['threat_analysis'])}")
        print(f"Human gist: {admin['human_gist']}")
        print(f"Research time: {admin['estimated_research_time']}")
        print(f"\nAdmin report contains complete sources and methods.")
        print("Only the owner can access this.")
    else:
        print("\n[Provide the admin code to unlock paid + admin reports]")


if __name__ == "__main__":
    run_demo()
