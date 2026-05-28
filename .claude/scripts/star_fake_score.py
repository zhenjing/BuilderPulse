#!/usr/bin/env python3
"""
GitHub Star Fake Score — detect fake/suspicious stars on GitHub repositories.

Usage:
    # Single repo by full_name
    python star_fake_score.py openai/gpt-4

    # Single repo by URL
    python star_fake_score.py https://github.com/openai/gpt-4

    # Batch from JSON file (array of repo objects from GitHub API)
    python star_fake_score.py --batch repos.json

    # From stdin (pipe GitHub API results)
    cat repos.json | python star_fake_score.py --stdin

    # Output only fakes (score >= 50)
    python star_fake_score.py --batch repos.json --min-score 50

    # CSV output for spreadsheet analysis
    python star_fake_score.py --batch repos.json --csv

Output per repo: score (0-100), category, signal breakdown.
0-25: genuine, 26-49: suspicious, 50-74: likely-fake, 75+: confirmed-spam
"""

import json
import sys
import io
import re
import urllib.request
from datetime import datetime, timedelta, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ── Spam indicators ──────────────────────────────────────────────────────

SPAM_KEYWORDS = {
    "casino", "bonus", "crack", "cheat", "hack2026", "cheat2026",
    "trading-bot", "crypto-bot", "stake", "bypass", "exploit",
    "cracked", "keygen", "activation-key", "license-key-generator",
    "no-deposit", "free-spins", "crypto-casino", "poker-bot",
    "warzone-hack", "cod-hack", "valorant-hack", "apex-hack",
    "fortnite-hack", "wallhack", "aimbot", "esp-hack",
    "slot", "wager", "deposit-bonus", "welcome-bonus",
    "airdrop", "token-launch", "presale", "whitelist",
    "onlyfans", "leaked", "nude", "cracked-account",
}

SPAM_TOPICS = {
    "casino", "casino-bonus", "casino-bonus-2026", "crypto-casino",
    "trading-bot", "crypto-bot", "crypto-trading-bot", "arbitrage-trading-bot",
    "perp-trading-bot", "dex-trading-bot", "fapi-bot",
    "cheat2026", "warzone-cheat", "cod-cheat", "pixel-scan-bot",
    "hack2026", "valorant-hack", "apex-hack",
    "wallet-drainer", "crypto-drainer", "token-miner",
    "pirated-software", "cracked-games", "free-premium",
    "apk-mod", "mod-menu", "unlock-tool",
}

SEO_STUFFING_PATTERNS = [
    r"(\w+)\s+\1\s+\1",  # same word 3x in a row
    r"(\S+(\s+\S+){2,})\s+\1",  # repeated phrase
]


def fetch_repo_from_api(full_name, timeout=15):
    """Fetch repo metadata from GitHub API."""
    url = f"https://api.github.com/repos/{full_name}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "StarFakeScore/1.0",
        "Accept": "application/vnd.github.v3+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"_error": str(e)}


