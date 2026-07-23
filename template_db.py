#!/usr/bin/env python3
"""Template Database — seed script for known template signatures."""
import json
import os

TEMPLATES = [
    {"name": "WordPress Astra", "platform": "wordpress", "signatures": ["ast-container", "ast-row", "ast-col", "astra-"], "popularity_score": 1200000},
    {"name": "WordPress Elementor", "platform": "wordpress", "signatures": ["elementor-", "elementor/", "elementor-section"], "popularity_score": 5000000},
    {"name": "WordPress Divi", "platform": "wordpress", "signatures": ["et_pb_", "divi-", "et_pb_section"], "popularity_score": 800000},
    {"name": "Shopify Dawn", "platform": "shopify", "signatures": ["shopify-section", "shopify-dawn", "section-header"], "popularity_score": 2000000},
    {"name": "Wix", "platform": "wix", "signatures": ["wix-", "static.wixstatic.com"], "popularity_score": 3000000},
    {"name": "Squarespace", "platform": "squarespace", "signatures": ["squarespace-", "static1.squarespace.com"], "popularity_score": 1500000},
    {"name": "Bootstrap", "platform": "framework", "signatures": ["bootstrap", "container-fluid", "row", "col-"], "popularity_score": 10000000},
    {"name": "Tailwind", "platform": "framework", "signatures": ["tailwind", "bg-", "text-", "flex", "grid-cols-"], "popularity_score": 8000000},
]

def seed_templates():
    db_file = os.path.join(os.path.dirname(__file__), "templates.jsonl")
    with open(db_file, "w", encoding="utf-8") as f:
        for t in TEMPLATES:
            f.write(json.dumps(t) + "\n")
    print(f"Seeded {len(TEMPLATES)} templates to {db_file}")

if __name__ == "__main__":
    seed_templates()
