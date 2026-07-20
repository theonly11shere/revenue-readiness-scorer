"""
Social Signals Fetcher — presence meter.

Measures REAL public conversation about a brand on Reddit: how many posts
actually mention the business, and whether any of them are complaints.
Returns honest counts and verdicts only — never fabricates signals.
"""

import requests
from typing import Any, Dict, List


class SocialSignalsFetcher:
    COMPLAINT_KEYWORDS = (
        "broken", "not working", "doesn't work", "slow", "scam", "ripoff",
        "terrible", "worst", "avoid", "awful", "useless", "never again",
        "down", "error", "complaint", "bad experience", "unresponsive",
    )

    def __init__(self, brand: str, domain: str):
        self.brand = brand.lower()
        self.domain = domain.lower()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; TrillokaBot/1.0)"})

    def scan(self, max_signals: int = 4, own: bool = False) -> Dict[str, Any]:
        """Search for public mentions of the brand/domain and grade presence.

        invisible = zero public mentions found (the common SMB case)
        quiet     = a handful of mentions
        discussed = people are actually talking about the business
        """
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
            # Only count posts that actually mention this brand/domain —
            # keyword-only matches are usually about something else entirely.
            if not title or (self.brand not in blob and self.domain not in blob):
                continue
            entry = f'Reddit r/{subreddit}: "{title[:80]}..."'
            mentions.append(entry)
            if any(kw in blob for kw in self.COMPLAINT_KEYWORDS):
                complaints.append(entry)

        total = len(mentions)
        positive = [m for m in mentions if m not in complaints]

        # Self guard-rail: never roast our own domain with its own radar.
        if own:
            return {
                "mentions_found": total,
                "complaints_found": len(complaints),
                "verdict": "own",
                "verdict_label": "Home turf — the Architect's own domain",
                "signals": [],
                "positive_examples": [],
                "negative_examples": [],
            }

        if total == 0:
            verdict, verdict_label = "invisible", "No public conversation found — invisible online"
        elif total <= 3:
            verdict, verdict_label = "quiet", "Barely discussed online"
        else:
            verdict, verdict_label = "discussed", "People are talking about this business"

        # Complaints first (highest signal), then plain mentions. All real.
        signals = (complaints + positive)[:max_signals]

        return {
            "mentions_found": total,
            "complaints_found": len(complaints),
            "verdict": verdict,
            "verdict_label": verdict_label,
            "signals": signals,
            "positive_examples": positive[:3],
            "negative_examples": complaints[:3],
        }

    def _search_reddit(self, queries: List[str], per_query: int = 5) -> List[Dict[str, Any]]:
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
