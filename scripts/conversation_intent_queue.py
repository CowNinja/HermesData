#!/usr/bin/env python3
"""Conversation → intent queue (dry-run default) — Jarvis spine muscle.

Research (2026-07-18): Draft→Approve→Execute HITL (Medium/Data Science Collective);
action-control over access-control (UnderDefense SOC 2026); human approval inbox
patterns (Reddit/Impri); kill-switch outside loop body (Codifying-Loops map).

Contract:
- Default mode is PROPOSE only (dry-run). Never executes tools or mutates stack.
- COMMIT requires --arm with exact phrase ARMED_INTENT or env INTENT_ARM=1.
- STOP file blocks arm: D:\\HermesData\\state\\intent_queue.STOP
- Writes vault receipt + JSONL for maker/checker audit.

Usage:
  python conversation_intent_queue.py propose --text "Remind me to call mom Sunday"
  python conversation_intent_queue.py propose --text "..." --source discord:1524...
  python conversation_intent_queue.py list
  python conversation_intent_queue.py show <id>
  python conversation_intent_queue.py arm <id> --phrase ARMED_INTENT   # marks ready; still no auto-exec
  python conversation_intent_queue.py reject <id> --reason "out of scope"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from atomic_io import atomic_write_json, atomic_write_text
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore
    atomic_write_text = None  # type: ignore

ROOT = Path(r"D:\HermesData")
STATE = ROOT / "state"
QUEUE = STATE / "intent_queue.jsonl"
STOP = STATE / "intent_queue.STOP"
VAULT_LOG = Path(r"D:\PhronesisVault\Operations\logs")
LATEST = VAULT_LOG / "intent-queue-latest.json"
CANON = "Operations/Conversation-to-Action-Ladder-CANONICAL-2026-07-18.md"


def _write_latest(obj: dict) -> None:
    VAULT_LOG.mkdir(parents=True, exist_ok=True)
    if atomic_write_json is not None:
        atomic_write_json(LATEST, obj, indent=2, min_bytes=20)
    else:
        LATEST.write_text(json.dumps(obj, indent=2), encoding="utf-8")

# Risk classes — only low can ever be auto-eligible later; high always human
RISK_KEYWORDS = {
    "high": [
        r"\bpurge\b",
        r"\bdelete\b",
        r"\bwipe\b",
        r"\btaskkill\b",
        r"\brestart gateway\b",
        r"\bsend email\b",
        r"\bwire\b",
        r"\btransfer money\b",
        r"\bproduction\b",
    ],
    "medium": [
        r"\bschedule\b",
        r"\bbook\b",
        r"\breserve\b",
        r"\bpost to\b",
        r"\bdiscord\b",
        r"\bcommit\b",
        r"\bdeploy\b",
        r"\bVW LIVE\b",
        r"\blive index\b",
    ],
}


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def classify_risk(text: str) -> str:
    t = text or ""
    for pat in RISK_KEYWORDS["high"]:
        if re.search(pat, t, re.I):
            return "high"
    for pat in RISK_KEYWORDS["medium"]:
        if re.search(pat, t, re.I):
            return "medium"
    return "low"


def suggest_lane(text: str, risk: str) -> str:
    t = (text or "").lower()
    if any(x in t for x in ("silo", "k:", "k drive", "land", "ocr", "registry")):
        return "silo_kitchen"
    if any(x in t for x in ("jan", "mom", "booksbloom", "wswtr", "tts", "voice")):
        return "jan_library"
    if any(x in t for x in ("8090", "8091", "model", "router", "proxy", "qwythos")):
        return "sovereign_model"
    if any(x in t for x in ("vaultwalker", "vw ", "obsidian", "second brain")):
        return "vaultwalker"
    if risk == "high":
        return "judgment_grok"
    return "jarvis_general"


def dry_run_plan(text: str, risk: str, lane: str) -> dict:
    """Propose steps only — never execute."""
    steps = [
        {"step": 1, "action": "capture", "detail": "intent recorded to queue (this step)"},
        {"step": 2, "action": "verify", "detail": "non-LLM checks: risk class, STOP file, single-writer if stack touch"},
        {"step": 3, "action": "draft", "detail": f"lane={lane} produces dry-run plan only"},
    ]
    if risk == "high":
        steps.append(
            {
                "step": 4,
                "action": "human_gate",
                "detail": "HIGH risk — Jeff explicit approve required; never auto",
            }
        )
    elif risk == "medium":
        steps.append(
            {
                "step": 4,
                "action": "human_gate",
                "detail": "MEDIUM — arm phrase + optional Discord confirm",
            }
        )
    else:
        steps.append(
            {
                "step": 4,
                "action": "human_gate",
                "detail": "LOW — arm phrase still required until score gates exist",
            }
        )
    steps.append(
        {
            "step": 5,
            "action": "execute",
            "detail": "BLOCKED by default. Future: only after arm + score gate + no STOP",
        }
    )
    return {
        "mode": "dry_run",
        "risk": risk,
        "lane": lane,
        "steps": steps,
        "forbidden_until_arm": True,
        "sources": [
            "Draft→Approve→Execute HITL",
            "action-control guardrails",
            CANON,
        ],
    }


def load_entries() -> list[dict]:
    if not QUEUE.is_file():
        return []
    out = []
    for line in QUEUE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def append_entry(entry: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    VAULT_LOG.mkdir(parents=True, exist_ok=True)
    with QUEUE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    _write_latest(entry)


def update_entry(eid: str, mutator) -> dict | None:
    rows = load_entries()
    found = None
    new_rows = []
    for r in rows:
        if r.get("id") == eid:
            found = mutator(dict(r))
            new_rows.append(found)
        else:
            new_rows.append(r)
    if not found:
        return None
    body = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in new_rows)
    if atomic_write_text is not None:
        atomic_write_text(QUEUE, body, min_bytes=1)
    else:
        tmp = QUEUE.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            f.write(body)
        tmp.replace(QUEUE)
    _write_latest(found)
    return found


def cmd_propose(args: argparse.Namespace) -> int:
    text = (args.text or "").strip()
    if not text:
        print("ERROR: --text required", file=sys.stderr)
        return 2
    risk = classify_risk(text)
    lane = suggest_lane(text, risk)
    plan = dry_run_plan(text, risk, lane)
    entry = {
        "id": uuid.uuid4().hex[:12],
        "ts": utc(),
        "status": "proposed",
        "source": args.source or "cli",
        "text": text,
        "risk": risk,
        "lane": lane,
        "plan": plan,
        "armed": False,
        "executed": False,
        "seal": "intent-queue-v1-dry-run-default",
        "canon": CANON,
    }
    append_entry(entry)
    print(json.dumps(entry, indent=2))
    print(f"\nDRY-RUN only. id={entry['id']} risk={risk} lane={lane}")
    print(f"Receipt: {LATEST}")
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    rows = load_entries()
    if not rows:
        print("queue empty")
        return 0
    for r in rows[-20:]:
        print(
            f"{r.get('id')}  {r.get('status')}  risk={r.get('risk')}  "
            f"armed={r.get('armed')}  {(r.get('text') or '')[:60]}"
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    for r in load_entries():
        if r.get("id") == args.id:
            print(json.dumps(r, indent=2))
            return 0
    print(f"not found: {args.id}", file=sys.stderr)
    return 1


def cmd_arm(args: argparse.Namespace) -> int:
    if STOP.is_file():
        print("BLOCKED: intent_queue.STOP present — clear only with Jeff intent", file=sys.stderr)
        return 3
    if (args.phrase or "").strip() != "ARMED_INTENT":
        print("BLOCKED: --phrase must be exactly ARMED_INTENT", file=sys.stderr)
        return 3

    def mut(r: dict) -> dict:
        r["status"] = "armed"
        r["armed"] = True
        r["armed_ts"] = utc()
        r["note"] = "Armed for future execute path; execute still not implemented (dry-run spine)."
        return r

    found = update_entry(args.id, mut)
    if not found:
        print(f"not found: {args.id}", file=sys.stderr)
        return 1
    print(json.dumps(found, indent=2))
    print("ARMED (no auto-execute yet). Next: implement gated executor after score gates.")
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    def mut(r: dict) -> dict:
        r["status"] = "rejected"
        r["armed"] = False
        r["reject_reason"] = args.reason or "rejected"
        r["rejected_ts"] = utc()
        return r

    found = update_entry(args.id, mut)
    if not found:
        print(f"not found: {args.id}", file=sys.stderr)
        return 1
    print(json.dumps(found, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Conversation intent queue (dry-run default)")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_prop = sub.add_parser("propose", help="Capture conversation as dry-run intent")
    p_prop.add_argument("--text", required=True)
    p_prop.add_argument("--source", default="cli")
    p_prop.set_defaults(func=cmd_propose)

    p_list = sub.add_parser("list", help="List recent intents")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show one intent")
    p_show.add_argument("id")
    p_show.set_defaults(func=cmd_show)

    p_arm = sub.add_parser("arm", help="Arm intent (still no execute)")
    p_arm.add_argument("id")
    p_arm.add_argument("--phrase", required=True, help="Must be ARMED_INTENT")
    p_arm.set_defaults(func=cmd_arm)

    p_rej = sub.add_parser("reject", help="Reject intent")
    p_rej.add_argument("id")
    p_rej.add_argument("--reason", default="")
    p_rej.set_defaults(func=cmd_reject)

    args = p.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
