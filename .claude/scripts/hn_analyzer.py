#!/usr/bin/env python3
"""
HackerNews Daily Analyzer — fetches HN front page stories and comments,
scores them for complaint density, and outputs structured JSON for
Claude to analyze and write the daily report.
"""

import json
import urllib.request
import urllib.parse
import re
import sys
import io
from datetime import datetime, timedelta
from html.parser import HTMLParser

# Force UTF-8 output on Windows
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
    # Decode HTML entities
    result = result.replace("&#x27;", "'").replace("&quot;", '"')
    result = result.replace("&amp;", "&").replace("&lt;", "<")
    result = result.replace("&gt;", ">").replace("&#x2F;", "/")
    result = re.sub(r"&\w+;", "", result)
    return result


def fetch_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "HNdaily/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# Complaint keywords for scoring
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

# Title-based product opportunity signals
TITLE_OPPORTUNITY_SIGNALS = {
    "show hn": 3, "launch hn": 3, "alternative to": 3,
    "open source": 2, "open-source": 2, "self-hosted": 2,
    "introducing": 2, "announcing": 2, "github.com": 2,
    "beta": 1, "free": 1, "a new": 1,
    "replacement for": 2, "competitor to": 2,
}

# Tiered purchase-intent & product-gap signals in comments
PRODUCT_SIGNALS = {
    "strong": [
        "i'd pay for", "i would pay for", "would happily pay",
        "shut up and take my money", "where can i buy",
        "take my money", "i want this", "how do i get this",
    ],
    "gap": [
        "i wish there was", "i wish there were", "i wish someone would",
        "why doesn't", "why isn't there", "why has nobody",
        "nobody is doing", "there's a gap", "underserved",
        "someone should build", "someone needs to build",
        "i'm surprised nobody", "i'm surprised no one",
        "should exist", "missed opportunity",
    ],
    "weak": [
        "any alternatives", "is there a service", "looking for a",
        "too expensive", "no middle tier", "no free tier",
        "workaround", "i ended up using", "i built a",
        "if only", "drop-in replacement", "self-hosted alternative",
        "i want to use", "i need a", "i just want",
        "shut down", "discontinued", "no longer maintained",
        "not worth the price", "overpriced", "price hike",
    ],
}
SIGNAL_WEIGHTS = {"strong": 3, "gap": 2, "weak": 1}

# AI-related keyword detection in titles
AI_KEYWORDS = [
    "ai ", "llm", "gpt", "claude", "model", "agent",
    "openai", "anthropic", "copilot", "codex", "deepseek",
    "inference", "benchmark", "token", "training", "fine-tun",
    "prompt", "generative", "coder", "chatgpt", "gemini",
    "neural", "transformer", "coding agent", "local ai",
    "frontier", "llama",
]


def is_ai_post(title):
    """Check if a post title is AI-related."""
    t = title.lower()
    for kw in AI_KEYWORDS:
        if kw in t:
            return True
    return False


def complaint_score(story):
    title = (story.get("title") or "").lower()
    score = 0
    descendants = story.get("descendants", 0)

    if descendants > 500:
        score += 7
    elif descendants > 400:
        score += 5       
    elif descendants > 200:
        score += 3
    elif descendants > 50:
        score += 1

    for word in NEGATIVE_WORDS:
        if word in title:
            score += 2
            break

    for entity in ENTITY_NAMES:
        if entity in title:
            score -= 1
            break

    return score


def title_opportunity_score(story):
    """Score product opportunity from title and URL alone."""
    title = (story.get("title") or "").lower()
    url = (story.get("url") or "").lower()
    combined = title + " " + url
    score = 0
    for signal, weight in TITLE_OPPORTUNITY_SIGNALS.items():
        if signal in combined:
            score += weight
    return score


def product_opportunity_score(story):
    """Tiered per-comment signal scan with dedup. Strongest signal wins per comment."""
    comment_texts = story.get("_comment_texts", [])
    if not comment_texts:
        return 0
    score = 0
    for text in comment_texts:
        t = text.lower()
        best = 0
        for tier in ("strong", "gap", "weak"):
            for phrase in PRODUCT_SIGNALS[tier]:
                if phrase in t:
                    best = max(best, SIGNAL_WEIGHTS[tier])
                    break
            if best >= SIGNAL_WEIGHTS[tier]:
                break  # already found at this tier, don't scan lower
        score += best
    return score


