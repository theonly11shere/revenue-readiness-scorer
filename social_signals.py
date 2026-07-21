#!/usr/bin/env python3
"""
Social Signals Fetcher — Measures REAL public conversation about a brand.
"""

import re
from typing import Dict, Any, List, Optional
import requests

from config import COMPLAINT_KEYWORDS


class SocialSignalsFetcher:
    """Fetches and analyzes public brand mentions across social platforms."""

    def __init__(self, brand: str, domain: str):
        self.brand = brand.lower().strip()
        self.domain = domain.lower().strip()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; TrillokaBot/1.0; RevenueReadinessScorer)"
        })

    def scan(self, max_signals: int = 4, own_domain: bool = False) -> Dict[str, Any]:
        """
        Scan for social signals about the brand.
        Returns presence score and conversation data.
        """
        if own_domain or self._is_own_domain():
            return self._own_domain_result()

        try:
            posts = self._search_reddit([self.brand, self.domain], per_query=8)
        except Exception:
            posts = []

        mentions: List[str] = []
        complaints: List[str] = []

        for post in posts:
            data = post.get("data", {})
            title = data.get("title", "") or ""
            selftext = data.get("selftext", "") or ""
            subreddit = data.get("subreddit", "") or ""
            blob = (title + " " + selftext).lower()

            if not title or (self.brand not in blob and self.domain not in blob):
                continue

            entry = f'r/{subreddit}: "{title[:80]}..."'
            mentions.append(entry)

            if any(kw in blob for kw in COMPLAINT_KEYWORDS):
                complaints.append(entry)

        total = len(mentions)
        positive = [m for m in mentions if m not in complaints]

        # Calculate presence score (0-100)
        if total == 0:
            presence_score = 0
            verdict = "invisible"
            verdict_label = "Zero online presence — no public conversation found"
        elif total <= 3:
            presence_score = 15
            verdict = "quiet"
            verdict_label = "Barely discussed — brand is a whisper online"
        elif total <= 10:
            presence_score = 40
            verdict = "emerging"
            verdict_label = "Some mentions — building awareness but not dominant"
        elif total <= 25:
            presence_score = 65
            verdict = "discussed"
            verdict_label = "Active conversation — people are talking about this brand"
        else:
            presence_score = 85
            verdict = "loud"
            verdict_label = "Strong presence — brand is part of the conversation"

        # Adjust for complaints
        complaint_ratio = len(complaints) / max(total, 1)
        if complaint_ratio > 0.5 and total > 3:
            presence_score = max(0, presence_score - 30)
            verdict_label += " (but mostly negative)"

        signals = (complaints + positive)[:max_signals]

        return {
            "presence_score": presence_score,
            "mentions_found": total,
            "complaints_found": len(complaints),
            "complaint_ratio": round(complaint_ratio, 2),
            "verdict": verdict,
            "verdict_label": verdict_label,
            "signals": signals,
            "positive_examples": positive[:3],
            "negative_examples": complaints[:3],
        }

    def _is_own_domain(self) -> bool:
        """Check if this is Trilloka's own domain."""
        own_domains = {"trilloka.com", "www.trilloka.com", "trilloka"}
        return self.domain in own_domains or self.brand in own_domains

    def _own_domain_result(self) -> Dict[str, Any]:
        """Special result for Trilloka itself — with attitude."""
        return {
            "presence_score": 100,
            "mentions_found": 999,
            "complaints_found": 0,
            "complaint_ratio": 0.0,
            "verdict": "architect",
            "verdict_label": "Nice try. You already know who built this.",
            "signals": [
                "We're the ones writing the rules everyone else is trying to follow.",
                "While others chase trends, we build the infrastructure.",
                "Our presence isn't measured in mentions — it's measured in who copies us next quarter."
            ],
            "positive_examples": [
                "The only Revenue Readiness System that actually reads between the lines.",
                "Built by people who got tired of generic SEO reports.",
                "If you're seeing this, you already found the best tool in the room."
            ],
            "negative_examples": [],
            "is_own_domain": True,
            "attitude": "supreme"
        }

    def _search_reddit(self, queries: List[str], per_query: int = 5) -> List[Dict[str, Any]]:
        """Search Reddit for brand mentions."""
        results: List[Dict[str, Any]] = []
        for query in queries:
            try:
                response = self.session.get(
                    "https://www.reddit.com/search.json",
                    params={"q": query, "limit": per_query, "sort": "new"},
                    timeout=5,
                )
                if response.status_code == 200:
                    results.extend(response.json().get("data", {}).get("children", []))
            except Exception:
                continue
        return results
