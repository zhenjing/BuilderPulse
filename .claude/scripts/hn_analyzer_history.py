#!/usr/bin/env python3
"""
HackerNews Daily Analyzer (History Mode) — fetches HN stories and comments
for a specific date via Algolia API, scores for complaint density,
and outputs structured JSON.
"""

import json
import urllib.request
import urllib.parse
import re
import sys
import io
import time
from datetime import datetime, timedelta
from html.parser import HTMLParser

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, data):
        self.text.append(data)

    def handle_entityref(self, name):
        self.text.append(f"&{name};")


def strip_html(html_str):
    if not html_str:
        return ""
    s = MLStripper()
    s.feed(html_str)
    result = "".join(s.text)
    result = result.replace("&#x27;", "'").replace("&quot;", '"')
    result = result.replace("&amp;", "&").replace("&lt;", "<")
    result = result.replace("&gt;", ">").replace("&#x2F;", "/")
    result = re.sub(r"&\w+;", "", result)
    return result


def fetch_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "HNdaily/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


NEGATIVE_WORDS = [
    "broke", "shut down", "outage", "kill", "ban", "block",
    "problem", "never", "loophole", "bitter", "warning",
    "propaganda", "broken", "fail", "stop", "against",
    "closing", "danger", "hate", "worst", "terrible",
    "forced", "forcing", "blunder", "attack", "exploit",
]

ENTITY_NAMES = [
    "google", "meta", "amazon", "aws", "microsoft", "apple",
    "eu", "us government", "linux foundation", "openai",
    "cloudflare", "facebook", "instagram",
]


def complaint_score(story):
    title = (story.get("title") or "").lower()
    score = 0
    descendants = story.get("descendants", 0)

    if descendants > 100:
        score += 4
    elif descendants > 50:
        score += 3
    elif descendants > 25:
        score += 2
    elif descendants > 10:
        score += 1

    for word in NEGATIVE_WORDS:
        if word in title:
            score += 2
            break

    for entity in ENTITY_NAMES:
        if entity in title:
            score += 1
            break

    return score


def fetch_stories_by_date(date_str, limit=30):
    """Fetch top HN stories for a given date using Algolia API."""
    # Parse date and create range for that day (Unix timestamps)
    target_date = datetime.strptime(date_str, "%Y-%m-%d")
    start_ts = int(target_date.timestamp())
    end_ts = int((target_date + timedelta(days=1)).timestamp())

    # Search Algolia for stories on that date, sorted by points
    url = (
        f"https://hn.algolia.com/api/v1/search?"
        f"tags=story&"
        f"numericFilters=created_at_i>={start_ts},created_at_i<{end_ts}&"
        f"hitsPerPage={limit}"
    )
    print(f"  Fetching: {url}", file=sys.stderr)
    data = fetch_json(url)
    hits = data.get("hits", [])
    print(f"  Found {len(hits)} stories from {date_str}", file=sys.stderr)

    stories = []
    for h in hits:
        story = {
            "id": int(h.get("objectID")),
            "title": h.get("title"),
            "url": h.get("url", f"https://news.ycombinator.com/item?id={h.get('objectID')}"),
            "by": h.get("author"),
            "score": h.get("points", 0),
            "descendants": h.get("num_comments", 0),
        }
        stories.append(story)
    return stories


def fetch_comments(story, max_comments=25):
    """Fetch comments for a story via Firebase API."""
    try:
        item = fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{story['id']}.json")
        kids = item.get("kids", [])
    except Exception:
        return []

    comments = []
    for cid in kids[:max_comments]:
        try:
            c = fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{cid}.json")
            if c and not c.get("dead") and not c.get("deleted") and c.get("text"):
                comments.append({
                    "id": c.get("id"),
                    "by": c.get("by", "?"),
                    "text": strip_html(c.get("text", ""))[:500],
                })
        except Exception:
            pass
    return comments


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    output_path = sys.argv[2] if len(sys.argv) > 2 else "hn_data.json"

    print(f"[HNdaily-history] Fetching stories for {date_str}...", file=sys.stderr)
    stories = fetch_stories_by_date(date_str, 30)

    if not stories:
        print(f"[HNdaily-history] No stories found for {date_str}", file=sys.stderr)
        sys.exit(1)

    print(f"[HNdaily-history] Fetched {len(stories)} stories. Scoring...", file=sys.stderr)

    for s in stories:
        s["_complaint_score"] = complaint_score(s)
    stories_sorted = sorted(stories, key=lambda s: s["_complaint_score"], reverse=True)
    candidates = stories_sorted[:10]

    print(f"[HNdaily-history] Fetching comments for top {len(candidates)} candidates...", file=sys.stderr)

    result = {
        "date": date_str,
        "total_stories": len(stories),
        "candidates": [],
    }

    for story in candidates:
        print(f"  -> [{story['_complaint_score']}] {story.get('title', 'N/A')[:80]}", file=sys.stderr)
        comments = fetch_comments(story)
        result["candidates"].append({
            "id": story.get("id"),
            "title": story.get("title"),
            "url": story.get("url"),
            "by": story.get("by"),
            "score": story.get("score", 0),
            "descendants": story.get("descendants", 0),
            "complaint_score": story["_complaint_score"],
            "comments": comments,
        })
        time.sleep(0.1)  # Small delay to be polite

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[HNdaily-history] Data saved to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