def fetch_stories(limit=80):
    ids = fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json")
    stories = []
    for sid in ids[:limit]:
        try:
            item = fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
            if item and item.get("type") == "story":
                stories.append(item)
        except Exception as e:
            print(f"  WARN: failed to fetch story {sid}: {e}", file=sys.stderr)
    return stories


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


def main():
    print("[HNdaily] Fetching top stories...", file=sys.stderr)
    stories = fetch_stories(80)
    print(f"[HNdaily] Fetched {len(stories)} stories. Scoring...", file=sys.stderr)

    # Score all stories on both dimensions
    for s in stories:
        s["_complaint_score"] = complaint_score(s)
        s["_title_opp_score"] = title_opportunity_score(s)

    # Scan AI-related posts from the full 80
    ai_posts = []
    for s in stories:
        title = s.get("title") or ""
        if is_ai_post(title):
            ai_posts.append({
                "id": s.get("id"),
                "title": title,
                "url": s.get("url", f"https://news.ycombinator.com/item?id={s.get('id')}"),
                "score": s.get("score", 0),
                "descendants": s.get("descendants", 0),
            })
    print(f"[HNdaily] AI-related posts: {len(ai_posts)}", file=sys.stderr)

    # Dual pipeline: independent Top 10 per dimension, then union
    complaint_top = sorted(stories, key=lambda s: s["_complaint_score"], reverse=True)[:10]
    opp_top = sorted(stories, key=lambda s: s["_title_opp_score"], reverse=True)[:10]

    # Union by story id, preserving origin
    candidates_map = {}
    for s in complaint_top:
        candidates_map[s["id"]] = {"story": s, "from": "complaint"}
    for s in opp_top:
        if s["id"] in candidates_map:
            candidates_map[s["id"]]["from"] = "both"
        else:
            candidates_map[s["id"]] = {"story": s, "from": "opportunity"}

    print(f"[HNdaily] Dual pipeline: {len(complaint_top)} complaint + {len(opp_top)} opportunity = {len(candidates_map)} unique candidates", file=sys.stderr)
    print(f"[HNdaily] Fetching comments for {len(candidates_map)} candidates...", file=sys.stderr)

    result = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_stories": len(stories),
        "ai_posts": ai_posts,
        "candidates": [],
    }

    for entry in candidates_map.values():
        story = entry["story"]
        comments = fetch_comments(story)
        story["_comment_texts"] = [c["text"] for c in comments]
        comment_opp = product_opportunity_score(story)
        total_opp = story["_title_opp_score"] + comment_opp
        pipe = entry["from"]

        marker = ""
        if pipe == "both":
            marker = " [C+O]"
        elif pipe == "opportunity":
            marker = " [O]"
        else:
            marker = " [C]"

        print(f"  {marker} [{story['_complaint_score']}|{total_opp}] {story.get('title', 'N/A')[:70]}", file=sys.stderr)

        result["candidates"].append({
            "id": story.get("id"),
            "title": story.get("title"),
            "url": story.get("url", f"https://news.ycombinator.com/item?id={story.get('id')}"),
            "by": story.get("by"),
            "score": story.get("score", 0),
            "descendants": story.get("descendants", 0),
            "complaint_score": story["_complaint_score"],
            "opportunity_score": total_opp,
            "pipeline": pipe,
            "comments": comments,
        })

    # Enrich AI posts not already in candidates: fetch comments for high-discussion ones
    enriched_ai = []
    for ap in ai_posts:
        if ap["id"] in candidates_map or ap["descendants"] < 50:
            enriched_ai.append(ap)
            continue
        # Fetch comments for this AI post
        story_obj = next((s for s in stories if s.get("id") == ap["id"]), None)
        if story_obj:
            ai_comments = fetch_comments(story_obj)
            ap["comments"] = ai_comments
            print(f"  [AI] [{ap['score']}pts|{ap['descendants']}cmt] {ap['title'][:70]}", file=sys.stderr)
        enriched_ai.append(ap)
    result["ai_posts"] = enriched_ai

    output_path = sys.argv[1] if len(sys.argv) > 1 else "hn_data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[HNdaily] Data saved to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
