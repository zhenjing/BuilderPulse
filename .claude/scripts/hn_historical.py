#!/usr/bin/env python3
"""
HackerNews Historical Analyzer — fetches HN stories from a specific date via Algolia API,
scores them for complaint density, and outputs structured JSON for the daily report.
Usage: python hn_historical.py YYYY-MM-DD [output.json]
"""

import json
import urllib.request
import urllib.parse
import re
import sys
import io
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

EST = timezone(timedelta(hours=-5))


class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, data):
        self.text.append(data)


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


def fetch_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "HNdaily/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


NEGATIVE_WORDS = [
    "broke", "shut down", "outage", "kill", "ban", "block",
    "problem", "never", "loophole", "bitter", "warning",
    "propaganda", "broken", "fail", "stop", "against",
    "closing", "danger", "hate", "worst", "terrible",
    "forced", "forcing", "blunder", "attack", "exploit",
    "spam", "scam", "abuse", "vulnerability", "leak",
    "layoff", "cancel", "remove", "drop", "suspend",
    "backdoor", "hack", "breach", "censor", "ban",
    "monopoly", "antitrust", "lawsuit",
]

ENTITY_NAMES = [
    "google", "meta", "amazon", "aws", "microsoft", "apple",
    "eu", "us government", "linux foundation", "openai",
    "cloudflare", "facebook", "instagram", "amd", "intel",
    "nvidia", "anthropic", "deepseek",
]


def complaint_score(story):
    title = (story.get("title") or "").lower()
    score = 0
    descendants = story.get("descendants", 0) or story.get("num_comments", 0)

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


def fetch_item(item_id):
    try:
        return fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json")
    except Exception:
        return None


def fetch_comments(story, max_comments=25):
    kids = story.get("kids", [])
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


def fetch_stories_by_date(date_str):
    """Fetch top HN stories from a specific date using Algolia API."""
    # Parse the target date in EST
    target_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=EST)
    start_ts = int(target_date.timestamp())
    end_ts = int((target_date + timedelta(days=1)).timestamp())

    print(f"[HNhistorical] Fetching stories for {date_str} (EST)...", file=sys.stderr)
    print(f"  Time range: {start_ts} - {end_ts} (Unix, EST)", file=sys.stderr)

    all_stories = []
    page = 0
    while True:
        url = (
            f"https://hn.algolia.com/api/v1/search_by_date?"
            f"tags=story&numericFilters=created_at_i>{start_ts},created_at_i<{end_ts},points>20"
            f"&hitsPerPage=200&page={page}"
        )
        try:
            data = fetch_json(url)
            hits = data.get("hits", [])
            if not hits:
                break
            all_stories.extend(hits)
            page += 1
            if page >= 5:
                break
        except Exception as e:
            print(f"  WARN: Algolia fetch error: {e}", file=sys.stderr)
            break

    print(f"  Found {len(all_stories)} stories with points>20", file=sys.stderr)

    # Deduplicate by story ID
    seen = set()
    unique = []
    for s in all_stories:
        sid = s.get("objectID")
        if sid not in seen:
            seen.add(sid)
            unique.append(s)

    # Sort by points descending, take top 30
    unique.sort(key=lambda s: s.get("points", 0) or s.get("score", 0), reverse=True)
    return unique[:30]


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} YYYY-MM-DD [output.json]", file=sys.stderr)
        sys.exit(1)

    date_str = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else f"hn_data_{date_str}.json"

    # Parse & validate date
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        print(f"ERROR: Invalid date format. Use YYYY-MM-DD.", file=sys.stderr)
        sys.exit(1)

    stories = fetch_stories_by_date(date_str)

    print(f"[HNhistorical] Fetched {len(stories)} stories. Scoring...", file=sys.stderr)

    # Enrich with full story data from Firebase for comment kids
    enriched = []
    for s in stories:
        sid = s.get("objectID")
        full = fetch_item(sid)
        if full:
            enriched.append({
                **full,
                "_algolia_points": s.get("points", 0),
                "_algolia_num_comments": s.get("num_comments", 0),
            })
        else:
            enriched.append({
                "id": sid,
                "title": s.get("title"),
                "url": s.get("url", f"https://news.ycombinator.com/item?id={sid}"),
                "by": s.get("author"),
                "score": s.get("points", 0),
                "descendants": s.get("num_comments", 0),
                "_complaint_score": 0,
            })

    # Score
    for s in enriched:
        s["_complaint_score"] = complaint_score(s)

    enriched.sort(key=lambda s: s["_complaint_score"], reverse=True)
    candidates = enriched[:10]

    print(f"[HNhistorical] Fetching comments for top {len(candidates)} candidates...", file=sys.stderr)

    result = {
        "date": date_str,
        "total_stories": len(stories),
        "candidates": [],
    }

    for story in candidates:
        title = story.get("title", "N/A")[:80]
        cs = story["_complaint_score"]
        print(f"  -> [{cs}] {title}", file=sys.stderr)
        comments = fetch_comments(story)
        result["candidates"].append({
            "id": story.get("id", story.get("objectID")),
            "title": story.get("title"),
            "url": story.get("url", f"https://news.ycombinator.com/item?id={story.get('id', story.get('objectID'))}"),
            "by": story.get("by"),
            "score": story.get("score", 0),
            "descendants": story.get("descendants", 0),
            "complaint_score": story["_complaint_score"],
            "comments": comments,
        })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[HNhistorical] Data saved to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
