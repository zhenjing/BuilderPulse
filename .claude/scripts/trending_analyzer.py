#!/usr/bin/env python3
"""
GitHub Trending Analyzer — fetch daily/weekly trending repos, enrich with API
metadata, detect fake stars, and output structured JSON for Claude to analyze.

Usage:
    python trending_analyzer.py trending_data.json              # daily trending (default)
    python trending_analyzer.py trending_data.json --weekly     # weekly trending
    python trending_analyzer.py trending_data.json --language python  # filter by language
"""

import json
import sys
import io
import re
import time
import urllib.request
import urllib.error
import subprocess
from datetime import datetime, timedelta, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ── Star Fake Score (inline) ──────────────────────────────────────────────

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
    """0-100 fake-star score. Returns (score, category, signals)."""
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

    words = [w for w in desc.split() if len(w) > 2]
    if words and stars > 100:
        unique_ratio = len(set(words)) / len(words)
        if len(words) > 30 and unique_ratio < 0.35:
            score += 25; signals.append(f"keyword stuffing (diversity={unique_ratio:.2f})")
        elif len(words) > 20 and unique_ratio < 0.50:
            score += 15; signals.append(f"possible keyword stuffing (diversity={unique_ratio:.2f})")

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

    if len(topics) > 15:
        score += 15; signals.append(f"{len(topics)} topics — tag stuffing")
    elif len(topics) == 0 and stars > 200:
        score += 5; signals.append("no topics despite high stars")

    if issues == 0 and stars >= 100:
        score += 12; signals.append(f"0 issues with {stars} stars")

    stars_per_day = stars / max(age_days, 0.5)
    if age_days <= 3 and stars >= 200:
        score += 25; signals.append(f"{stars}★ in {age_days:.0f}d — unnatural")
    elif age_days <= 3 and stars >= 100:
        score += 15; signals.append(f"{stars}★ in {age_days:.0f}d — suspicious")
    elif age_days <= 7 and stars_per_day > 100:
        score += 15; signals.append(f"{stars_per_day:.0f}★/day — very high")
    elif age_days <= 7 and stars_per_day > 50:
        score += 8; signals.append(f"{stars_per_day:.0f}★/day — elevated")

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


# ── HTTP Helpers ──────────────────────────────────────────────────────────

GITHUB_TOKEN = None  # set via --token or GITHUB_TOKEN env var


