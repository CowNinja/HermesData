#!/usr/bin/env python3
"""extract_x_wisdom.py — SINGLE inspiration pipeline for Hermes (list-only).

Sole cron for new external inspiration (Jeff 2026-07-12):
  X list 2068802754282504617 only. No parallel Universal-Ingestion inspiration pulls.

Modes:
  1) Agent cron (preferred): LLM uses x_search, then may call this with --from-json
  2) Direct: python extract_x_wisdom.py --from-json posts.json
  3) Seed/batch: --write-seed writes distilled high-signal entries from inline SEED

Never stubs into Wisdom.md. Dedup by URL + content fingerprint.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
HERMESDATA = SCRIPT_DIR.parent
GENE_DIR = HERMESDATA / "skill_evo"
STATE_DIR = HERMESDATA / "data" / "inspiration"
EPISODIC_FILE = GENE_DIR / "episodic.jsonl"
WISDOM_FILE = Path(r"D:\PhronesisVault\Research\Hermes-Local-AI-X-Wisdom.md")
TRIAGE = Path(r"D:\PhronesisVault\Operations\Architecture-Idea-Triage.md")
SEEN_FILE = STATE_DIR / "seen_urls.json"
LIST_ID = "2068802754282504617"
LIST_QUERY = (
    f'list:{LIST_ID} (Hermes OR "local AI" OR sovereign OR agent OR skill OR '
    f"Obsidian OR MCP OR memory OR self-improving OR MoE OR vault OR tool)"
)

GENE_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)


def _fp(url: str, text: str) -> str:
    raw = (url or "") + "|" + (text or "")[:400]
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def load_seen() -> set[str]:
    if not SEEN_FILE.exists():
        return set()
    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        return set(data.get("fps") or data.get("urls") or [])
    except Exception:
        return set()


def save_seen(seen: set[str]) -> None:
    SEEN_FILE.write_text(
        json.dumps(
            {
                "updated": datetime.now(timezone.utc).isoformat(),
                "count": len(seen),
                "fps": sorted(seen)[-500:],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def distill_post(post: dict[str, Any]) -> dict[str, Any]:
    text = (post.get("text") or post.get("content") or post.get("extracted") or "").strip()
    url = (post.get("url") or "").strip()
    user = (post.get("user") or post.get("poster") or post.get("author") or "unknown").lstrip("@")
    ts = post.get("timestamp") or post.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if len(ts) > 10:
        ts = ts[:10]

    low = text.lower()
    fit = "High"
    if not any(
        k in low
        for k in (
            "hermes",
            "local",
            "sovereign",
            "agent",
            "obsidian",
            "vault",
            "skill",
            "memory",
            "mcp",
            "self-improv",
        )
    ):
        fit = "Medium"

    actionable = post.get("actionable") or (
        "Map to Hermes: skills, vault indexes, cron hygiene, or local agent patterns. "
        "Add concrete step to Architecture-Idea-Triage if novel."
    )
    evaluation = post.get("evaluation") or {
        "fit": fit,
        "strengths": post.get("strengths") or "Practical agent / local AI signal",
        "weaknesses": post.get("weaknesses") or "May need stack-specific adaptation",
    }

    return {
        "type": "x_wisdom",
        "source": "x_list",
        "list_id": LIST_ID,
        "poster": user,
        "url": url,
        "timestamp": ts,
        "extracted": text[:800],
        "evaluation": evaluation,
        "actionable": actionable,
        "category": post.get("category") or "implementation_idea",
        "fp": _fp(url, text),
        "verified": bool(url and text),
    }


def save_wisdom(entries: list[dict[str, Any]]) -> int:
    WISDOM_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = WISDOM_FILE.read_text(encoding="utf-8") if WISDOM_FILE.exists() else ""
    seen = load_seen()
    new_count = 0
    written: list[dict[str, Any]] = []

    header_needed = not WISDOM_FILE.exists() or "# Hermes" not in existing[:200]
    if header_needed and not existing.strip():
        WISDOM_FILE.write_text(
            "# Hermes / Local AI / Sovereign X-Wisdom Digest\n\n"
            f"**Source:** X list {LIST_ID} (single inspiration cron).\n\n"
            f"**Updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n",
            encoding="utf-8",
        )
        existing = WISDOM_FILE.read_text(encoding="utf-8")

    with WISDOM_FILE.open("a", encoding="utf-8") as f:
        for e in entries:
            if not e.get("extracted") or e["extracted"].startswith("Replace with real"):
                continue
            fp = e.get("fp") or _fp(e.get("url", ""), e.get("extracted", ""))
            if fp in seen:
                continue
            if e.get("url") and e["url"] in existing:
                seen.add(fp)
                continue
            if e["extracted"][:120] in existing:
                seen.add(fp)
                continue

            f.write(f"\n\n## {e['timestamp']} from @{e['poster']}\n")
            if e.get("url"):
                f.write(f"URL: {e['url']}\n")
            f.write(f"Category: {e['category']}\n")
            f.write(f"Content: {e['extracted']}\n")
            ev = e.get("evaluation") or {}
            f.write(
                f"Evaluation: fit={ev.get('fit')}; strengths={ev.get('strengths')}; "
                f"weaknesses={ev.get('weaknesses')}\n"
            )
            f.write(f"Actionable: {e.get('actionable')}\n")
            seen.add(fp)
            written.append(e)
            new_count += 1

    # touch header last pull
    if new_count:
        body = WISDOM_FILE.read_text(encoding="utf-8")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        body = re.sub(
            r"\*\*Updated:\*\*[^\n]*",
            f"**Updated:** {stamp}",
            body,
            count=1,
        )
        if "**Updated:**" not in body[:400]:
            body = body.replace(
                f"**Source:** X list {LIST_ID} (single inspiration cron).\n\n",
                f"**Source:** X list {LIST_ID} (single inspiration cron).\n\n**Updated:** {stamp}\n\n",
                1,
            )
        # strip stub section if present
        body = re.sub(
            r"\n##\s+from @example\nURL: \nCategory: implementation_idea\nContent: Replace with real results\n?",
            "\n",
            body,
        )
        WISDOM_FILE.write_text(body, encoding="utf-8")

    with EPISODIC_FILE.open("a", encoding="utf-8") as f:
        for e in written:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    save_seen(seen)
    return new_count


def append_triage_pointers(entries: list[dict[str, Any]], limit: int = 2) -> int:
    """Light pointer into central triage for highest-fit ideas only."""
    if not TRIAGE.exists():
        return 0
    high = [e for e in entries if (e.get("evaluation") or {}).get("fit") == "High" and e.get("url")]
    if not high:
        return 0
    text = TRIAGE.read_text(encoding="utf-8")
    n = 0
    block = []
    for e in high[:limit]:
        if e["url"] in text:
            continue
        block.append(
            f"\n### X-List seed {e['timestamp']} — @{e['poster']}\n"
            f"- URL: {e['url']}\n"
            f"- Idea: {e['extracted'][:280]}\n"
            f"- Hermes action: {e.get('actionable')}\n"
            f"- Source: list:{LIST_ID}\n"
        )
        n += 1
    if block:
        with TRIAGE.open("a", encoding="utf-8") as f:
            f.write("\n## Auto from extract-wisdom (single inspiration cron)\n")
            f.writelines(block)
    return n


# Curated seed from live x_search 2026-07-12 (agent/cron may replace with fresher)
SEED_POSTS = [
    {
        "user": "RoundtableSpace",
        "url": "https://x.com/RoundtableSpace/status/2076445247983301014",
        "timestamp": "2026-07-12",
        "text": (
            "Obsidian as IDE + vault as codebase + agent as programmer: Ingest (atomic linked notes), "
            "Query (your words + citations), Lint (weekly orphans/stale). Skill files teach Obsidian markdown. "
            "Plain files, no vector DB required for core loop."
        ),
        "actionable": (
            "Keep PhronesisVault 00-INDEX + Vault-Hygiene-6h as Lint; map Ingest to list cron distill; "
            "avoid inventing extra vector layers when markdown maps work."
        ),
        "evaluation": {
            "fit": "High",
            "strengths": "Matches Four Worlds CNS + index maps",
            "weaknesses": "Repo hype may oversell zero-infra",
        },
    },
    {
        "user": "tonysimons_",
        "url": "https://x.com/tonysimons_/status/2076450353105519010",
        "timestamp": "2026-07-12",
        "text": (
            "Hermes (Nous) multi-model / auxiliary models for task specialization — fine-tuned engine feel "
            "for modular agents and skills."
        ),
        "actionable": "Keep Grok parent + phronesis-sovereign grunt split; document MoA in skills not chat.",
        "evaluation": {
            "fit": "High",
            "strengths": "Direct Hermes product signal",
            "weaknesses": "Feature churn",
        },
    },
    {
        "user": "JulianGoldieSEO",
        "url": "https://x.com/JulianGoldieSEO/status/2076441478100898268",
        "timestamp": "2026-07-12",
        "text": (
            "Gemma 4 fully offline on phone (React Native, 4-bit, ~1GB text, function calling, local calendar "
            "from flyer) — pure local/sovereign AI."
        ),
        "actionable": "Track on-device patterns for future mobile twin; not a vault rewrite.",
        "evaluation": {
            "fit": "High",
            "strengths": "Sovereign / local AI",
            "weaknesses": "Different runtime than desktop Hermes",
        },
    },
    {
        "user": "0x0SojalSec",
        "url": "https://x.com/0x0SojalSec/status/2076440462257479940",
        "timestamp": "2026-07-12",
        "text": (
            "Self-improving agent path: long-horizon agents, agent societies / no-person companies, "
            "self-play + models rewriting code in sandboxes."
        ),
        "actionable": "Feed Phase B + skill-evo; keep sandbox walls for RP vs life silo.",
        "evaluation": {
            "fit": "High",
            "strengths": "Self-improve vision",
            "weaknesses": "Abstract vs executable today",
        },
    },
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Single X-list inspiration extractor")
    ap.add_argument("--from-json", type=str, help="Path to JSON list of posts")
    ap.add_argument("--write-seed", action="store_true", help="Write curated SEED_POSTS (real URLs)")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--triage", action="store_true", help="Also append high-fit pointers to Triage")
    ap.add_argument("--list", default=LIST_ID, help="List id (documentation / agent prompt)")
    args = ap.parse_args()

    posts: list[dict[str, Any]] = []
    if args.from_json:
        path = Path(args.from_json)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "posts" in raw:
            raw = raw["posts"]
        if not isinstance(raw, list):
            print("from-json must be a list or {posts: [...]}", file=sys.stderr)
            return 2
        posts = raw[: args.limit * 2]
    elif args.write_seed:
        posts = SEED_POSTS[: args.limit]
    else:
        # no_agent bare run: do NOT write stubs — instruct agent path
        print(
            "extract-wisdom: no --from-json/--write-seed. "
            "Agent cron should x_search then call with --from-json. "
            f"Query hint: {LIST_QUERY}"
        )
        print("[SILENT]")
        return 0

    entries = [distill_post(p) for p in posts]
    entries = [e for e in entries if e.get("verified") or e.get("extracted")]
    new_n = save_wisdom(entries)
    triage_n = append_triage_pointers(entries) if args.triage else 0
    print(
        f"InspirationOK list={args.list} candidates={len(entries)} "
        f"new={new_n} triage={triage_n} file={WISDOM_FILE}"
    )
    if new_n == 0:
        print("[SILENT]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
