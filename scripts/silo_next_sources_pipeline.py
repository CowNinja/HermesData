#!/usr/bin/env python3
"""Next-sources dry pipeline — probe + plan only (never land without --apply + Jeff intent).

Reads config/next_sources_rules.json. Writes receipt + machine plan JSON.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

RULES = Path(r"D:/HermesData/config/next_sources_rules.json")
OUT_JSON = Path(r"D:/HermesData/state/next_sources_plan.json")
RECEIPT = Path(r"D:/PhronesisVault/Operations/logs/silo-next-sources-probe-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def probe_root(root: str, max_files: int = 50) -> dict:
    p = Path(root)
    if not p.exists():
        return {"root": root, "exists": False, "sample_files": 0}
    n = 0
    if p.is_dir():
        try:
            for i, f in enumerate(p.rglob("*")):
                if f.is_file():
                    n += 1
                if i >= max_files * 20 or n >= max_files:
                    break
        except Exception as e:
            return {"root": root, "exists": True, "error": str(e)[:120], "sample_files": n}
    elif p.is_file():
        n = 1
    return {"root": root, "exists": True, "sample_files": n}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--apply",
        action="store_true",
        help="RESERVED — refuses unless SILIO_NEXT_SOURCE_APPLY=1 and Jeff phrase file present",
    )
    args = ap.parse_args()
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    sources = []
    for s in rules.get("order") or []:
        probes = [probe_root(r) for r in s.get("roots") or []]
        any_ok = any(p.get("exists") for p in probes)
        sources.append(
            {
                "id": s.get("id"),
                "label": s.get("label"),
                "class": s.get("class"),
                "ready_present": any_ok,
                "probes": probes,
                "notes": s.get("notes"),
                "land_allowed": False,  # always false until explicit arming
            }
        )
    plan = {
        "at": utc(),
        "doctrine": rules.get("doctrine"),
        "locked_rules": rules.get("locked_rules"),
        "sources": sources,
        "apply_requested": bool(args.apply),
        "apply_executed": False,
        "reason": "dry-run only — land requires Jeff green light",
    }
    if args.apply:
        plan["reason"] = "REFUSED: next-source land not armed in this codification wave"
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    lines = [
        f"# Next-sources probe — {plan['at']}",
        "",
        "| Source | Present | Notes |",
        "|--------|:-------:|-------|",
    ]
    for s in sources:
        lines.append(
            f"| {s['id']} | {'YES' if s['ready_present'] else 'no'} | {s.get('notes') or ''} |"
        )
    lines += [
        "",
        "**No land.** Copy-first rules locked. See `config/next_sources_rules.json`.",
        f"Plan JSON: `{OUT_JSON}`",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"sources": [{k: s[k] for k in ('id','ready_present')} for s in sources], "receipt": str(RECEIPT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