def fetch_owner_from_api(login, timeout=15):
    """Fetch user/org profile from GitHub API."""
    url = f"https://api.github.com/users/{login}"
    req = urllib.request.Request(url, headers={"User-Agent": "StarFakeScore/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return {}


def description_entropy(text):
    """Measure word diversity in description. Low entropy = keyword stuffing."""
    if not text:
        return 1.0
    words = re.findall(r"[a-z0-9]+", text.lower())
    if len(words) < 5:
        return 1.0
    unique = len(set(words))
    return min(unique / len(words), 1.0)


def count_seo_repetitions(text):
    """Count repeated phrases in text (indicator of SEO stuffing)."""
    if not text:
        return 0
    count = 0
    for pattern in SEO_STUFFING_PATTERNS:
        matches = re.findall(pattern, text.lower())
        count += len(matches)
    return count


def compute_star_fake_score(repo, owner_info=None, verbose=False):
    """
    Compute fake-star probability score for a GitHub repo.

    Args:
        repo: dict with GitHub API repo fields. Required: full_name, stargazers_count,
              forks_count, description, topics, open_issues_count, created_at.
        owner_info: optional dict from GitHub users API for the owner.

    Returns:
        dict with: full_name, score, category, signals[], details{}
    """
    score = 0
    signals = []
    details = {}

    stars = repo.get("stargazers_count", 0) or 0
    forks = repo.get("forks_count", 0) or 0
    issues = repo.get("open_issues_count", 0) or 0
    desc = repo.get("description") or ""
    topics = repo.get("topics", []) or []
    created_str = repo.get("created_at") or ""
    full_name = repo.get("full_name", "")

    # ── Signal 1: fork/star ratio anomalies ──
    ratio = forks / max(stars, 1)
    details["fork_star_ratio"] = round(ratio, 3)

    if stars >= 50 and ratio > 5:
        score += 40
        signals.append(f"fork/star ratio extreme ({ratio:.1f}:1) — likely bot farm")
    elif stars >= 50 and ratio > 2:
        score += 25
        signals.append(f"fork/star ratio very high ({ratio:.1f}:1) — probable bot farm")
    elif stars >= 50 and ratio > 1:
        score += 12
        signals.append(f"fork/star ratio elevated ({ratio:.1f}:1) — suspicious")

    if stars >= 100 and forks == 0:
        score += 15
        signals.append("zero forks with high stars — no organic engagement")

    # ── Signal 2: description quality ──
    entropy = description_entropy(desc)
    seo_reps = count_seo_repetitions(desc)
    desc_words = len(re.findall(r"[a-z0-9]+", desc.lower()))
    details["desc_entropy"] = round(entropy, 3)
    details["desc_word_count"] = desc_words

    if desc_words > 30 and entropy < 0.45:
        score += 25
        signals.append(f"keyword stuffing (entropy={entropy:.2f}, {desc_words} words)")
    elif desc_words > 20 and entropy < 0.55:
        score += 15
        signals.append(f"possible keyword stuffing (entropy={entropy:.2f})")

    if seo_reps >= 2:
        score += 20
        signals.append(f"SEO phrase repetition detected ({seo_reps} repeats)")

    # ── Signal 3: spam topics ──
    spam_hits = [t for t in topics if t.lower() in SPAM_TOPICS]
    details["spam_topics"] = spam_hits
    if len(spam_hits) >= 3:
        score += 30
        signals.append(f"multiple spam topics: {spam_hits}")
    elif len(spam_hits) >= 1:
        score += 15
        signals.append(f"spam topic: {spam_hits}")

    # ── Signal 4: spam keywords in description ──
    desc_lower = desc.lower()
    spam_kw_hits = [kw for kw in SPAM_KEYWORDS if kw in desc_lower]
    details["spam_keywords"] = spam_kw_hits
    if len(spam_kw_hits) >= 4:
        score += 25
        signals.append(f"description spam keywords: {spam_kw_hits}")
    elif len(spam_kw_hits) >= 2:
        score += 12
        signals.append(f"suspicious keywords: {spam_kw_hits}")

    # ── Signal 5: topics count anomaly ──
    details["topic_count"] = len(topics)
    if len(topics) > 15:
        score += 15
        signals.append(f"excessive topics ({len(topics)}) — SEO tag stuffing")
    elif len(topics) == 0 and stars > 200:
        score += 5
        signals.append("no topics despite high stars — unusual")

    # ── Signal 6: issue vacuum ──
    details["open_issues"] = issues
    if issues == 0 and stars >= 100:
        score += 12
        signals.append(f"zero open issues with {stars} stars — no community engagement")
    elif issues <= 1 and stars >= 300:
        score += 8
        signals.append(f"only {issues} open issue(s) with {stars} stars — low engagement")

    # ── Signal 7: age anomaly (too many stars too fast) ──
    if created_str:
        try:
            created_dt = datetime.fromisoformat(created_str.rstrip("Z") + "+00:00")
            age_days = max((datetime.now(timezone.utc) - created_dt).days, 0.5)
            stars_per_day = stars / age_days
            details["age_days"] = age_days
            details["stars_per_day"] = round(stars_per_day, 1)

            if age_days <= 3 and stars >= 200:
                score += 25
                signals.append(f"{stars} stars in {age_days:.0f}d ({stars_per_day:.0f}/day) — unnatural velocity")
            elif age_days <= 3 and stars >= 100:
                score += 15
                signals.append(f"{stars} stars in {age_days:.0f}d — suspicious velocity")
            elif age_days <= 7 and stars_per_day > 100:
                score += 15
                signals.append(f"{stars_per_day:.0f} stars/day — very high velocity")
            elif age_days <= 7 and stars_per_day > 50:
                score += 8
                signals.append(f"{stars_per_day:.0f} stars/day — elevated velocity")
        except (ValueError, TypeError, AttributeError):
            details["age_days"] = -1
            details["stars_per_day"] = -1

    # ── Signal 8: owner account signals ──
    if owner_info:
        owner_type = owner_info.get("type", "User")
        created_str_owner = owner_info.get("created_at", "")
        public_repos = owner_info.get("public_repos", 0)
        followers = owner_info.get("followers", 0)

        details["owner_type"] = owner_type
        details["owner_public_repos"] = public_repos
        details["owner_followers"] = followers

        if owner_type == "User":
            if public_repos <= 2 and stars > 100:
                score += 18
                signals.append(f"single-repo account ({public_repos} repos) with {stars} stars")
            elif public_repos <= 2 and stars > 50:
                score += 10
                signals.append(f"low-repo account ({public_repos} repos)")

            if created_str_owner:
                try:
                    owner_created = datetime.fromisoformat(created_str_owner.rstrip("Z") + "+00:00")
                    owner_age_days = max((datetime.now(timezone.utc) - owner_created).days, 1)
                    details["owner_age_days"] = owner_age_days
                    if owner_age_days < 30 and stars > 100:
                        score += 20
                        signals.append(f"brand new account ({owner_age_days}d old) with {stars} stars")
                    elif owner_age_days < 30 and stars > 50:
                        score += 10
                        signals.append(f"new account ({owner_age_days}d old)")
                except (ValueError, TypeError, AttributeError):
                    pass

            # Suspicious name patterns
            login = owner_info.get("login", "").lower()
            if re.search(r"\d{4,}", login):
                score += 8
                signals.append(f"numeric-heavy username: {login}")
            if re.search(r"[a-z]+-[a-z]+-[a-z]+-[a-z]+", login):
                score += 8
                signals.append(f"auto-generated username pattern: {login}")

    # ── Signal 9: name pattern (org/user name) ──
    name_part = full_name.split("/")[0].lower() if "/" in full_name else ""
    details["owner_name"] = name_part
    if re.search(r"[a-z]+\d{4,}", name_part):
        score += 5
        signals.append("organization name looks auto-generated")

    # ── Final scoring ──
    score = min(score, 100)

    if score >= 75:
        category = "confirmed-spam"
    elif score >= 50:
        category = "likely-fake"
    elif score >= 26:
        category = "suspicious"
    else:
        category = "genuine"

    return {
        "full_name": full_name,
        "score": score,
        "category": category,
        "signals": signals,
        "details": details,
    }


# ── Output formatters ─────────────────────────────────────────────────────

def format_result(result, verbose=False):
    """Format a single result for terminal output."""
    emoji = {"genuine": "✓", "suspicious": "⚠", "likely-fake": "✗", "confirmed-spam": "☠"}
    icon = emoji.get(result["category"], "?")

    lines = [
        f"{icon} {result['full_name']}  score={result['score']}  [{result['category']}]",
    ]
    for sig in result["signals"]:
        lines.append(f"   → {sig}")

    if verbose and result["details"]:
        lines.append(f"   details: {json.dumps(result['details'], ensure_ascii=False)}")

    return "\n".join(lines)


def format_result_csv(result):
    """Format a single result as CSV row."""
    d = result["details"]
    return (
        f"{result['full_name']},{result['score']},{result['category']},"
        f"{d.get('fork_star_ratio', '')},{d.get('desc_entropy', '')},"
        f"{d.get('age_days', '')},{d.get('stars_per_day', '')},"
        f"{d.get('open_issues', '')},{d.get('topic_count', '')},"
        f"\"{'|'.join(result['signals'])}\""
    )


def csv_header():
    return "repo,score,category,fork_star_ratio,desc_entropy,age_days,stars_per_day,open_issues,topic_count,signals"


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="GitHub Star Fake Score — detect fake/suspicious stars"
    )
    parser.add_argument(
        "target", nargs="?", default=None,
        help="GitHub repo full_name (owner/repo) or URL"
    )
    parser.add_argument(
        "--batch", "-b", type=str, default=None,
        help="Path to JSON file with repo array (from GitHub API)"
    )
    parser.add_argument(
        "--stdin", action="store_true",
        help="Read JSON repo array from stdin"
    )
    parser.add_argument(
        "--min-score", "-m", type=int, default=0,
        help="Only show repos with score >= N (default: 0 = all)"
    )
    parser.add_argument(
        "--csv", action="store_true",
        help="Output in CSV format"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Include detail fields in output"
    )
    parser.add_argument(
        "--fetch", "-f", action="store_true",
        help="Fetch repo+owner data from GitHub API (otherwise use provided JSON fields)"
    )
    parser.add_argument(
        "--json-output", "-j", action="store_true",
        help="Output raw JSON (machine-readable)"
    )

    args = parser.parse_args()

    repos = []

    # ── Collect repos from input ──
    if args.batch:
        with open(args.batch, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            repos = data
        elif isinstance(data, dict) and "items" in data:
            repos = data["items"]
        else:
            repos = [data]

    elif args.stdin:
        data = json.load(sys.stdin)
        if isinstance(data, list):
            repos = data
        elif isinstance(data, dict) and "items" in data:
            repos = data["items"]
        else:
            repos = [data]

    elif args.target:
        target = args.target.strip().rstrip("/")
        # Parse: URL → full_name
        match = re.search(r"github\.com/([^/]+/[^/]+?)(?:\.git)?$", target)
        if match:
            full_name = match.group(1)
        elif re.match(r"^[^/]+/[^/]+$", target):
            full_name = target
        else:
            print(f"ERROR: not a valid repo URL or full_name: {target}", file=sys.stderr)
            sys.exit(1)

        if args.fetch:
            repo = fetch_repo_from_api(full_name)
            if "_error" in repo:
                print(f"ERROR fetching repo: {repo['_error']}", file=sys.stderr)
                sys.exit(1)
            owner_info = fetch_owner_from_api(repo.get("owner", {}).get("login", ""))
            repos = [repo]
        else:
            # Minimal object from just the name
            repos = [{"full_name": full_name, "stargazers_count": 0}]

    else:
        parser.print_help()
        sys.exit(1)

    # ── Use API for each repo if --fetch is set ──
    if args.fetch:
        enriched = []
        for r in repos:
            fn = r.get("full_name", "")
            if not fn:
                continue
            api_data = fetch_repo_from_api(fn)
            if "_error" in api_data:
                enriched.append(r)  # keep original
                continue
            owner = fetch_owner_from_api(api_data.get("owner", {}).get("login", ""))
            api_data["_owner_info"] = owner
            enriched.append(api_data)
        repos = enriched

    # ── Score each repo ──
    results = []
    for repo in repos:
        if not repo.get("full_name"):
            continue
        owner_info = repo.pop("_owner_info", None)
        result = compute_star_fake_score(repo, owner_info=owner_info)
        results.append(result)

    # Filter
    if args.min_score > 0:
        results = [r for r in results if r["score"] >= args.min_score]

    # Sort by score descending
    results.sort(key=lambda r: r["score"], reverse=True)

    # ── Output ──
    if args.json_output:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif args.csv:
        print(csv_header())
        for r in results:
            print(format_result_csv(r))
    else:
        for r in results:
            print(format_result(r, verbose=args.verbose))
            print()

        # Summary
        counts = {"genuine": 0, "suspicious": 0, "likely-fake": 0, "confirmed-spam": 0}
        for r in results:
            counts[r["category"]] = counts.get(r["category"], 0) + 1
        print(f"── Summary: {len(results)} repos ──")
        for cat, count in counts.items():
            if count > 0:
                emoji = {"genuine": "✓", "suspicious": "⚠", "likely-fake": "✗", "confirmed-spam": "☠"}
                print(f"  {emoji.get(cat, '?')} {cat}: {count}")


if __name__ == "__main__":
    main()
