#!/usr/bin/env python3
"""Social Signals Fetcher — Multi-platform brand mention scanner."""
import re
from typing import Dict, Any, List
import requests
from bs4 import BeautifulSoup
from config import COMPLAINT_KEYWORDS

class SocialSignalsFetcher:
    def __init__(self, brand: str, domain: str):
        self.brand = brand.lower().strip()
        self.domain = domain.lower().strip()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; TrillokaBot/1.0; RevenueReadinessScorer)"})

    def scan(self, max_signals: int = 4, own_domain: bool = False) -> Dict[str, Any]:
        if own_domain or self._is_own_domain():
            return self._own_domain_result()
        try:
            reddit_posts = self._search_reddit([self.brand, self.domain], per_query=8)
        except Exception:
            reddit_posts = []
        try:
            trustpilot = self._search_trustpilot(self.domain)
        except Exception:
            trustpilot = []
        try:
            yelp = self._search_yelp(self.brand)
        except Exception:
            yelp = []
        try:
            google = self._search_google_reviews(self.domain)
        except Exception:
            google = []

        mentions: List[str] = []
        complaints: List[str] = []
        all_sources = reddit_posts + trustpilot + yelp + google
        for entry in all_sources:
            title = entry.get("title", "")
            text = entry.get("text", "")
            source = entry.get("source", "")
            blob = (title + " " + text).lower()
            if not title:
                continue
            entry_str = f'{source}: "{title[:80]}..."'
            mentions.append(entry_str)
            if any(kw in blob for kw in COMPLAINT_KEYWORDS):
                complaints.append(entry_str)

        total = len(mentions)
        positive = [m for m in mentions if m not in complaints]

        if total == 0:
            presence_score = 0
            verdict = "invisible"
            verdict_label = "Zero online presence — no public conversation found"
        elif total <= 5:
            presence_score = 20
            verdict = "quiet"
            verdict_label = "Barely discussed — brand is a whisper online"
        elif total <= 15:
            presence_score = 50
            verdict = "emerging"
            verdict_label = "Some mentions — building awareness but not dominant"
        elif total <= 30:
            presence_score = 75
            verdict = "discussed"
            verdict_label = "Active conversation — people are talking about this brand"
        else:
            presence_score = 90
            verdict = "loud"
            verdict_label = "Strong presence — brand is part of the conversation"

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
            "sources": {
                "reddit": len(reddit_posts),
                "trustpilot": len(trustpilot),
                "yelp": len(yelp),
                "google": len(google),
            },
        }

    def _is_own_domain(self) -> bool:
        own_domains = {"trilloka.com", "www.trilloka.com", "trilloka"}
        return self.domain in own_domains or self.brand in own_domains

    def _own_domain_result(self) -> Dict[str, Any]:
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
            "sources": {"reddit": 0, "trustpilot": 0, "yelp": 0, "google": 0},
        }

    def _search_reddit(self, queries: List[str], per_query: int = 5) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for query in queries:
            try:
                response = self.session.get("https://www.reddit.com/search.json", params={"q": query, "limit": per_query, "sort": "new"}, timeout=5)
                if response.status_code == 200:
                    for child in response.json().get("data", {}).get("children", []):
                        d = child.get("data", {})
                        results.append({"title": d.get("title", ""), "text": d.get("selftext", ""), "source": f"Reddit r/{d.get('subreddit', '')}"})
            except Exception:
                continue
        return results

    def _search_trustpilot(self, domain: str) -> List[Dict[str, Any]]:
        try:
            resp = self.session.get(f"https://www.trustpilot.com/review/{domain}", timeout=8)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            reviews = soup.find_all("p", {"data-service-review-text-typography": True})
            return [{"title": r.get_text()[:100], "text": r.get_text(), "source": "Trustpilot"} for r in reviews[:5]]
        except Exception:
            return []

    def _search_yelp(self, brand: str) -> List[Dict[str, Any]]:
        try:
            resp = self.session.get(f"https://www.yelp.com/search?find_desc={brand}", timeout=8)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            reviews = soup.find_all("p", class_=re.compile(r"comment"))
            return [{"title": r.get_text()[:100], "text": r.get_text(), "source": "Yelp"} for r in reviews[:3]]
        except Exception:
            return []

    def _search_google_reviews(self, domain: str) -> List[Dict[str, Any]]:
        try:
            resp = self.session.get(f"https://www.google.com/search?q={domain}+reviews", timeout=8)
            soup = BeautifulSoup(resp.text, "html.parser")
            snippets = soup.find_all("span", class_=re.compile(r"review"))
            return [{"title": s.get_text()[:100], "text": s.get_text(), "source": "Google"} for s in snippets[:3]]
        except Exception:
            return []
