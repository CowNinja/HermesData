#!/usr/bin/env python3
"""Autonomous entity mining for silo routing lexicon.

1) Scan filenames (and optional light text) for person/org candidates
2) Cluster / count mentions
3) Rule + optional local AI role guess
4) Auto-promote high-confidence professional entities into entity_context.json
5) Write thin Jeff review queue for sensitive/unclear roles

No deletes. Local AI only if --ai. No Grok.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

POLICY = Path(r"D:\HermesData\config\entity_mining_policy.json")
ENTITY = Path(r"D:\HermesData\config\entity_context.json")
QUEUE = Path(r"D:\PhronesisVault\Operations\logs\entity-review-queue-latest.md")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\entity-mine-latest.md")
JSON_OUT = Path(r"D:\HermesData\Backups\entity-mine-latest.json")
GRUNT = Path(r"D:\HermesData\scripts\grunt_local.py")
SCRIPTS = Path(r"D:\HermesData\scripts")
SMOKE = SCRIPTS / "detective_codify_smoke.py"

STOP = {
    "the", "and", "for", "with", "from", "this", "that", "your", "have", "will",
    "file", "copy", "page", "pages", "document", "google", "drive", "sheet",
    "docs", "untitled", "template", "share", "online", "resources", "table",
    "format", "walkthrough", "combined", "groomed", "content", "required",
    "discord", "summary", "values", "common", "laboratory", "actual", "readings",
    "jeffrey", "bloom", "jeff",  # self
    "apps", "gift", "speed", "accounts", "windows", "results", "internet",
    "suggestions", "best", "code", "order", "logo", "until", "building",
    "christ", "lord", "jesus", "blessed", "father", "mother",  # scripture noise
    "gmail", "facebook", "microsoft", "amazon", "google", "linkedin",
    "threaded", "variants", "found", "speech", "recognition", "division",
    "front", "door", "dirty", "things", "moan", "during", "breakdown",
    "create", "profile", "badge", "trading", "assistant", "seller", "contract",
    "last", "empire", "free", "email", "search", "secure", "messaging",
    "home", "use", "program", "invoice", "posts", "commented",
}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def scan_names(roots: list[Path], limit: int = 8000) -> list[str]:
    names: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            names.append(root.name)
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.name.endswith(".meta.json") or ".train." in p.name:
                continue
            if p.name.startswith("."):
                continue
            names.append(p.name)
            if len(names) >= limit:
                return names
    return names


def extract_candidates(name: str, policy: dict) -> list[dict]:
    out: list[dict] = []
    # Dr. Name
    for m in re.finditer(r"(?i)\bdr\.?\s+([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?)", name):
        out.append({"raw": m.group(0), "key": m.group(1).strip().lower(), "hint": "doctor"})
    # USS Name
    for m in re.finditer(r"(?i)\bUSS\s+([A-Z][A-Za-z0-9\-]+)", name):
        out.append({"raw": m.group(0), "key": "uss " + m.group(1).lower(), "hint": "ship"})
    # NAV* tokens
    for m in re.finditer(r"(?i)\b(NAVADMIN|NAVPERS|BUMED|CNIC|NROTC|CJTF[- ]?HOA|SEABEE)\b", name):
        out.append({"raw": m.group(0), "key": m.group(1).lower().replace(" ", "-"), "hint": "navy_command"})
    # Capitalized multi-words (light)
    for m in re.finditer(r"\b([A-Z][a-z]{3,}(?:\s+[A-Z][a-z]{3,}){0,2})\b", name):
        phrase = m.group(1).strip()
        key = phrase.lower()
        if key.split()[0] in STOP or key in STOP:
            continue
        if len(key) < 4:
            continue
        # skip pure months etc
        if key in {"january", "february", "march", "april", "august", "september", "october", "november", "december"}:
            continue
        out.append({"raw": phrase, "key": key, "hint": "unclear_person"})
    # family keywords alone don't create people but flag file
    if re.search(policy.get("patterns", {}).get("family_hint", r"$^"), name):
        out.append({"raw": name, "key": "_family_keyword_", "hint": "family", "file_only": True})
    return out


def rule_role(hint: str, key: str, examples: list[str]) -> tuple[str, float]:
    if hint in {"doctor", "ship", "navy_command"}:
        return hint, 0.9
    blob = " ".join(examples).lower()
    if re.search(r"(?i)\b(md|dmd|do|clinic|endocrin|dental|medical|labs?)\b", blob):
        return "doctor", 0.8
    if re.search(r"(?i)\b(navy|navadmin|uss |ship|command|base)\b", blob):
        return "navy_command", 0.75
    if re.search(r"(?i)\b(attorney|esq|lawyer|law office)\b", blob):
        return "lawyer", 0.85
    if re.search(r"(?i)\b(university|college|school|transcript)\b", blob):
        return "school", 0.8
    if re.search(r"(?i)\b(gas|electric|utility|bank|mortgage)\b", blob):
        return "utility", 0.7
    if re.search(r"(?i)\b(mom|dad|mother|father|sister|brother|wife|husband)\b", blob):
        return "family", 0.7
    return "unclear_person", 0.4


def local_ai_role(key: str, examples: list[str]) -> dict:
    if not GRUNT.exists():
        return {}
    prompt = (
        "Guess entity role for personal archive routing. JSON only: "
        '{"role":"doctor|clinic|navy_command|ship|employer|school|utility|lawyer|family|friend|'
        'significant_other|past_relationship|government|unclear_person","confidence":0-1,"why":"..."}. '
        "Sensitive relationship roles only if clearly evidenced. "
        f"Entity: {key}. Filenames: {examples[:5]}"
    )
    try:
        r = subprocess.run(
            [sys.executable, str(GRUNT), "classify", "--text", prompt[:1400]],
            capture_output=True,
            text=True,
            timeout=90,
        )
        out = (r.stdout or "") + (r.stderr or "")
        a, b = out.find("{"), out.rfind("}") + 1
        if a >= 0 and b > a:
            return json.loads(out[a:b])
    except Exception as e:
        return {"error": str(e)}
    return {"raw": out[-300:] if "out" in dir() else ""}


def promote(entity_doc: dict, key: str, role: str, domain: str, names: list[str]) -> bool:
    people = entity_doc.setdefault("people", [])
    orgs = entity_doc.setdefault("orgs", [])
    bucket = people if role in {
        "doctor", "lawyer", "family", "friend", "significant_other", "past_relationship", "unclear_person"
    } else orgs
    # already?
    for row in bucket:
        existing = {n.lower() for n in (row.get("names") or [])}
        if key in existing or any(n in existing for n in names):
            return False
    bucket.append(
        {
            "names": sorted(set([key] + [n.lower() for n in names]))[:8],
            "role": role,
            "domain": domain,
            "source": "entity_mine_auto",
            "promoted_at": utc(),
        }
    )
    return True


def run_post_promote_smoke() -> dict:
    """N2/A6 gate after entity_context write. Non-LLM. Soft-fail dict always."""
    if not SMOKE.is_file():
        return {"ok": False, "error": "detective_codify_smoke.py missing"}
    try:
        r = subprocess.run(
            [sys.executable, str(SMOKE), "--json"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(SCRIPTS),
        )
        out = (r.stdout or "") + (r.stderr or "")
        a, b = out.find("{"), out.rfind("}") + 1
        if a >= 0 and b > a:
            data = json.loads(out[a:b])
            data["exit_code"] = r.returncode
            return data
        return {"ok": False, "error": "no_json", "raw": out[-400:], "exit_code": r.returncode}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=6000)
    ap.add_argument("--ai", action="store_true", help="Local AI for top unclear candidates only")
    ap.add_argument("--ai-top", type=int, default=8)
    ap.add_argument("--no-promote", action="store_true")
    args = ap.parse_args()
    policy = load_json(POLICY, {})
    role_domain = policy.get("role_to_domain") or {}
    auto = policy.get("auto_promote") or {}
    human_roles = set((policy.get("human_review") or {}).get("roles_always_queue") or [])

    roots = [
        Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo"),
        Path(r"G:\MemoryCard_Backups\Google Drive"),
        Path(r"G:\MemoryCard_Backups\Google Drive(archive)"),
    ]
    # Prefer from-g-drive names on K for speed
    k_fg = list(Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo").rglob("from-g-drive"))
    scan_roots = k_fg[:20] if k_fg else roots
    names = scan_names(scan_roots, limit=args.limit)

    clusters: dict[str, dict] = {}
    for name in names:
        for cand in extract_candidates(name, policy):
            if cand.get("file_only"):
                continue
            key = cand["key"]
            if key in STOP or len(key) < 3:
                continue
            row = clusters.setdefault(
                key,
                {"key": key, "hint": cand["hint"], "count": 0, "examples": [], "raws": set()},
            )
            row["count"] += 1
            if len(row["examples"]) < 8:
                row["examples"].append(name)
            row["raws"].add(cand["raw"])

    # score
    results = []
    for key, row in clusters.items():
        role, conf = rule_role(row["hint"], key, row["examples"])
        results.append(
            {
                "key": key,
                "count": row["count"],
                "role": role,
                "confidence": conf,
                "examples": row["examples"],
                "raws": sorted(row["raws"])[:6],
            }
        )
    results.sort(key=lambda r: (-r["count"], -r["confidence"]))

    # optional AI on unclear top
    if args.ai:
        unclear = [r for r in results if r["role"] == "unclear_person" and r["count"] >= 2][: args.ai_top]
        for r in unclear:
            ai = local_ai_role(r["key"], r["examples"])
            r["ai"] = ai
            if ai.get("role") and float(ai.get("confidence") or 0) >= 0.7:
                r["role"] = ai["role"]
                r["confidence"] = float(ai.get("confidence") or r["confidence"])

    entity_doc = load_json(ENTITY, {"people": [], "orgs": []})
    promoted = []
    queue = []
    min_n = int(auto.get("min_mentions") or 3)
    min_c = float(auto.get("min_confidence") or 0.75)
    allowed = set(auto.get("allowed_roles") or [])

    for r in results:
        role = r["role"]
        conf = float(r["confidence"])
        domain = role_domain.get(role, "Core-Personal/_Inbox")
        r["domain"] = domain
        if role in human_roles or role == "unclear_person":
            if r["count"] >= 2:
                queue.append(r)
            continue
        if (
            not args.no_promote
            and role in allowed
            and r["count"] >= min_n
            and conf >= min_c
        ):
            names_list = [r["key"]] + [x.lower() for x in r.get("raws") or []]
            if promote(entity_doc, r["key"], role, domain, names_list):
                promoted.append(r)

    smoke_result: dict | None = None
    if promoted and not args.no_promote:
        entity_doc["updated"] = utc()[:10]
        save_json(ENTITY, entity_doc)
        # Tier A6 / N2 — domain_for smoke after any promote write
        smoke_result = run_post_promote_smoke()
        if not smoke_result.get("ok"):
            # Do not silent-green a broken lexicon; leave write (audit trail) but flag hard.
            RECEIPT.parent.mkdir(parents=True, exist_ok=True)

    queue = sorted(queue, key=lambda r: -r["count"])[: int((policy.get("human_review") or {}).get("max_queue") or 40)]

    # write queue MD
    q_lines = [
        f"# Entity review queue — {utc()}",
        "",
        "Jeff: only thin queue. Reply like: `entity: richardson = doctor medical` or `entity: skip key`",
        "",
        "| Key | Role guess | n | conf | Domain | Examples |",
        "|-----|------------|--:|-----:|--------|----------|",
    ]
    for r in queue:
        ex = "; ".join(r["examples"][:2]).replace("|", "/")[:60]
        q_lines.append(
            f"| `{r['key']}` | {r['role']} | {r['count']} | {r['confidence']:.2f} | {r['domain']} | {ex} |"
        )
    q_lines += [
        "",
        "## Auto-promoted this run",
        "",
    ]
    if not promoted:
        q_lines.append("_None_")
    else:
        for r in promoted:
            q_lines.append(f"- **{r['key']}** → {r['role']} → `{r['domain']}` (n={r['count']})")
    q_lines += [
        "",
        "Config: `entity_context.json` · policy `entity_mining_policy.json`",
        "[[Operations/Entity-Mining-and-Human-Thin-Queue-CANONICAL-2026-07-10]]",
        "",
    ]
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text("\n".join(q_lines), encoding="utf-8")

    payload = {
        "ts": utc(),
        "files_scanned": len(names),
        "clusters": len(results),
        "promoted": len(promoted),
        "queue": len(queue),
        "top": results[:30],
        "promoted_rows": promoted,
        "queue_rows": queue,
    }
    save_json(JSON_OUT, payload)
    smoke_line = ""
    if smoke_result is not None:
        smoke_line = (
            f"post_promote_smoke ok={smoke_result.get('ok')} "
            f"pass={smoke_result.get('n_pass')}/{smoke_result.get('n_cases')} "
            f"evidence={str(smoke_result.get('evidence') or smoke_result.get('error') or '')[:200]}\n\n"
            f"Smoke: [[Operations/logs/detective-codify-smoke-latest]]\n"
        )
    RECEIPT.write_text(
        f"# Entity mine — {utc()}\n\n"
        f"scanned_files={len(names)} clusters={len(results)} "
        f"promoted={len(promoted)} queue={len(queue)}\n\n"
        f"{smoke_line}"
        f"Queue: [[Operations/logs/entity-review-queue-latest]]\n"
        f"Canon: [[Operations/Detective-Entity-Codify-Loop-CANONICAL-2026-07-11]] "
        f"· [[Operations/Self-Correcting-Codify-Loops-Safe-Surfaces-CANONICAL-2026-07-18]]\n",
        encoding="utf-8",
    )
    payload_out = {
        "files_scanned": len(names),
        "clusters": len(results),
        "promoted": len(promoted),
        "queue": len(queue),
        "queue_md": str(QUEUE),
        "post_promote_smoke": smoke_result,
    }
    print(json.dumps(payload_out, indent=2))
    # exit 2 only when we promoted AND smoke hard-failed (lexicon regression)
    if smoke_result is not None and not smoke_result.get("ok"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
