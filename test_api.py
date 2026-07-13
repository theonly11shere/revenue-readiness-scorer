"""
Simple test script for the local RRS API.
Run with: python test_api.py [url]
"""

import json
import sys
import urllib.request

URL = "http://127.0.0.1:8000/api/v1/score/free"
TARGET = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"

BODY = json.dumps({"url": TARGET}).encode("utf-8")

req = urllib.request.Request(
    URL,
    data=BODY,
    headers={"Content-Type": "application/json"},
    method="POST",
)

try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode("utf-8"))
        print("API is working!")
        print("-" * 50)
        print(f"Type: {data['type']}")
        print(f"URL analyzed: {data['url']}")
        print(f"Scores: {data['scores']}")
        print(f"Severity: {data['severity']['label']}")
        print(f"Pages sampled: {data['pages_sampled']}")
        print(f"Hidden failures: {data['hidden_failure_count']}")
        print(f"Upgrade CTA: {data['upgrade_cta']}")
        print("-" * 50)
        print("Content Evidence Signals:")
        for signal in data.get("content_evidence_signals", []):
            print(f"  [{signal['status'].upper()}] {signal['name']}")
except Exception as e:
    print(f"Error: {e}")
    print("Make sure the server is running with: python start.py")