def _api_headers():
    h = {"User-Agent": "TrendingAnalyzer/1.0"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def fetch_url(url, timeout=30, headers=None):
    default_headers = _api_headers()
    if headers:
        default_headers.update(headers)
    req = urllib.request.Request(url, headers=default_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_json(url, timeout=30):
    req = urllib.request.Request(url, headers=_api_headers())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# ── Trending Scraper ──────────────────────────────────────────────────────

def _download_via_curl(url, timeout=30):
    """Use curl subprocess to download — handles GFW interruptions better."""
    result = subprocess.run(
        ["curl", "-sL", "--max-time", str(timeout),
         "-H", "User-Agent: TrendingAnalyzer/1.0",
         "-H", "Accept: text/html,application/xhtml+xml",
         "--retry", "3", "--retry-delay", "2",
         url],
        capture_output=True, timeout=timeout + 10,
    )
    if result.returncode == 0 and result.stdout:
        return result.stdout.decode("utf-8", errors="replace")
    raise RuntimeError(f"curl failed with code {result.returncode}")


def _download_page(url, timeout=30):
    """Download page with urllib retry, fallback to curl."""
    # Attempt 1-3: urllib
    for attempt in range(3):
        try:
            html = fetch_url(url, timeout=timeout).decode("utf-8")
            # Validate: must have repo blocks or be a complete page (>500KB)
            has_repos = 'class="h3 lh-condensed"' in html
            is_complete = html.rstrip().endswith("</html>")
            if has_repos or (len(html) > 500000 and is_complete):
                return html
            print(f"  Attempt {attempt+1}: got {len(html)} bytes (incomplete), retrying...", file=sys.stderr)
        except (urllib.error.URLError, ConnectionError, TimeoutError,
                urllib.error.HTTPError, OSError) as e:
            print(f"  Attempt {attempt+1}: {e}, retrying...", file=sys.stderr)
        time.sleep(2)

    # Attempt 4: curl
    print(f"  Falling back to curl...", file=sys.stderr)
    return _download_via_curl(url, timeout=timeout)


def scrape_trending_page(since="daily", language=""):
    """Scrape github.com/trending and return list of basic repo dicts."""
    params = f"?since={since}"
    if language:
        params += f"&language={language}"
    url = f"https://github.com/trending{params}"

    print(f"  Fetching {url} ...", file=sys.stderr)
    html = _download_page(url, timeout=30)

    # Extract repo blocks from h2.h3.lh-condensed
    h2_blocks = re.findall(
        r'<h2\s+class="h3\s+lh-condensed">(.*?)</h2>', html, re.DOTALL
    )
    repo_names = []
    for block in h2_blocks:
        links = re.findall(r'href="/([^"]+)"', block)
        if links and links[0] != "trending":
            repo_names.append(links[0])

    # Descriptions (col-9 color-fg-muted)
    descs_raw = re.findall(
        r'<p\s+class="col-9\s+color-fg-muted[^"]*"[^>]*>\s*(.*?)\s*</p>',
        html, re.DOTALL,
    )
    descs = [re.sub(r"<[^>]+>", "", d).strip()[:300] for d in descs_raw]

    # Stars today
    stars_today = re.findall(r"(\d[\d,]*)\s*stars?\s*today", html)

    # Languages
    langs = re.findall(r'itemprop="programmingLanguage"[^>]*>\s*(\S+?)\s*</span>', html)
    langs = [l.replace("</span>", "") for l in langs]

    repos = []
    for i, name in enumerate(repo_names):
        repos.append({
            "full_name": name,
            "description": descs[i] if i < len(descs) else "",
            "language": langs[i] if i < len(langs) else "",
            "stars_today_str": stars_today[i] if i < len(stars_today) else "0",
            "stars_today": int(stars_today[i].replace(",", "")) if i < len(stars_today) else 0,
        })

    print(f"  Parsed {len(repos)} repos from Trending page", file=sys.stderr)
    return repos


# ── API Enrichment ────────────────────────────────────────────────────────

def enrich_repo_with_api(repo):
    """Fetch full repo metadata from GitHub API."""
    try:
        data = fetch_json(f"https://api.github.com/repos/{repo['full_name']}")
        now = datetime.now(timezone.utc)
        created_str = data.get("created_at") or ""
        try:
            created_dt = datetime.fromisoformat(created_str.rstrip("Z") + "+00:00")
            age_days = max((now - created_dt).days, 1)
        except (ValueError, TypeError, AttributeError):
            age_days = 365

        stars = data.get("stargazers_count", 0)
        repo.update({
            "html_url": data.get("html_url", ""),
            "stargazers_count": stars,
            "forks_count": data.get("forks_count", 0),
            "open_issues_count": data.get("open_issues_count", 0),
            "topics": data.get("topics", []),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "pushed_at": data.get("pushed_at", ""),
            "language": repo.get("language") or data.get("language", ""),
            "license": (data.get("license") or {}).get("spdx_id", "N/A") if data.get("license") else "N/A",
            "owner_type": (data.get("owner") or {}).get("type", "User"),
            "homepage": data.get("homepage", ""),
            "age_days": age_days,
            "stars_per_day": round(stars / age_days, 1),
        })
        # Override description from API if page didn't have one
        if not repo.get("description"):
            repo["description"] = data.get("description") or ""
        return True
    except Exception as e:
        print(f"  WARN: API enrich failed for {repo['full_name']}: {e}", file=sys.stderr)
        return False


def enrich_all_repos(repos):
    """Enrich all repos with API data, with rate-limit awareness."""
    enriched = []
    rate_limited = False
    for i, repo in enumerate(repos):
        if rate_limited:
            repo["_fake_score"] = -1
            repo["_fake_category"] = "api-skipped"
            repo["_fake_signals"] = []
            enriched.append(repo)
            continue

        print(f"  [{i+1}/{len(repos)}] Enriching {repo['full_name']} ...", file=sys.stderr)
        try:
            success = enrich_repo_with_api(repo)
            if success:
                score, cat, signals = star_fake_score(repo)
                repo["_fake_score"] = score
                repo["_fake_category"] = cat
                repo["_fake_signals"] = signals
            else:
                repo["_fake_score"] = -1
                repo["_fake_category"] = "api-failed"
                repo["_fake_signals"] = []
        except Exception as e:
            err_msg = str(e)
            if "403" in err_msg or "rate limit" in err_msg.lower():
                print(f"  RATE LIMITED — skipping remaining API calls", file=sys.stderr)
                rate_limited = True
            repo["_fake_score"] = -1
            repo["_fake_category"] = "api-failed"
            repo["_fake_signals"] = []

        enriched.append(repo)
        if i < len(repos) - 1 and not rate_limited:
            time.sleep(0.5)
    return enriched


# ── Report generation hints ───────────────────────────────────────────────

def classify_repo_type(repo):
    """Classify repo into broad category for analysis framing."""
    desc = (repo.get("description") or "").lower()
    topics = [t.lower() for t in (repo.get("topics") or [])]
    full_name = repo.get("full_name", "").lower()
    all_text = desc + " " + " ".join(topics) + " " + full_name

    if any(kw in all_text for kw in ["ai", "llm", "gpt", "agent", "model", "claude", "prompt", "copilot"]):
        return "AI/LLM工具"
    if any(kw in all_text for kw in ["framework", "library", "sdk", "api", "cli", "tool"]):
        return "开发者工具/框架"
    if any(kw in all_text for kw in ["awesome", "curated", "list", "resource", "guide"]):
        return "资源列表/知识库"
    if any(kw in all_text for kw in ["app", "desktop", "mobile", "web", "dashboard"]):
        return "应用/产品"
    if any(kw in all_text for kw in ["skill", "harness", "rule", "config"]):
        return "Agent技能/配置"
    return "其他"


def generate_analysis_prompts(repos):
    """Generate Claude-ready analysis prompts for each repo."""
    prompts = []
    for repo in repos:
        full_name = repo.get("full_name", "")
        desc = repo.get("description", "")
        stars = repo.get("stargazers_count", 0)
        stars_today = repo.get("stars_today", 0)
        lang = repo.get("language", "")
        topics = repo.get("topics", [])
        age_days = repo.get("age_days", 30)
        fake_score = repo.get("_fake_score", -1)
        fake_cat = repo.get("_fake_category", "unknown")
        fake_signals = repo.get("_fake_signals", [])
        repo_type = classify_repo_type(repo)
        license_spdx = repo.get("license", "N/A")
        homepage = repo.get("homepage", "")

        prompt = {
            "repo": full_name,
            "type": repo_type,
            "data": {
                "description": desc,
                "total_stars": stars,
                "stars_today": stars_today,
                "language": lang,
                "topics": topics[:10],
                "age_days": age_days,
                "license": license_spdx,
                "homepage": homepage,
            },
            "authenticity": {
                "fake_score": fake_score,
                "category": fake_cat,
                "signals": fake_signals,
            },
            "analysis_questions": {
                "problem": f"{full_name} 解决什么问题？目标用户是谁？痛点有多痛？",
                "differentiation": "比现有方案好在哪里？是真差异还是换壳？技术壁垒在哪？",
                "commercialization": "能否商业化？如果可以，什么形态（SaaS/开源+托管/咨询/内容付费）？定价多少？MVP 多久？",
            },
        }
        prompts.append(prompt)
    return prompts


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    global GITHUB_TOKEN
    output_path = sys.argv[1] if len(sys.argv) > 1 else "trending_data.json"
    since = "daily"
    language = ""

    # Parse flags
    args = sys.argv[2:] if len(sys.argv) > 2 else []
    for arg in args:
        if arg == "--weekly":
            since = "weekly"
        elif arg == "--monthly":
            since = "monthly"
        elif arg.startswith("--language="):
            language = arg.split("=", 1)[1]
        elif arg.startswith("--lang="):
            language = arg.split("=", 1)[1]
        elif arg.startswith("--token="):
            GITHUB_TOKEN = arg.split("=", 1)[1]
        elif arg == "--no-enrich":
            GITHUB_TOKEN = "__skip__"  # signal to skip all API calls

    # Token from env var (lower priority than CLI)
    import os
    if not GITHUB_TOKEN:
        GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", None)

    t_start = time.time()
    shanghai_tz = timezone(timedelta(hours=8))
    now = datetime.now(shanghai_tz)

    # ── Step 1: Scrape Trending page ──
    print(f"[1/3] Scraping GitHub Trending ({since}) ...", file=sys.stderr)
    try:
        repos = scrape_trending_page(since=since, language=language)
    except Exception as e:
        print(f"  ERROR: Cannot fetch trending page: {e}", file=sys.stderr)
        print(f"  Falling back to API approximation ...", file=sys.stderr)
        # Fallback: use Search API for recently-pushed high-star repos
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        url = (
            f"https://api.github.com/search/repositories?"
            f"q=pushed:>={yesterday}+stars:>50&sort=stars&order=desc&per_page=20"
        )
        data = fetch_json(url)
        repos = []
        for r in data.get("items", []):
            repos.append({
                "full_name": r.get("full_name", ""),
                "description": r.get("description", ""),
                "language": r.get("language", ""),
                "stars_today_str": "?",
                "stars_today": 0,
            })
        print(f"  API fallback: {len(repos)} repos", file=sys.stderr)

    # ── Step 2: Enrich with API ──
    if GITHUB_TOKEN == "__skip__":
        print("[2/3] Skipping API enrichment (--no-enrich)", file=sys.stderr)
        for r in repos:
            r["_fake_score"] = -1
            r["_fake_category"] = "not-enriched"
            r["_fake_signals"] = []
    else:
        print(f"[2/3] Enriching {len(repos)} repos via GitHub API ...", file=sys.stderr)
        repos = enrich_all_repos(repos)

    # ── Step 3: Generate analysis prompts ──
    print("[3/3] Generating analysis prompts ...", file=sys.stderr)
    analysis_prompts = generate_analysis_prompts(repos)

    # ── Build output ──
    fake_summary = {"genuine": 0, "suspicious": 0, "likely-fake": 0, "confirmed-spam": 0}
    for r in repos:
        cat = r.get("_fake_category", "unknown")
        fake_summary[cat] = fake_summary.get(cat, 0) + 1

    result = {
        "meta": {
            "date": now.strftime("%Y-%m-%d"),
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "source": f"github.com/trending?since={since}" + (f"&language={language}" if language else ""),
            "total_repos": len(repos),
            "data_quality": "api_enriched" if repos and repos[0].get("stargazers_count") else "scrape_only",
        },
        "trending_repos": repos,
        "analysis_prompts": analysis_prompts,
        "star_fake_summary": fake_summary,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t_start
    print(f"[TrendingAnalyzer] Done in {elapsed:.1f}s → {output_path}", file=sys.stderr)
    print(f"  Repos: {len(repos)} | Authenticity: {fake_summary}", file=sys.stderr)


if __name__ == "__main__":
    main()
