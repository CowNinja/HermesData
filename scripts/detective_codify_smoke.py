#!/usr/bin/env python3
"""Detective → codify smoke gate (Tier A6 / N2).

After any entity_context / domain_route change, run deterministic domain_for cases.
Default dry-run (report only). --commit writes receipt claiming smoke PASS.

Canon:
  Operations/Detective-Entity-Codify-Loop-CANONICAL-2026-07-11 (step 5)
  Operations/Self-Correcting-Codify-Loops-Safe-Surfaces-CANONICAL-2026-07-18 (A6)
  Operations/Codifying-Loops-Guardrails-Map-2026-07-18 (N2)

Guardrails:
  - non-LLM verify only
  - Friends ≠ Family hard assert on Abigail-class
  - dry-run default; no entity_context writes from this script
  - exit 0 soft when ran; JSON has ok=true/false
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
sys.path.insert(0, str(SCRIPTS))
from domain_route import domain_for  # noqa: E402

try:
    from atomic_io import atomic_write_json, atomic_write_text, atomic_append_jsonl
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore
    atomic_write_text = None  # type: ignore
    atomic_append_jsonl = None  # type: ignore

VAULT_LOG = Path(r"D:\PhronesisVault\Operations\logs\detective-codify-smoke-latest.json")
VAULT_MD = Path(r"D:\PhronesisVault\Operations\logs\detective-codify-smoke-latest.md")
HERMES_TRAJ = Path(r"D:\HermesData\data\self_correcting_loops\detective_codify_smoke.jsonl")

# Grounded in live entity_context.json (2026-07-18 measure)
# expect: exact domain_for result OR allowed set
SMOKE_CASES: list[dict] = [
    {
        "name": "William Wilhelm genealogy notes",
        "path_hint": "Family/BLOOM",
        "expect_contains": "Family",
        "forbid_contains": ["Friends"],
        "note": "Wilhelm → genealogy Family",
    },
    {
        "name": "Abigail Tulis v Commonwealth affidavit",
        "path_hint": "David Tulis folder VA case",
        "expect_contains": "Friends",
        "forbid_contains": ["Family"],
        "note": "Abigail Tulis case party — Friends cohort, not Jeff Family",
    },
    {
        "name": "Rescue Church wifi donation",
        "path_hint": "Spiritual",
        "expect_contains": "Spiritual",
        "forbid_contains": [],
        "note": "Rescue Church org → Spiritual",
    },
    {
        "name": "Andrew Latourette birthday photo",
        "path_hint": "Friends",
        "expect_contains": "Friends",
        "forbid_contains": ["Family"],
        "note": "Latourette friend_rescue_church",
    },
    {
        "name": "LEWZ Last Empire War Z build notes",
        "path_hint": "Projects/games",
        "expect_contains": "Projects",
        "forbid_contains": [],
        "note": "LEWZ → Projects",
    },
    {
        "name": "random unknown scan 12345.pdf",
        "path_hint": "",
        "expect_contains": "_Inbox",
        "forbid_contains": [],
        "note": "unknown → Inbox placeholder path",
    },
]


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_case(case: dict) -> dict:
    got = domain_for(case["name"], case.get("path_hint", ""))
    ok_expect = case["expect_contains"].lower() in got.lower()
    forbid_hit = [
        f for f in case.get("forbid_contains") or [] if f.lower() in got.lower()
    ]
    ok = ok_expect and not forbid_hit
    return {
        "name": case["name"],
        "got": got,
        "expect_contains": case["expect_contains"],
        "forbid_hit": forbid_hit,
        "ok": ok,
        "note": case.get("note", ""),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Detective codify domain_for smoke gate")
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Write PASS/FAIL receipt as committed smoke (still no entity writes)",
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    results = [run_case(c) for c in SMOKE_CASES]
    ok = all(r["ok"] for r in results)
    evidence = "; ".join(
        f"{r['name'][:32]}={'PASS' if r['ok'] else 'FAIL'}→{r['got']}" for r in results
    )
    payload = {
        "at": utc(),
        "ok": ok,
        "mode": "commit" if args.commit else "dry-run",
        "n_cases": len(results),
        "n_pass": sum(1 for r in results if r["ok"]),
        "n_fail": sum(1 for r in results if not r["ok"]),
        "evidence": evidence,
        "results": results,
        "hard_rules": ["Friends≠Family for Abigail-class", "unknown→_Inbox"],
        "canon": [
            "Operations/Detective-Entity-Codify-Loop-CANONICAL-2026-07-11",
            "Operations/Self-Correcting-Codify-Loops-Safe-Surfaces-CANONICAL-2026-07-18",
        ],
        "committed_receipt": bool(args.commit),
    }

    # Always write latest report (measure); commit flag only changes mode label
    VAULT_LOG.parent.mkdir(parents=True, exist_ok=True)
    if atomic_write_json is not None:
        atomic_write_json(VAULT_LOG, payload, indent=2, ensure_ascii=False, min_bytes=20)
    else:
        VAULT_LOG.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = [
        f"# Detective codify smoke",
        f"",
        f"- **at:** {payload['at']}",
        f"- **ok:** {ok}",
        f"- **mode:** {payload['mode']}",
        f"- **pass/fail:** {payload['n_pass']}/{payload['n_fail']}",
        f"- **evidence:** `{evidence}`",
        f"",
        f"## Cases",
    ]
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        md.append(f"- [{mark}] `{r['name']}` → `{r['got']}` — {r['note']}")
    md += [
        f"",
        f"## Vault links",
        f"- [[Operations/Detective-Entity-Codify-Loop-CANONICAL-2026-07-11]]",
        f"- [[Operations/Self-Correcting-Codify-Loops-Safe-Surfaces-CANONICAL-2026-07-18]]",
        f"- [[Operations/Codifying-Loops-Guardrails-Map-2026-07-18]]",
        f"",
    ]
    md_body = "\n".join(md)
    if atomic_write_text is not None:
        atomic_write_text(VAULT_MD, md_body, min_bytes=20)
    else:
        VAULT_MD.write_text(md_body, encoding="utf-8")

    if args.commit:
        HERMES_TRAJ.parent.mkdir(parents=True, exist_ok=True)
        if atomic_append_jsonl is not None:
            atomic_append_jsonl(HERMES_TRAJ, payload)
        else:
            with HERMES_TRAJ.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    print(
        f"DETECTIVE_SMOKE ok={ok} pass={payload['n_pass']}/{payload['n_cases']} "
        f"mode={payload['mode']} log={VAULT_LOG}"
    )
    if args.json:
        print(json.dumps({k: v for k, v in payload.items() if k != "results"}, indent=2))
    # Soft exit 0 when script ran; callers read ok field. Nonzero only if --strict
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
