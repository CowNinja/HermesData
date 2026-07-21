#!/usr/bin/env python3
"""Conversation → intent queue (dry-run default) — Jarvis spine muscle.

Research (2026-07-18 / refreshed 2026-07-20):
  - Draft→Approve→Execute HITL (Medium/Data Science Collective; human-approval inbox)
  - Action-control over access-control (UnderDefense SOC 2026)
  - Allowlist tool-use (OpenAI/Anthropic agent safety: never free-form shell from chat)
  - Maker ≠ checker + STOP outside body (Codifying-Loops map)
  - Reflexion / evaluator-optimizer: score gate before commit (arXiv 2303.11366)

Contract:
- Default mode is PROPOSE only (dry-run). Never executes tools or mutates stack.
- SCORE GATE maps low intents to known scripts only (allowlist).
- ARM requires exact phrase ARMED_INTENT or env INTENT_ARM=1.
- EXECUTE default is dry-run print; --commit runs allowlisted low-risk only.
- STOP file blocks arm/execute: D:\\HermesData\\state\\intent_queue.STOP
- Writes vault receipt + JSONL for maker/checker audit.

Usage:
  python conversation_intent_queue.py propose --text "Remind me to call mom Sunday"
  python conversation_intent_queue.py propose --text "..." --source discord:1524...
  python conversation_intent_queue.py list
  python conversation_intent_queue.py show <id>
  python conversation_intent_queue.py score <id>
  python conversation_intent_queue.py arm <id> --phrase ARMED_INTENT
  python conversation_intent_queue.py execute <id>            # dry-run
  python conversation_intent_queue.py execute <id> --commit   # allowlisted low only
  python conversation_intent_queue.py reject <id> --reason "out of scope"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from atomic_io import atomic_write_json, atomic_write_text
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore
    atomic_write_text = None  # type: ignore

ROOT = Path(r"D:\HermesData")
SCRIPTS = ROOT / "scripts"
STATE = ROOT / "state"
QUEUE = STATE / "intent_queue.jsonl"
STOP = STATE / "intent_queue.STOP"
VAULT_LOG = Path(r"D:\PhronesisVault\Operations\logs")
LATEST = VAULT_LOG / "intent-queue-latest.json"
EXEC_LOG = VAULT_LOG / "intent-execute-latest.json"
CANON = "Operations/Conversation-to-Action-Ladder-CANONICAL-2026-07-18.md"

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

# Score-gate allowlist: LOW risk only. Fixed argv — never free-form shell.
# Research: OpenAI tool allowlists; Anthropic computer-use sandbox; HITL draft→approve.
ALLOWLIST: Dict[str, Dict[str, Any]] = {
    "stack_snapshot": {
        "patterns": [r"\bstack[_\s-]?snapshot\b", r"\bsnapshot\s+the\s+stack\b"],
        "script": "stack_snapshot.py",
        "argv": [],
        "risk_max": "low",
        "desc": "Measure stack health snapshot (read-only)",
    },
    "six_numbers": {
        "patterns": [r"\bsix[_\s-]?numbers\b", r"\bsilo\s+metrics\b", r"\bkitchen\s+scoreboard\b"],
        "script": "silo_discord_six_numbers.py",
        "argv": [],
        "risk_max": "low",
        "desc": "Silo six_numbers pulse (read-only)",
    },
    "local_offline_check": {
        "patterns": [
            r"\blocal[_\s-]?offline\b",
            r"\blocal[_\s-]?first\s+check\b",
            r"\boffline\s+mode\s+check\b",
        ],
        "script": "local_offline_mode_check.py",
        "argv": ["--no-smoke"],
        "risk_max": "low",
        "desc": "Local-first / hybrid plane check (no GPU smoke)",
    },
    "ensure_single_gateway": {
        "patterns": [
            r"\bensure[_\s-]?single[_\s-]?gateway\b",
            r"\bsingle[_\s-]?gateway\s+check\b",
            r"\bgateway\s+tree\s+ok\b",
        ],
        "script": "ensure_single_gateway.py",
        "argv": [],
        "risk_max": "low",
        "desc": "Tree-aware single gateway ensure (heal path only if down)",
    },
    "canon_conflict_lint": {
        "patterns": [r"\bcanon[_\s-]?conflict\b", r"\blint\s+canons?\b"],
        "script": "canon_conflict_lint.py",
        "argv": [],
        "risk_max": "low",
        "desc": "Read-only canon conflict lint",
    },
    "loop_registry_lint": {
        "patterns": [r"\bloop[_\s-]?registry\b", r"\blint\s+loops?\b"],
        "script": "loop_registry_lint.py",
        "argv": [],
        "risk_max": "low",
        "desc": "Read-only loop registry lint",
    },
    "detective_codify_smoke": {
        "patterns": [r"\bdetective[_\s-]?codify\b", r"\bcodify\s+smoke\b"],
        "script": "detective_codify_smoke.py",
        "argv": [],
        "risk_max": "low",
        "desc": "Detective codify smoke (dry-run)",
    },
    "judgment_backlog_list": {
        "patterns": [r"\bjudgment\s+backlog\b", r"\blist\s+judgment\b"],
        "script": "judgment_backlog.py",
        "argv": ["--list"],
        "risk_max": "low",
        "desc": "List judgment backlog",
    },
    "driver_judgment_pulse": {
        "patterns": [
            r"\bdriver\s+(judgment\s+)?pulse\b",
            r"\bjudgment\s+pulse\b",
            r"\bpulse\s+driver\b",
            r"\bdriver[_\\s-]?judgment[_\\s-]?pulse\b",
        ],
        "script": "driver_judgment_pulse.py",
        "argv": [],
        "risk_max": "low",
        "desc": "Driver/Judgment composite pulse (read-only)",
    },
    "ensure_qwythos_8090": {
        "patterns": [
            r"\bensure\s+qwythos\b",
            r"\brestore\s+qwythos\b",
            r"\bbring\s+up\s+:?8090\b",
            r"\b8090\s+(down|restore|up)\b",
        ],
        "script": "ensure_qwythos_8090.py",
        "argv": [],
        "risk_max": "low",
        "desc": "Ensure Qwythos :8090 up (release+hidden start; cooldown; no gateway kill)",
    },
}


def _write_latest(obj: dict, path: Path = LATEST) -> None:
    VAULT_LOG.mkdir(parents=True, exist_ok=True)
    if atomic_write_json is not None:
        atomic_write_json(path, obj, indent=2, min_bytes=20)
    else:
        path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


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
    if any(x in t for x in ("gateway", "architecture", "hybrid", "judgment", "canon")):
        return "judgment_grok"
    return "jarvis_general"


def score_allowlist(text: str, risk: str) -> Dict[str, Any]:
    """Map intent text → allowlisted script or none. Never invent argv."""
    if risk != "low":
        return {
            "eligible": False,
            "reason": f"risk={risk} not low — allowlist execute blocked",
            "match": None,
        }
    t = text or ""
    hits: List[Tuple[str, Dict[str, Any]]] = []
    for key, meta in ALLOWLIST.items():
        for pat in meta["patterns"]:
            if re.search(pat, t, re.I):
                hits.append((key, meta))
                break
    if not hits:
        return {
            "eligible": False,
            "reason": "no allowlist pattern matched — propose/arm only",
            "match": None,
        }
    if len(hits) > 1:
        return {
            "eligible": False,
            "reason": f"ambiguous allowlist hits: {[h[0] for h in hits]}",
            "match": None,
            "candidates": [h[0] for h in hits],
        }
    key, meta = hits[0]
    script_path = SCRIPTS / str(meta["script"])
    return {
        "eligible": script_path.is_file(),
        "reason": "ok" if script_path.is_file() else f"missing script {script_path}",
        "match": key,
        "script": str(meta["script"]),
        "argv": list(meta.get("argv") or []),
        "desc": meta.get("desc"),
        "script_path": str(script_path),
    }


def dry_run_plan(text: str, risk: str, lane: str, score: Dict[str, Any]) -> dict:
    """Propose steps only — never execute."""
    steps = [
        {"step": 1, "action": "capture", "detail": "intent recorded to queue (this step)"},
        {
            "step": 2,
            "action": "verify",
            "detail": "non-LLM checks: risk class, STOP file, allowlist score",
        },
        {
            "step": 3,
            "action": "score_gate",
            "detail": (
                f"allowlist={score.get('match') or 'none'} "
                f"eligible={score.get('eligible')} ({score.get('reason')})"
            ),
        },
        {"step": 4, "action": "draft", "detail": f"lane={lane} produces dry-run plan only"},
    ]
    if risk == "high":
        steps.append(
            {
                "step": 5,
                "action": "human_gate",
                "detail": "HIGH risk — Jeff explicit approve required; never auto",
            }
        )
    elif risk == "medium":
        steps.append(
            {
                "step": 5,
                "action": "human_gate",
                "detail": "MEDIUM — arm phrase + optional Discord confirm; no allowlist exec",
            }
        )
    else:
        gate = (
            "LOW + allowlisted — arm then execute --commit permitted"
            if score.get("eligible")
            else "LOW — arm still required; execute blocked until allowlist match"
        )
        steps.append({"step": 5, "action": "human_gate", "detail": gate})
    steps.append(
        {
            "step": 6,
            "action": "execute",
            "detail": (
                "Default dry-run. --commit only if armed + low + allowlisted + no STOP"
            ),
        }
    )
    return {
        "mode": "dry_run",
        "risk": risk,
        "lane": lane,
        "score": score,
        "steps": steps,
        "forbidden_until_arm": True,
        "sources": [
            "Draft→Approve→Execute HITL",
            "action-control + tool allowlist",
            "Reflexion score-before-commit",
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
    score = score_allowlist(text, risk)
    plan = dry_run_plan(text, risk, lane, score)
    entry = {
        "id": uuid.uuid4().hex[:12],
        "ts": utc(),
        "status": "proposed",
        "source": args.source or "cli",
        "text": text,
        "risk": risk,
        "lane": lane,
        "score": score,
        "plan": plan,
        "armed": False,
        "executed": False,
        "seal": "intent-queue-v2-score-gate-allowlist",
        "canon": CANON,
    }
    append_entry(entry)
    print(json.dumps(entry, indent=2))
    print(
        f"\nDRY-RUN only. id={entry['id']} risk={risk} lane={lane} "
        f"allowlist={score.get('match') or 'none'} eligible={score.get('eligible')}"
    )
    print(f"Receipt: {LATEST}")
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    rows = load_entries()
    if not rows:
        print("queue empty")
        return 0
    for r in rows[-20:]:
        sc = (r.get("score") or {}).get("match") or "-"
        print(
            f"{r.get('id')}  {r.get('status')}  risk={r.get('risk')}  "
            f"armed={r.get('armed')}  allow={sc}  {(r.get('text') or '')[:50]}"
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    for r in load_entries():
        if r.get("id") == args.id:
            print(json.dumps(r, indent=2))
            return 0
    print(f"not found: {args.id}", file=sys.stderr)
    return 1


def cmd_score(args: argparse.Namespace) -> int:
    found = None
    for r in load_entries():
        if r.get("id") == args.id:
            found = r
            break
    if not found:
        print(f"not found: {args.id}", file=sys.stderr)
        return 1
    score = score_allowlist(found.get("text") or "", found.get("risk") or "low")

    def mut(r: dict) -> dict:
        r["score"] = score
        r["score_ts"] = utc()
        if r.get("plan"):
            r["plan"] = dry_run_plan(
                r.get("text") or "", r.get("risk") or "low", r.get("lane") or "jarvis_general", score
            )
        return r

    updated = update_entry(args.id, mut)
    print(json.dumps(updated, indent=2))
    return 0


def cmd_arm(args: argparse.Namespace) -> int:
    if STOP.is_file():
        print("BLOCKED: intent_queue.STOP present — clear only with Jeff intent", file=sys.stderr)
        return 3
    phrase_ok = (args.phrase or "").strip() == "ARMED_INTENT" or os.environ.get("INTENT_ARM") == "1"
    if not phrase_ok:
        print("BLOCKED: --phrase must be exactly ARMED_INTENT", file=sys.stderr)
        return 3

    def mut(r: dict) -> dict:
        # refresh score at arm time
        score = score_allowlist(r.get("text") or "", r.get("risk") or "low")
        r["score"] = score
        r["status"] = "armed"
        r["armed"] = True
        r["armed_ts"] = utc()
        r["note"] = (
            "Armed. execute --commit only if low+allowlisted; default execute is dry-run."
        )
        return r

    found = update_entry(args.id, mut)
    if not found:
        print(f"not found: {args.id}", file=sys.stderr)
        return 1
    print(json.dumps(found, indent=2))
    elig = (found.get("score") or {}).get("eligible")
    print(f"ARMED. allowlist_eligible={elig}. Next: execute (dry) or execute --commit if eligible.")
    return 0


def cmd_execute(args: argparse.Namespace) -> int:
    if STOP.is_file():
        print("BLOCKED: intent_queue.STOP present", file=sys.stderr)
        return 3
    found = None
    for r in load_entries():
        if r.get("id") == args.id:
            found = r
            break
    if not found:
        print(f"not found: {args.id}", file=sys.stderr)
        return 1
    if not found.get("armed"):
        print("BLOCKED: not armed — arm with ARMED_INTENT first", file=sys.stderr)
        return 3
    risk = found.get("risk") or "low"
    score = score_allowlist(found.get("text") or "", risk)
    commit = bool(args.commit)

    result: Dict[str, Any] = {
        "at": utc(),
        "id": found.get("id"),
        "commit": commit,
        "risk": risk,
        "score": score,
        "status": "blocked",
    }

    if risk != "low":
        result["reason"] = f"risk={risk} never auto-executes"
        _write_latest(result, EXEC_LOG)
        print(json.dumps(result, indent=2))
        return 3
    if not score.get("eligible"):
        result["reason"] = score.get("reason") or "not allowlisted"
        _write_latest(result, EXEC_LOG)
        print(json.dumps(result, indent=2))
        return 3

    cmd = [sys.executable, str(SCRIPTS / score["script"]), *list(score.get("argv") or [])]
    result["cmd"] = cmd

    if not commit:
        result["status"] = "dry_run"
        result["reason"] = "would run allowlisted script; pass --commit to execute"
        _write_latest(result, EXEC_LOG)

        def mut_dry(r: dict) -> dict:
            r["last_execute"] = result
            r["score"] = score
            return r

        update_entry(args.id, mut_dry)
        print(json.dumps(result, indent=2))
        print("DRY-RUN execute only. Re-run with --commit to run allowlisted script.")
        return 0

    # commit path — still only allowlisted low
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(ROOT),
        )
        result["returncode"] = proc.returncode
        result["stdout_tail"] = (proc.stdout or "")[-2000:]
        result["stderr_tail"] = (proc.stderr or "")[-1000:]
        result["status"] = "executed" if proc.returncode == 0 else "exec_failed"
        result["reason"] = "allowlisted subprocess finished"
    except Exception as exc:
        result["status"] = "exec_error"
        result["reason"] = str(exc)

    _write_latest(result, EXEC_LOG)

    def mut_ex(r: dict) -> dict:
        r["score"] = score
        r["executed"] = result.get("status") == "executed"
        r["executed_ts"] = utc()
        r["last_execute"] = result
        if result.get("status") == "executed":
            r["status"] = "executed"
        else:
            r["status"] = "exec_failed"
        return r

    update_entry(args.id, mut_ex)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "executed" else 1


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


def format_discord_card(entry: dict) -> str:
    """≤6-line Discord card for Hermes standing order."""
    score = entry.get("score") or {}
    allow = score.get("match") or "none"
    elig = score.get("eligible")
    text = (entry.get("text") or "").replace("\n", " ").strip()
    if len(text) > 80:
        text = text[:77] + "..."
    lines = [
        f"**Intent** `{entry.get('id')}` · status={entry.get('status')}",
        f"risk=**{entry.get('risk')}** · lane=`{entry.get('lane')}` · allow=`{allow}` eligible={elig}",
        f"text: {text}",
        "Next: Jeff `ARMED_INTENT` → "
        f"`python D:/HermesData/scripts/conversation_intent_queue.py arm {entry.get('id')} --phrase ARMED_INTENT`",
        "Then dry: `execute <id>` · commit low+allowlisted only: `execute <id> --commit`",
        "STOP: `D:/HermesData/state/intent_queue.STOP` · never free-form shell from chat",
    ]
    return "\n".join(lines[:6])


def cmd_card(args: argparse.Namespace) -> int:
    """Propose from last user message + print Discord-ready card (thin Hermes wrapper)."""
    text = (args.text or "").strip()
    if not text and args.file:
        p = Path(args.file)
        if not p.is_file():
            print(f"ERROR: file not found: {p}", file=sys.stderr)
            return 2
        text = p.read_text(encoding="utf-8", errors="replace").strip()
    if not text and not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    if not text:
        print("ERROR: --text, --file, or stdin required", file=sys.stderr)
        return 2

    # reuse propose path
    class NS:
        pass

    ns = NS()
    ns.text = text
    ns.source = args.source or "discord:card"
    # cmd_propose prints full JSON — capture via direct logic
    risk = classify_risk(text)
    lane = suggest_lane(text, risk)
    score = score_allowlist(text, risk)
    plan = dry_run_plan(text, risk, lane, score)
    entry = {
        "id": uuid.uuid4().hex[:12],
        "ts": utc(),
        "status": "proposed",
        "source": ns.source,
        "text": text,
        "risk": risk,
        "lane": lane,
        "score": score,
        "plan": plan,
        "armed": False,
        "executed": False,
        "seal": "intent-queue-v2-score-gate-allowlist",
        "canon": CANON,
        "card": True,
    }
    append_entry(entry)
    card = format_discord_card(entry)
    if args.json:
        print(json.dumps({"entry": entry, "discord_card": card}, indent=2))
    else:
        print(card)
        print(f"\n# id={entry['id']} receipt={LATEST}")
    return 0


def cmd_allowlist(_: argparse.Namespace) -> int:
    out = {
        k: {
            "script": v["script"],
            "argv": v.get("argv"),
            "desc": v.get("desc"),
            "patterns": v.get("patterns"),
        }
        for k, v in ALLOWLIST.items()
    }
    print(json.dumps(out, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Conversation intent queue (dry-run default)")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_prop = sub.add_parser("propose", help="Capture conversation as dry-run intent")
    p_prop.add_argument("--text", required=True)
    p_prop.add_argument("--source", default="cli")
    p_prop.set_defaults(func=cmd_propose)

    p_card = sub.add_parser(
        "card",
        help="Discord thin wrapper: propose from last user message + ≤6-line card",
    )
    p_card.add_argument("--text", default="", help="Last user message text")
    p_card.add_argument("--file", default="", help="Read message text from file")
    p_card.add_argument("--source", default="discord:card")
    p_card.add_argument("--json", action="store_true", help="Full JSON + card")
    p_card.set_defaults(func=cmd_card)

    p_list = sub.add_parser("list", help="List recent intents")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show one intent")
    p_show.add_argument("id")
    p_show.set_defaults(func=cmd_show)

    p_score = sub.add_parser("score", help="Refresh allowlist score gate on an intent")
    p_score.add_argument("id")
    p_score.set_defaults(func=cmd_score)

    p_arm = sub.add_parser("arm", help="Arm intent (execute still gated)")
    p_arm.add_argument("id")
    p_arm.add_argument("--phrase", required=True, help="Must be ARMED_INTENT")
    p_arm.set_defaults(func=cmd_arm)

    p_ex = sub.add_parser("execute", help="Execute armed+allowlisted low intent (default dry-run)")
    p_ex.add_argument("id")
    p_ex.add_argument(
        "--commit",
        action="store_true",
        help="Actually run allowlisted script (default: print only)",
    )
    p_ex.set_defaults(func=cmd_execute)

    p_rej = sub.add_parser("reject", help="Reject intent")
    p_rej.add_argument("id")
    p_rej.add_argument("--reason", default="")
    p_rej.set_defaults(func=cmd_reject)

    p_al = sub.add_parser("allowlist", help="Print score-gate allowlist")
    p_al.set_defaults(func=cmd_allowlist)

    args = p.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
