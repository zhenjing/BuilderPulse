#!/usr/bin/env python3
"""
BuilderPulse Data Fetcher — pulls from 7+ sources (HN, GitHub, HuggingFace,
Reddit, Lobsters, DEV Community, Product Hunt RSS) and optionally Google Trends,
normalizes all signals into structured JSON for Claude to generate the
BuilderPulse Daily report.

All sources accessible without authentication and functional behind GFW.
"""

import json
import sys
import io
import time
import urllib.request
import urllib.parse
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Google Trends (optional — fails gracefully if blocked)
try:
    from pytrends.request import TrendReq
    HAS_PYTRENDS = True
except ImportError:
    HAS_PYTRENDS = False

# ── Google Trends Seed Keywords ──────────────────────────────────────────────

GOOGLE_TRENDS_SEEDS = [
    "ai agent", "claude code", "ai coding", "autonomous ai agent",
    "open source ai", "self hosted", "local first", "passkey",
    "browser automation", "mcp server", "api development", "micro saas",
]

# ── HTML Stripper ──────────────────────────────────────────────────────────

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


# ── HTTP Helper ────────────────────────────────────────────────────────────

def fetch_json(url, timeout=30):
    """Fetch JSON from URL with retries and User-Agent."""
    req = urllib.request.Request(url, headers={"User-Agent": "BuilderPulse/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def fetch_url(url, timeout=30, headers=None):
    """Fetch raw content from URL."""
    default_headers = {"User-Agent": "BuilderPulse/1.0"}
    if headers:
        default_headers.update(headers)
    req = urllib.request.Request(url, headers=default_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ── Relevance Keywords ─────────────────────────────────────────────────────

BUILDER_KEYWORDS = [
    "launch", "revenue", "pricing", "mrr", "shutdown", "migration",
    "agent", "mcp", "self-host", "self host", "cost", "privacy",
    "open source", "open-source", "tool calling", "tool-calling",
    "local model", "small model", "browser automation", "billing",
    "payment", "receipt", "ownership", "data residency", "sovereignty",
    "api", "sdk", "framework", "platform", "nocode", "no-code",
    "microsaas", "micro-saas", "indie", "solo", "founder",
    "claude code", "codex", "cursor", "copilot", "ai coding",
    "token cost", "usage billing", "vendor lock", "lock-in",
    "telemetry", "tracking", "gdpr", "compliance", "audit",
]


def extract_relevance_tags(text):
    """Score and tag text for builder relevance."""
    if not text:
        return []
    text_lower = text.lower()
    tags = []
    for kw in BUILDER_KEYWORDS:
        if kw in text_lower:
            tags.append(kw.replace(" ", "-"))
    return list(set(tags))


def compute_signal_strength(item_type, item):
    """Compute 0-10 signal strength for any normalized item."""
    score = 0

    # Discussion volume
    volume = 0
    if "descendants" in item:
        volume = item.get("descendants", 0)
    elif "num_comments" in item:
        volume = item.get("num_comments", 0)
    elif "comments_count" in item:
        volume = item.get("comments_count", 0)
    elif "stargazers_count" in item:
        volume = item.get("stargazers_count", 0) // 100
    elif "score" in item:
        volume = item.get("score", 0)

    if volume > 400:
        score += 4
    elif volume > 100:
        score += 3
    elif volume > 30:
        score += 2
    elif volume > 10:
        score += 1

    # Keyword relevance
    text = ""
    for f in ["title", "description", "tagline", "selftext"]:
        if item.get(f):
            text += " " + str(item[f])
    tags = extract_relevance_tags(text)
    if len(tags) >= 4:
        score += 3
    elif len(tags) >= 2:
        score += 2
    elif len(tags) >= 1:
        score += 1

    return min(score, 10)


# ── Hacker News Fetchers ───────────────────────────────────────────────────

def fetch_hn_top_stories(limit=30):
    """Fetch HN top stories with comment samples."""
    ids = fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json")
    stories = []
    comments_by_story = {}

    for sid in ids[:limit]:
        try:
            item = fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
            if item and item.get("type") == "story":
                story = {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "url": item.get("url", f"https://news.ycombinator.com/item?id={item.get('id')}"),
                    "by": item.get("by", "?"),
                    "score": item.get("score", 0),
                    "descendants": item.get("descendants", 0),
                    "time": item.get("time", 0),
                    "type": item.get("type"),
                }
                story["_signal_strength"] = compute_signal_strength("hn_story", story)
                story["_relevance_tags"] = extract_relevance_tags(
                    story.get("title", "") + " " + story.get("url", "")
                )
                stories.append(story)

                # Fetch comment samples for top stories (high comment count)
                if item.get("descendants", 0) > 70 and item.get("kids"):
                    kid_ids = item["kids"][:25]
                    story_comments = []
                    for cid in kid_ids:
                        try:
                            c = fetch_json(
                                f"https://hacker-news.firebaseio.com/v0/item/{cid}.json"
                            )
                            if c and not c.get("dead") and not c.get("deleted") and c.get("text"):
                                story_comments.append({
                                    "id": c.get("id"),
                                    "by": c.get("by", "?"),
                                    "text": strip_html(c.get("text", ""))[:400],
                                })
                        except Exception:
                            pass
                    if story_comments:
                        comments_by_story[str(item["id"])] = story_comments
        except Exception as e:
            print(f"  WARN: failed story {sid}: {e}", file=sys.stderr)

    return stories, comments_by_story


def fetch_hn_show_stories(limit=15):
    """Fetch HN Show HN stories via Algolia API."""
    try:
        url = (
            f"https://hn.algolia.com/api/v1/search?"
            f"tags=show_hn&hitsPerPage={limit}&numericFilters=points>3"
        )
        data = fetch_json(url)
        hits = data.get("hits", [])
        stories = []
        for h in hits:
            story = {
                "id": h.get("objectID"),
                "title": h.get("title", ""),
                "url": h.get("url", f"https://news.ycombinator.com/item?id={h.get('objectID')}"),
                "by": h.get("author", "?"),
                "points": h.get("points", 0),
                "num_comments": h.get("num_comments", 0),
                "created_at": h.get("created_at", ""),
            }
            story["_signal_strength"] = compute_signal_strength("hn_show", story)
            story["_relevance_tags"] = extract_relevance_tags(story.get("title", ""))
            stories.append(story)
        return stories
    except Exception as e:
        print(f"  WARN: HN Show stories failed: {e}", file=sys.stderr)
        return []


# ── Star Fake Score ────────────────────────────────────────────────────────

SPAM_KEYWORDS = {
    "casino", "bonus", "crack", "cheat", "trading-bot", "crypto-bot",
    "stake", "bypass", "exploit", "cracked", "keygen", "no-deposit",
    "free-spins", "poker-bot", "hack", "wallhack", "aimbot",
    "airdrop", "token-launch", "presale",
}

SPAM_TOPICS = {
    "casino", "casino-bonus", "trading-bot", "crypto-bot", "crypto-trading-bot",
    "arbitrage-trading-bot", "perp-trading-bot", "dex-trading-bot",
    "cheat", "cheat2026", "pixel-scan-bot",
    "wallet-drainer", "crypto-drainer",
    "apk-mod", "mod-menu", "cracked-games",
}


def star_fake_score(repo):
    """Return 0-100 fake-star probability for a GitHub repo dict.
    Signals: fork/star ratio, keyword stuffing, spam topics, issue vacuum,
    star velocity, name patterns.
    """
    score = 0
    signals = []
    stars = repo.get("stargazers_count", 0) or 0
    forks = repo.get("forks_count", 0) or 0
    issues = repo.get("open_issues_count", 0) or 0
    desc = (repo.get("description") or "").lower()
    topics = [t.lower() for t in (repo.get("topics") or [])]
    full_name = repo.get("full_name", "")
    created_str = repo.get("created_at") or ""
    age_days = repo.get("age_days", 30)

    # 1. fork/star ratio
    ratio = forks / max(stars, 1)
    if stars >= 50:
        if ratio > 5:
            score += 40; signals.append(f"fork/star={ratio:.1f}x — bot farm")
        elif ratio > 2:
            score += 25; signals.append(f"fork/star={ratio:.1f}x — probable bot farm")
        elif ratio > 1:
            score += 12; signals.append(f"fork/star={ratio:.1f}x — suspicious")
    if stars >= 100 and forks == 0:
        score += 15; signals.append("zero forks with high stars")

    # 2. keyword stuffing
    words = [w for w in desc.split() if len(w) > 2]
    if words and stars > 100:
        unique_ratio = len(set(words)) / len(words)
        if len(words) > 30 and unique_ratio < 0.35:
            score += 25; signals.append(f"keyword stuffing (diversity={unique_ratio:.2f})")
        elif len(words) > 20 and unique_ratio < 0.50:
            score += 15; signals.append(f"possible keyword stuffing (diversity={unique_ratio:.2f})")

    # 3. spam topics/keywords
    spam_t = [t for t in topics if t in SPAM_TOPICS or any(s in t for s in SPAM_TOPICS)]
    spam_k = [kw for kw in SPAM_KEYWORDS if kw in desc]
    if len(spam_t) >= 3:
        score += 30; signals.append(f"spam topics: {spam_t}")
    elif spam_t:
        score += 15; signals.append(f"spam topics: {spam_t}")
    if len(spam_k) >= 4:
        score += 25; signals.append(f"spam keywords: {spam_k}")
    elif len(spam_k) >= 2:
        score += 12; signals.append(f"suspicious keywords: {spam_k}")

    # 4. topics count
    if len(topics) > 15:
        score += 15; signals.append(f"{len(topics)} topics — tag stuffing")
    elif len(topics) == 0 and stars > 200:
        score += 5; signals.append("no topics despite high stars")

    # 5. issue vacuum
    if issues == 0 and stars >= 100:
        score += 12; signals.append(f"0 issues with {stars} stars")

    # 6. star velocity
    stars_per_day = stars / max(age_days, 0.5)
    if age_days <= 3 and stars >= 200:
        score += 25; signals.append(f"{stars}★ in {age_days:.0f}d — unnatural")
    elif age_days <= 3 and stars >= 100:
        score += 15; signals.append(f"{stars}★ in {age_days:.0f}d — suspicious")
    elif age_days <= 7 and stars_per_day > 100:
        score += 15; signals.append(f"{stars_per_day:.0f}★/day — very high")
    elif age_days <= 7 and stars_per_day > 50:
        score += 8; signals.append(f"{stars_per_day:.0f}★/day — elevated")

    # 7. name pattern
    owner = full_name.split("/")[0] if "/" in full_name else ""
    if re.search(r"\d{4,}", owner):
        score += 5; signals.append("auto-generated org name")

    score = min(score, 100)
    if score >= 75:
        cat = "confirmed-spam"
    elif score >= 50:
        cat = "likely-fake"
    elif score >= 26:
        cat = "suspicious"
    else:
        cat = "genuine"

    return int(score), cat, signals


# ── GitHub Fetcher ─────────────────────────────────────────────────────────

def fetch_github_trending(limit=20):
    """Fetch trending GitHub repos — created in last 30 days, sorted by stars.

    Uses a two-pass strategy: fetch 50 recent repos, then client-side rank by
    star-to-age ratio to surface fast-growing new repos over established giants.
    """
    try:
        month_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        # Fetch more repos, filter locally for quality
        url = (
            f"https://api.github.com/search/repositories?"
            f"q=created:>={month_ago}+stars:>10&sort=stars&order=desc&per_page=50"
        )
        data = fetch_json(url)
        items = data.get("items", [])

        repos = []
        now = datetime.now(timezone.utc)
        for r in items:
            # Compute approximate age in days
            created_str = r.get("created_at") or ""
            created_dt = None
            try:
                created_dt = datetime.fromisoformat(created_str.rstrip("Z") + "+00:00")
                age_days = max((now - created_dt).days, 1)
            except (ValueError, TypeError, AttributeError):
                age_days = 30  # default

            stars = r.get("stargazers_count", 0)
            repo = {
                "full_name": r.get("full_name", ""),
                "html_url": r.get("html_url", ""),
                "description": r.get("description", ""),
                "stargazers_count": stars,
                "language": r.get("language", ""),
                "topics": r.get("topics", []),
                "pushed_at": r.get("pushed_at", ""),
                "created_at": created_str,
                "open_issues_count": r.get("open_issues_count", 0),
                "forks_count": r.get("forks_count", 0),
                "age_days": age_days,
                "stars_per_day": round(stars / age_days, 1),
            }
            repo["_signal_strength"] = compute_signal_strength("github", repo)
            combined_text = (
                (repo.get("description") or "")
                + " "
                + " ".join(repo.get("topics") or [])
            )
            repo["_relevance_tags"] = extract_relevance_tags(combined_text)

            # Star fake detection
            fake_score, fake_cat, fake_signals = star_fake_score(repo)
            repo["_fake_score"] = fake_score
            repo["_fake_category"] = fake_cat
            repo["_fake_signals"] = fake_signals

            repos.append(repo)

        # Sort by stars_per_day (growth rate), not total stars
        repos.sort(key=lambda r: r["stars_per_day"], reverse=True)
        return repos[:limit]
    except Exception as e:
        print(f"  WARN: GitHub trending failed: {e}", file=sys.stderr)
        return []


# ── HuggingFace Fetcher ────────────────────────────────────────────────────

def fetch_huggingface_models(limit=10):
    """Fetch trending HuggingFace models — young models with high download velocity.

    Strategy: fetch 100 recently-created models, then filter to find "hot new"
    models that satisfy:
      - Created within last 30 days
      - Total downloads < 1,000,000 (not an established giant)
      - Highest estimated weekly download growth (downloads / age_days * 7)

    This surfaces fast-rising new models that haven't yet become infrastructure.
    """
    INFRA_TAGS = {"sentence-similarity", "fill-mask", "text-classification",
                  "token-classification", "text-ranking", "feature-extraction",
                  "zero-shot-classification", "question-answering", "text2text-generation",
                  "summarization", "translation", "table-question-answering"}

    try:
        # Fetch many recently modified models
        url = (
            f"https://huggingface.co/api/models?"
            f"sort=lastModified&direction=-1&limit=100&full=false"
        )
        data = fetch_json(url)

        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)
        candidates = []

        for m in data:
            # Parse creation date
            created_str = m.get("createdAt", "")
            if not created_str:
                continue
            try:
                created_dt = datetime.fromisoformat(created_str.rstrip("Z") + "+00:00")
            except (ValueError, TypeError):
                continue

            # Filter: created within 30 days
            age_days = (now - created_dt).days
            if age_days > 30:
                continue

            downloads = m.get("downloads", 0)
            likes = m.get("likes", 0)

            # Filter: total downloads < 1M (not an established giant)
            if downloads >= 1_000_000:
                continue

            # Filter: must have meaningful download activity + community validation
            if downloads < 500 and likes < 5:
                continue
            # Skip obvious fine-tuning experiments (tiny models with 0 likes)
            if likes == 0 and downloads < 1000:
                continue

            # Estimate weekly download growth
            # (downloads / age_days * 7), minimum age 0.5 days
            effective_age = max(age_days, 0.5)
            weekly_estimate = round(downloads / effective_age * 7)

            pipeline = m.get("pipeline_tag", "") or ""
            tags = m.get("tags", []) or []

            # Skip training artifacts: generated_from_trainer, DPO, TRL, RLHF etc.
            training_noise = {"generated_from_trainer", "dpo", "trl", "rlhf", "rl_tuning",
                             "sft", "lora", "qlora", "peft", "finetuned"}
            tag_lower = {t.lower() for t in tags}
            if tag_lower & training_noise:
                continue

            # Infrastructure filter: skip pure NLP infra
            consumer_tags = [t for t in tags
                           if t not in INFRA_TAGS and "embed" not in t.lower()
                           and "license" not in t.lower() and "region" not in t.lower()
                           and "transformers" not in t.lower() and "safetensors" not in t.lower()]
            is_infra = pipeline in INFRA_TAGS
            if is_infra and not consumer_tags:
                continue

            # Require at least minimal consumer signal:
            # (a pipeline_tag that's not infra, OR at least 2 consumer tags, OR "gguf" for local-use models)
            meaningful_pipeline = pipeline and not is_infra
            has_consumer = len(consumer_tags) >= 1
            has_gguf = any("gguf" in t.lower() for t in tags)
            if not meaningful_pipeline and not has_consumer and not has_gguf:
                continue

            # Consumer relevance bonus
            consumer_bonus = 0
            if not is_infra and pipeline:
                consumer_bonus += 3
            for t in tags:
                tl = t.lower()
                if any(w in tl for w in ["chat", "instruct", "agent"]):
                    consumer_bonus += 2
                if any(w in tl for w in ["vision", "image", "video"]):
                    consumer_bonus += 2
                if any(w in tl for w in ["audio", "voice", "speech"]):
                    consumer_bonus += 2
            if has_gguf:
                consumer_bonus += 1

            candidates.append({
                "model_id": m.get("modelId", m.get("id", "")),
                "url": f"https://huggingface.co/{m.get('modelId', m.get('id', ''))}",
                "downloads": downloads,
                "likes": likes,
                "pipeline_tag": pipeline,
                "tags": tags[:10],
                "author": m.get("author", "?"),
                "created_at": created_str,
                "last_modified": m.get("lastModified", ""),
                "age_days": age_days,
                "weekly_downloads_estimate": weekly_estimate,
                "_consumer_bonus": consumer_bonus,
            })

        # Sort by weekly download estimate (descending), consumer bonus as tiebreaker
        candidates.sort(key=lambda m: (m["weekly_downloads_estimate"], m["_consumer_bonus"]), reverse=True)

        # Build final result with signal scoring
        models = []
        for m in candidates[:limit]:
            combined = m["pipeline_tag"] + " " + " ".join(m["tags"])
            m["_signal_strength"] = compute_signal_strength("huggingface", m)
            m["_relevance_tags"] = extract_relevance_tags(
                m["model_id"] + " " + combined
            )
            models.append(m)

        return models
    except Exception as e:
        print(f"  WARN: HuggingFace failed: {e}", file=sys.stderr)
        return []


# ── Reddit Fetchers ────────────────────────────────────────────────────────

def fetch_reddit_subreddit(subreddit, limit=15):
    """Fetch hot posts from a subreddit via .json endpoint."""
    try:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
        headers = {"User-Agent": "BuilderPulse/1.0 (by /u/builderpulse_bot)"}
        data = json.loads(fetch_url(url, timeout=15, headers=headers))
        children = data.get("data", {}).get("children", [])
        posts = []
        for c in children:
            d = c.get("data", {})
            post = {
                "subreddit": f"r/{subreddit}",
                "id": d.get("id", ""),
                "title": d.get("title", ""),
                "selftext": strip_html(d.get("selftext", ""))[:400],
                "score": d.get("score", 0),
                "num_comments": d.get("num_comments", 0),
                "author": d.get("author", "?"),
                "permalink": f"https://www.reddit.com{d.get('permalink', '')}",
                "created_utc": d.get("created_utc", 0),
                "url": d.get("url", ""),
            }
            combined = post.get("title", "") + " " + post.get("selftext", "")
            post["_signal_strength"] = compute_signal_strength("reddit", post)
            post["_relevance_tags"] = extract_relevance_tags(combined)
            posts.append(post)
        return posts
    except Exception as e:
        print(f"  WARN: Reddit r/{subreddit} failed: {e}", file=sys.stderr)
        return []


def fetch_all_reddit():
    """Fetch from r/SaaS, r/indiehackers, and r/programming."""
    result = {"saas_posts": [], "indiehackers_posts": [], "programming_posts": []}
    result["saas_posts"] = fetch_reddit_subreddit("SaaS", 15)
    time.sleep(1)
    result["indiehackers_posts"] = fetch_reddit_subreddit("indiehackers", 10)
    time.sleep(1)
    result["programming_posts"] = fetch_reddit_subreddit("programming", 10)
    return result


# ── Lobsters Fetcher ───────────────────────────────────────────────────────

def fetch_lobsters_hottest(limit=15):
    """Fetch hottest Lobsters stories."""
    try:
        data = fetch_json("https://lobste.rs/hottest.json")
        stories = []
        for s in data[:limit]:
            story = {
                "short_id": s.get("short_id", ""),
                "title": s.get("title", ""),
                "url": s.get("url", ""),
                "score": s.get("score", 0),
                "comment_count": s.get("comment_count", 0),
                "submitter_user": s.get("submitter_user", "?"),
                "tags": s.get("tags", []),
                "created_at": s.get("created_at", ""),
            }
            combined = story.get("title", "") + " " + " ".join(story.get("tags", []))
            story["_signal_strength"] = compute_signal_strength("lobsters", story)
            story["_relevance_tags"] = extract_relevance_tags(combined)
            stories.append(story)
        return stories
    except Exception as e:
        print(f"  WARN: Lobsters failed: {e}", file=sys.stderr)
        return []


# ── DEV Community Fetcher ──────────────────────────────────────────────────

def fetch_dev_articles(limit=20):
    """Fetch top DEV Community articles with AI/programming tags."""
    articles = []
    tags_to_try = ["programming", "ai", "webdev", "opensource", "typescript", "python", "rust"]
    for tag in tags_to_try:
        try:
            url = f"https://dev.to/api/articles?tag={tag}&top=1&per_page=5"
            data = fetch_json(url)
            for a in data:
                article = {
                    "id": a.get("id", ""),
                    "title": a.get("title", ""),
                    "url": a.get("url", ""),
                    "author": (a.get("user", {}) or {}).get("name", "?"),
                    "positive_reactions_count": a.get("positive_reactions_count", 0),
                    "comments_count": a.get("comments_count", 0),
                    "published_at": a.get("published_timestamp", a.get("published_at", "")),
                    "tag_list": a.get("tag_list", []),
                    "description": a.get("description", ""),
                    "reading_time_minutes": a.get("reading_time_minutes", 0),
                }
                combined = (
                    article.get("title", "")
                    + " "
                    + article.get("description", "")
                    + " "
                    + " ".join(article.get("tag_list", []))
                )
                article["_signal_strength"] = compute_signal_strength("dev", article)
                article["_relevance_tags"] = extract_relevance_tags(combined)
                articles.append(article)
        except Exception as e:
            print(f"  WARN: DEV.to tag={tag} failed: {e}", file=sys.stderr)
        time.sleep(0.3)

    # Deduplicate by id
    seen = set()
    unique = []
    for a in articles:
        if a["id"] not in seen:
            seen.add(a["id"])
            unique.append(a)
    return unique[:limit]


# ── Product Hunt RSS Fetcher ───────────────────────────────────────────────

def fetch_producthunt_rss(limit=30):
    """Fetch Product Hunt latest products via RSS feed, enrich with page scrape."""
    try:
        data = fetch_url(
            "https://www.producthunt.com/feed",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        root = ET.fromstring(data)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)

        products = []
        for entry in entries[:limit]:
            title_el = entry.find("atom:title", ns)
            link_el = entry.find("atom:link", ns)
            published_el = entry.find("atom:published", ns)
            updated_el = entry.find("atom:updated", ns)
            content_el = entry.find("atom:content", ns)
            author_el = entry.find("atom:author", ns)
            id_el = entry.find("atom:id", ns)

            title = title_el.text if title_el is not None else ""
            link = link_el.get("href", "") if link_el is not None else ""
            published = published_el.text if published_el is not None else ""
            updated = updated_el.text if updated_el is not None else ""
            content_html = content_el.text if content_el is not None else ""

            # Extract tagline from content HTML (first <p>)
            tagline = ""
            if content_html:
                tagline_match = re.search(r"<p>\s*(.*?)\s*</p>", content_html, re.DOTALL)
                if tagline_match:
                    tagline = strip_html(tagline_match.group(1)).strip()[:200]

            # Author
            author_name = ""
            if author_el is not None:
                name_el = author_el.find("atom:name", ns)
                if name_el is not None:
                    author_name = name_el.text or ""

            # Extract post ID from <id> tag
            post_id = ""
            if id_el is not None and id_el.text:
                id_match = re.search(r"Post/(\d+)", id_el.text)
                if id_match:
                    post_id = id_match.group(1)

            product = {
                "id": post_id,
                "name": title,
                "url": link,
                "tagline": tagline,
                "author": author_name,
                "published": published,
                "updated": updated,
                "comments_count": 0,  # Will try to enrich below
                "categories": [],
                "description": tagline,
            }

            combined = title + " " + tagline
            product["_signal_strength"] = compute_signal_strength("producthunt", product)
            product["_relevance_tags"] = extract_relevance_tags(combined)
            products.append(product)

        # Enrich today's products by scraping detail page for comments count
        today_str = datetime.now().strftime("%Y-%m-%d")
        for p in products:
            published_date = p.get("published", "")[:10]
            if published_date == today_str and p.get("url"):
                try:
                    detail_html = fetch_url(
                        p["url"],
                        timeout=10,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                        },
                    ).decode("utf-8")
                    # Extract comments count
                    cmt_match = re.findall(r"\"commentsCount\"\s*:\s*(\d+)", detail_html)
                    if cmt_match:
                        p["comments_count"] = max(int(x) for x in cmt_match)
                    # Extract JSON-LD description
                    ld_match = re.findall(
                        r'<script type="application/ld\+json">(.*?)</script>',
                        detail_html,
                        re.DOTALL,
                    )
                    for ld_str in ld_match:
                        try:
                            ld = json.loads(ld_str)
                            if isinstance(ld, dict) and ld.get("description"):
                                p["description"] = ld["description"][:500]
                                break
                        except json.JSONDecodeError:
                            pass
                except Exception:
                    pass
                time.sleep(0.3)

        return products
    except Exception as e:
        print(f"  WARN: ProductHunt RSS failed: {e}", file=sys.stderr)
        return []


# ── Google Trends Fetcher ──────────────────────────────────────────────────

def fetch_google_trends(seeds=None, max_seeds=8):
    """Fetch rising search queries from Google Trends via pytrends.

    Uses related_queries() on seed keywords to discover rising search terms.
    Rate-limited: ~30s delay between seeds, ~8 seeds max before CAPTCHA.
    Falls back gracefully on any error.
    """
    if not HAS_PYTRENDS:
        return {"available": False, "error": "pytrends not installed", "rising_terms": []}

    if seeds is None:
        seeds = GOOGLE_TRENDS_SEEDS[:max_seeds]

    rising_terms = []
    errors = []
    pytrends = None

    try:
        pytrends = TrendReq(hl="en-US", tz=360, timeout=30, retries=1)
    except Exception as e:
        return {"available": False, "error": f"TrendReq init failed: {e}", "rising_terms": []}

    for i, kw in enumerate(seeds):
        try:
            pytrends.build_payload([kw], cat=0, timeframe="today 1-m", geo="")
            related = pytrends.related_queries()
            if related and kw in related:
                rising = related[kw].get("rising", None)
                if rising is not None and not rising.empty:
                    for _, row in rising.iterrows():
                        query_text = str(row["query"])
                        try:
                            value = int(str(row["value"]).replace("+", "").replace("%", ""))
                        except (ValueError, TypeError):
                            value = 0
                        # Filter noise: skip very long queries, non-English queries
                        if 5 < len(query_text) < 120 and value >= 30:
                            rising_terms.append({
                                "keyword": query_text,
                                "change_pct": value,
                                "seed": kw,
                            })
            # 25-35 second delay to avoid rate limit
            delay = 25 + (i * 3) % 10
            time.sleep(delay)
        except Exception as e:
            err_msg = str(e)[:100]
            errors.append(f"{kw}: {err_msg}")
            # If we hit CAPTCHA/sorry page, stop — further requests will fail
            if "sorry" in err_msg.lower() or "captcha" in err_msg.lower():
                break
            time.sleep(40)

    # Deduplicate and sort by change_pct descending
    seen = set()
    unique = []
    for t in rising_terms:
        key = t["keyword"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(t)
    unique.sort(key=lambda x: x["change_pct"], reverse=True)

    # Determine availability: need at least 1 seed to succeed
    successful_seeds = sum(1 for e in errors if "sorry" not in e.lower() and "captcha" not in e.lower())
    actually_available = len(unique) > 0

    return {
        "available": actually_available,
        "source": "Google Trends (pytrends)",
        "seeds_queried": successful_seeds,
        "total_seeds": len(seeds),
        "rising_terms": unique[:50],
        "errors": errors[:5],
    }


# ── Keyword Trend Inference (Google Trends substitute) ─────────────────────

def compute_keyword_trends(hn_stories, reddit_data, dev_articles, github_repos):
    """Infer trending search terms from cross-source topic frequency."""
    # Collect all relevance tags across sources
    tag_frequency = {}
    all_items = []

    def _s(v):
        """Safe string — returns '' for None."""
        return v if v else ""

    for s in hn_stories:
        all_items.append((_s(s.get("title")), s.get("_relevance_tags", [])))
    for sub in ["saas_posts", "indiehackers_posts", "programming_posts"]:
        for p in reddit_data.get(sub, []):
            all_items.append((_s(p.get("title")) + " " + _s(p.get("selftext")),
                              p.get("_relevance_tags", [])))
    for a in dev_articles:
        all_items.append((_s(a.get("title")) + " " + _s(a.get("description")),
                          a.get("_relevance_tags", [])))
    for r in github_repos:
        all_items.append((_s(r.get("description")) + " " + " ".join(r.get("topics") or []),
                          r.get("_relevance_tags", [])))

    for text, tags in all_items:
        for tag in tags:
            tag_frequency[tag] = tag_frequency.get(tag, 0) + 1

    # Also extract bigrams from titles as candidate "search terms"
    bigram_freq = {}
    stopwords = {"the", "a", "an", "is", "of", "to", "in", "for", "on", "with",
                 "and", "or", "it", "be", "at", "by", "from", "as", "not", "but",
                 "are", "was", "has", "its", "that", "this", "can", "you", "your",
                 "how", "why", "what", "show", "hn", "new", "using", "i", "my", "we"}
    for item in all_items:
        text = item[0].lower()
        words = re.findall(r"[a-z][a-z0-9-]+", text)
        for i in range(len(words) - 1):
            if words[i] not in stopwords and words[i + 1] not in stopwords:
                bg = f"{words[i]} {words[i+1]}"
                if len(bg) > 8:
                    bigram_freq[bg] = bigram_freq.get(bg, 0) + 1

    # Keep top bigrams as trending terms
    sorted_bigrams = sorted(bigram_freq.items(), key=lambda x: x[1], reverse=True)[:30]
    trending_terms = []
    for term, count in sorted_bigrams:
        if count >= 2:
            trending_terms.append({
                "keyword": term,
                "frequency": count,
                "change_direction": "rising" if count >= 3 else "stable",
                "change_pct": count * 100,
            })

    return trending_terms


# ── Cross-Source Clustering ────────────────────────────────────────────────

def build_cross_source_clusters(all_data):
    """Group items across sources by shared themes."""
    # Collect all items with their source and tags
    clusters = {}
    sources_map = {
        "hn": all_data.get("hn", {}).get("top_stories", []) + all_data.get("hn", {}).get("show_stories", []),
        "github": all_data.get("github", {}).get("trending_repos", []),
        "huggingface": all_data.get("huggingface", {}).get("trending_models", []),
        "reddit": (
            all_data.get("reddit", {}).get("saas_posts", [])
            + all_data.get("reddit", {}).get("indiehackers_posts", [])
            + all_data.get("reddit", {}).get("programming_posts", [])
        ),
        "lobsters": all_data.get("lobsters", {}).get("hottest", []),
        "dev": all_data.get("dev_community", {}).get("articles", []),
        "producthunt": all_data.get("producthunt", {}).get("products", []),
    }

    for source, items in sources_map.items():
        for item in items:
            for tag in item.get("_relevance_tags", [])[:5]:
                if tag not in clusters:
                    clusters[tag] = {"theme": tag, "sources": set(), "total_strength": 0, "key_items": []}
                clusters[tag]["sources"].add(source)
                clusters[tag]["total_strength"] += item.get("_signal_strength", 0)
                if len(clusters[tag]["key_items"]) < 5:
                    key = {"source": source}
                    key["title"] = item.get("title") or item.get("name") or item.get("full_name", "")
                    key["url"] = item.get("url") or item.get("html_url", "")
                    key["strength"] = item.get("_signal_strength", 0)
                    clusters[tag]["key_items"].append(key)

    # Keep clusters appearing in 2+ sources, sort by total strength
    result = []
    for tag, cl in clusters.items():
        if len(cl["sources"]) >= 2:
            cl["sources"] = sorted(list(cl["sources"]))
            result.append(cl)

    result.sort(key=lambda c: c["total_strength"], reverse=True)
    return result[:20]


# ── Revenue Signal Extraction ──────────────────────────────────────────────

def extract_revenue_signals(reddit_data, dev_articles, hn_stories):
    """Extract revenue/monetization signals from text content."""
    signals = []
    all_texts = []

    for sub in ["saas_posts", "indiehackers_posts"]:
        for p in reddit_data.get(sub, []):
            all_texts.append({
                "source": "reddit",
                "title": p.get("title", ""),
                "text": p.get("selftext", ""),
                "permalink": p.get("permalink", ""),
            })

    for a in dev_articles:
        all_texts.append({
            "source": "dev",
            "title": a.get("title", ""),
            "text": a.get("description", ""),
            "permalink": a.get("url", ""),
        })

    for item in all_texts:
        combined = (item["title"] + " " + item["text"]).lower()
        revenue_info = {}

        # MRR: $200 MRR, $3K MRR, $6K/month, 6k mrr
        mrr_match = re.search(
            r"\$?(\d+[kKmM]?)\s*(?:MRR|mrr|monthly\s*(?:recurring\s*)?revenue)",
            combined, re.IGNORECASE
        )
        if mrr_match:
            revenue_info["mrr_raw"] = mrr_match.group(0).strip()
        else:
            # $X/month, $X/mo, $X per month
            mrr2 = re.search(r"\$(\d+[kKmM]?)\s*(?:\/mo(?:nth)?|per\s*month)", combined)
            if mrr2:
                revenue_info["mrr_raw"] = mrr2.group(0).strip()

        # ARR / annual: $X ARR, $X/year, $X annual
        arr_match = re.search(
            r"\$?(\d+[kKmMbB]?)\s*(?:ARR|arr|annual|yearly|\/year|per\s*year)",
            combined, re.IGNORECASE
        )
        if arr_match:
            revenue_info["arr_raw"] = arr_match.group(0).strip()

        # Revenue: $X revenue, $X income, $X earn, generated $X, hit $X, doing $X, at $X
        rev_match = re.search(
            r"(?:revenue|income|earn(?:ing)?|generated|hit|doing|at|reached|making)"
            r"\s*:?\s*\$?(\d+[kKmMbB]?)",
            combined, re.IGNORECASE
        )
        if rev_match:
            revenue_info["revenue_raw"] = rev_match.group(0).strip()

        # Sold for: sold for $X, acquired for $X
        sold_match = re.search(
            r"(?:sold|acquired|bought|exit(?:ed)?)\s+(?:for|at)\s+\$?(\d+[kKmMbB]?)",
            combined, re.IGNORECASE
        )
        if sold_match:
            revenue_info["sold_raw"] = sold_match.group(0).strip()

        # User counts
        user_match = re.search(
            r"(\d+[kKmM]?)\s*(?:users|customers|subscribers|downloads|signups|sign-ups|waitlist)",
            combined, re.IGNORECASE
        )
        if user_match:
            revenue_info["users_raw"] = user_match.group(0).strip()

        # Pricing: $X/mo, $X/month, $X/m, $X per month
        price_match = re.search(
            r"\$(\d+(?:\.\d+)?)\s*(?:\/mo(?:\b|nth)|per\s*month|\/m\b|per\s*seat)",
            combined, re.IGNORECASE
        )
        if price_match:
            revenue_info["pricing_raw"] = price_match.group(0).strip()

        # Launch / just launched
        launch_match = re.search(
            r"(?:just\s+launched|launched\s+today|finally\s+launched|launch(?:ed|ing)\s+(?:my|our|a))",
            combined, re.IGNORECASE
        )
        if launch_match:
            revenue_info["launch_flag"] = True

        if revenue_info:
            signals.append({
                "source": item["source"],
                "title": item["title"],
                "permalink": item["permalink"],
                "revenue_info": revenue_info,
            })

    # Sort: prioritize signals with MRR/ARR/revenue over user-only signals
    def signal_rank(s):
        info = s["revenue_info"]
        if any(k in info for k in ["mrr_raw", "arr_raw", "revenue_raw", "sold_raw"]):
            return 0
        return 1

    signals.sort(key=signal_rank)
    return signals[:20]


# ── Complaint Cluster Building ─────────────────────────────────────────────

def build_complaint_clusters(hn_data, reddit_data, lobsters_stories):
    """Cluster complaints across HN, Reddit, and Lobsters."""
    complaint_keywords = {
        "vendor-lock-in": ["lock-in", "vendor lock", "migration", "leaving", "switched from"],
        "pricing-unfair": ["price increase", "pricing change", "too expensive", "overpriced", "billing"],
        "breaking-change": ["broke", "break", "breaking", "deprecated", "removed", "shutdown"],
        "privacy-concern": ["privacy", "tracking", "telemetry", "surveillance", "data collection"],
        "ai-quality": ["hallucination", "wrong answer", "slop", "garbage", "useless"],
        "dx-friction": ["slow", "bug", "crash", "broken", "doesn't work", "frustrating"],
        "security-incident": ["vulnerability", "CVE", "exploit", "breach", "hack", "attack"],
    }

    clusters = {k: {"theme": k, "total_discussion": 0, "sources": [], "sample_quotes": []} for k in complaint_keywords}

    all_items = []
    for s in hn_data.get("top_stories", []):
        all_items.append({
            "source": "hn",
            "title": s.get("title", ""),
            "url": s.get("url", ""),
            "descendants": s.get("descendants", 0),
            "comments": s.get("_comments", []),
        })
    for sub in ["saas_posts", "programming_posts"]:
        for p in reddit_data.get(sub, []):
            all_items.append({
                "source": "reddit",
                "title": p.get("title", ""),
                "url": p.get("permalink", ""),
                "descendants": p.get("num_comments", 0),
                "comments": [],
            })
    for s in lobsters_stories:
        all_items.append({
            "source": "lobsters",
            "title": s.get("title", ""),
            "url": s.get("url", ""),
            "descendants": s.get("comment_count", 0),
            "comments": [],
        })

    for item in all_items:
        text = item["title"].lower()
        for ck, keywords in complaint_keywords.items():
            if any(kw in text for kw in keywords):
                clusters[ck]["total_discussion"] += item["descendants"]
                if item["source"] not in clusters[ck]["sources"]:
                    clusters[ck]["sources"].append(item["source"])
                if len(clusters[ck]["sample_quotes"]) < 3:
                    clusters[ck]["sample_quotes"].append(item["title"][:150])

    return [c for c in clusters.values() if c["total_discussion"] > 0 and c["sources"]]


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    t_start = time.time()
    output_path = sys.argv[1] if len(sys.argv) > 1 else "builderpulse_data.json"
    errors = []

    shanghai_tz = timezone(timedelta(hours=8))
    now_shanghai = datetime.now(shanghai_tz)

    # ── Source 0: Google Trends (enrichment only, 2-retry then skip) ──
    # Primary trend data comes from cross-source keyword frequency inference.
    # Google Trends is used only to calibrate/boost accuracy when available.
    print("[0/8] Fetching Google Trends (enrichment, 2-retry max)...", file=sys.stderr)
    gt_data = None
    gt_attempts = 0
    max_gt_attempts = 2
    while gt_attempts < max_gt_attempts:
        gt_attempts += 1
        try:
            gt_data = fetch_google_trends(GOOGLE_TRENDS_SEEDS[:8], max_seeds=8)
            if gt_data and gt_data.get("available") and gt_data.get("rising_terms"):
                gt_terms = len(gt_data["rising_terms"])
                print(f"  OK (attempt {gt_attempts}): {gt_terms} rising terms", file=sys.stderr)
                break
            else:
                print(f"  No data (attempt {gt_attempts}/{max_gt_attempts})", file=sys.stderr)
                gt_data = None
        except Exception as e:
            print(f"  Failed (attempt {gt_attempts}/{max_gt_attempts}): {e}", file=sys.stderr)
            gt_data = None
    if gt_data is None:
        print(f"  Google Trends unavailable after {max_gt_attempts} attempts, using fallback only", file=sys.stderr)

    # ── Source 1: HN ──
    print("[1/8] Fetching HN top stories + comments...", file=sys.stderr)
    try:
        hn_stories, hn_comments = fetch_hn_top_stories(30)
        # Attach comments to stories
        for s in hn_stories:
            sid = str(s["id"])
            if sid in hn_comments:
                s["_comments"] = hn_comments[sid]
        print(f"  OK: {len(hn_stories)} stories, {len(hn_comments)} with comments", file=sys.stderr)
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        errors.append(f"hn: {e}")
        hn_stories, hn_comments = [], {}

    # ── Source 2: HN Show HN ──
    print("[2/8] Fetching HN Show HN stories...", file=sys.stderr)
    try:
        hn_show = fetch_hn_show_stories(15)
        print(f"  OK: {len(hn_show)} stories", file=sys.stderr)
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        errors.append(f"hn_show: {e}")
        hn_show = []

    # ── Source 3: GitHub ──
    print("[3/8] Fetching GitHub trending repos...", file=sys.stderr)
    try:
        github_repos = fetch_github_trending(20)
        print(f"  OK: {len(github_repos)} repos", file=sys.stderr)
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        errors.append(f"github: {e}")
        github_repos = []

    # ── Source 4: HuggingFace ──
    print("[4/8] Fetching HuggingFace trending models...", file=sys.stderr)
    try:
        hf_models = fetch_huggingface_models(10)
        print(f"  OK: {len(hf_models)} models", file=sys.stderr)
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        errors.append(f"huggingface: {e}")
        hf_models = []

    # ── Source 5: Reddit ──
    print("[5/8] Fetching Reddit posts...", file=sys.stderr)
    try:
        reddit_data = fetch_all_reddit()
        total_reddit = sum(len(v) for v in reddit_data.values())
        print(f"  OK: {total_reddit} posts", file=sys.stderr)
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        errors.append(f"reddit: {e}")
        reddit_data = {"saas_posts": [], "indiehackers_posts": [], "programming_posts": []}

    # ── Source 6: Lobsters ──
    print("[6/8] Fetching Lobsters...", file=sys.stderr)
    try:
        lobsters_stories = fetch_lobsters_hottest(15)
        print(f"  OK: {len(lobsters_stories)} stories", file=sys.stderr)
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        errors.append(f"lobsters: {e}")
        lobsters_stories = []

    # ── Source 8: DEV Community + Product Hunt ──
    print("[8/8] Fetching DEV Community + Product Hunt...", file=sys.stderr)
    try:
        dev_articles = fetch_dev_articles(20)
        print(f"  DEV: {len(dev_articles)} articles", file=sys.stderr)
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        errors.append(f"dev: {e}")
        dev_articles = []

    try:
        ph_products = fetch_producthunt_rss(25)
        print(f"  PH: {len(ph_products)} products", file=sys.stderr)
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        errors.append(f"producthunt: {e}")
        ph_products = []

    # ── Compute cross-source clusters ──
    print("Building cross-source clusters...", file=sys.stderr)
    all_data = {
        "hn": {"top_stories": hn_stories, "show_stories": hn_show},
        "github": {"trending_repos": github_repos},
        "huggingface": {"trending_models": hf_models},
        "reddit": reddit_data,
        "lobsters": {"hottest": lobsters_stories},
        "dev_community": {"articles": dev_articles},
        "producthunt": {"products": ph_products},
    }
    clusters = build_cross_source_clusters(all_data)

    # ── Extract revenue signals ──
    print("Extracting revenue signals...", file=sys.stderr)
    revenue = extract_revenue_signals(reddit_data, dev_articles, hn_stories)

    # ── Build complaint clusters ──
    print("Building complaint clusters...", file=sys.stderr)
    complaints = build_complaint_clusters(
        {"top_stories": hn_stories}, reddit_data, lobsters_stories
    )

    # ── Compute keyword trends (always primary; GT enriches when available) ──
    print("Computing keyword trends (primary source)...", file=sys.stderr)
    fallback_trends = compute_keyword_trends(hn_stories, reddit_data, dev_articles, github_repos)

    # Enrich fallback trends with Google Trends when available
    gt_available = bool(gt_data and gt_data.get("available") and gt_data.get("rising_terms"))
    gt_rising = gt_data.get("rising_terms", []) if gt_data else []

    if gt_available and gt_rising:
        # Build lookup of GT keywords (lowercase)
        gt_keywords = set()
        for t in gt_rising:
            kw = t.get("keyword", "").lower().strip()
            gt_keywords.add(kw)
        # Boost fallback terms that also appear in Google Trends
        for ft in fallback_trends:
            ft_kw = ft.get("keyword", "").lower().strip()
            if ft_kw in gt_keywords or any(
                gt_kw in ft_kw or ft_kw in gt_kw
                for gt_kw in gt_keywords
            ):
                ft["gt_corroborated"] = True
                # Boost frequency when GT confirms
                ft["frequency"] = ft.get("frequency", 0) + 3
        # Re-sort after boosting
        fallback_trends.sort(key=lambda x: x.get("frequency", 0), reverse=True)
        print(f"  GT-enriched: {sum(1 for ft in fallback_trends if ft.get('gt_corroborated'))} terms corroborated", file=sys.stderr)

    gt_source_note = "Google Trends (pytrends)" if gt_available else "cross-platform keyword frequency inference"

    # ── Star fake audit summary ──
    star_fake_audit = {
        "total_repos": len(github_repos),
        "flagged_repos": [],
        "summary": {"genuine": 0, "suspicious": 0, "likely-fake": 0, "confirmed-spam": 0},
    }
    for r in github_repos:
        cat = r.get("_fake_category", "genuine")
        score = r.get("_fake_score", 0)
        star_fake_audit["summary"][cat] = star_fake_audit["summary"].get(cat, 0) + 1
        if score >= 26:
            star_fake_audit["flagged_repos"].append({
                "full_name": r.get("full_name", ""),
                "score": score,
                "category": cat,
                "stars": r.get("stargazers_count", 0),
                "forks": r.get("forks_count", 0),
                "signals": r.get("_fake_signals", []),
            })
    star_fake_audit["flagged_repos"].sort(key=lambda x: x["score"], reverse=True)

    # ── Build output ──
    result = {
        "meta": {
            "date": now_shanghai.strftime("%Y-%m-%d"),
            "generated_at": now_shanghai.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "source_count": 8,
            "total_signals": (
                len(hn_stories) + len(hn_show) + len(github_repos) + len(hf_models)
                + sum(len(v) for v in reddit_data.values()) + len(lobsters_stories)
                + len(dev_articles) + len(ph_products)
            ),
            "google_trends_available": gt_available,
            "errors": errors,
        },
        "hn": {
            "top_stories": hn_stories,
            "show_stories": hn_show,
        },
        "github": {
            "trending_repos": github_repos,
        },
        "huggingface": {
            "trending_models": hf_models,
        },
        "reddit": reddit_data,
        "lobsters": {
            "hottest": lobsters_stories,
        },
        "dev_community": {
            "articles": dev_articles,
        },
        "producthunt": {
            "products": ph_products,
        },
        "trends": {
            "available": gt_available,
            "source": gt_source_note,
            "google_trends_rising": gt_rising,
            "trending_terms": fallback_trends,
        },
        "cross_source_clusters": clusters,
        "revenue_signals": revenue,
        "complaint_clusters": complaints,
        "star_fake_audit": star_fake_audit,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t_start
    print(f"[BuilderPulse] Done in {elapsed:.1f}s → {output_path}", file=sys.stderr)
    if errors:
        print(f"[BuilderPulse] {len(errors)} source errors (non-fatal)", file=sys.stderr)


if __name__ == "__main__":
    main()
