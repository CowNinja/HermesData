#!/usr/bin/env python3
"""P2: Start / sample Discord router soak + popup audit snapshot.

Not a full 24h wait ? writes baseline + checklist so overnight soak is measurable.
Receipt: D:\\PhronesisVault\\Operations\\logs\\discord-router-soak-latest.{json,md}
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

VAULT_LOG = Path(r"D:\PhronesisVault\Operations\logs")
PROXY_LOG = VAULT_LOG / "sovereign-proxy.jsonl"
WATCHDOG_LOG = VAULT_LOG / "sovereign-stack-watchdog.jsonl"
POPUP_LOG = VAULT_LOG / "popup-kill-audit-latest.md"
RECEIPT_JSON = VAULT_LOG / "discord-router-soak-latest.json"
RECEIPT_MD = VAULT_LOG / "discord-router-soak-latest.md"
SEAL = "discord-router-soak-p2-2026-07-25"
SOAK_HOURS = 24


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _proxy_health() -> Dict[str, Any]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8091/health", timeout=5) as r:
            return {"up": True, "body": json.loads(r.read().decode())}
    except Exception as e:
        return {"up": False, "error": str(e)}


def _count_markers(path: Path, markers: List[str], tail: int = 3000) -> Dict[str, int]:
    out = {m: 0 for m in markers}
    if not path.is_file():
        return out
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]
    except Exception:
        return out
    for line in lines:
        low = line.lower()
        for m in markers:
            if m.lower() in low:
                out[m] += 1
    return out


def main() -> int:
    start = datetime.now(timezone.utc)
    end = start + timedelta(hours=SOAK_HOURS)
    markers = [
        "proactive_tool_history_flatten",
        "grammar_retry",
        "dispatch_fail",
        "dispatch_ok",
        "failure_class",
        "permanent",
        '"code": 503',
        "local_fail_to_free",
    ]
    health = _proxy_health()
    proxy_hits = _count_markers(PROXY_LOG, markers)
    wd_hits = _count_markers(
        WATCHDOG_LOG,
        ["storm_retriable", "permanent_fail", "grammar_crash", "provider_503"],
        tail=200,
    )

    # Popup / focus-steal residual pointers (existing ops artifacts)
    popup_notes = []
    for p in (
        VAULT_LOG / "no-popup-law-latest.md",
        VAULT_LOG / "popup-kill-audit-latest.md",
        VAULT_LOG / "Popup-Error-Troubleshoot-2026-07-22.md",
    ):
        popup_notes.append({"path": str(p), "exists": p.is_file()})

    receipt = {
        "ts": _utc(),
        "seal": SEAL,
        "soak_start_utc": start.isoformat(),
        "soak_end_utc_target": end.isoformat(),
        "soak_hours": SOAK_HOURS,
        "status": "BASELINE_STARTED",
        "proxy_health": {
            "up": health.get("up"),
            "status": (health.get("body") or {}).get("status") if health.get("up") else None,
            "circuit_8090": ((health.get("body") or {}).get("circuit_breakers") or {}).get("8090"),
        },
        "baseline_proxy_markers_last_3k": proxy_hits,
        "baseline_watchdog_markers_last_200": wd_hits,
        "popup_artifact_check": popup_notes,
        "pass_criteria_at_end": [
            "proxy remains GREEN majority of window",
            "no infinite 503 retry storms (storm_retriable false on watchdog ticks)",
            "grammar_retry rate declining or stable vs baseline; dispatch_ok >> dispatch_fail",
            "no new conhost/llama-server console focus-steal (hidden VBS only)",
            "Discord Hermes turns complete without operator popup spam",
        ],
        "operator_closeout": (
            f"After {SOAK_HOURS}h re-run: python D:\\HermesData\\scripts\\discord_router_soak_snapshot.py --closeout"
        ),
        "notes": [
            "This run records soak START baseline only.",
            "Full 24h wall-clock soak cannot complete inside one cook session.",
        ],
    }

    # Optional closeout mode
    import sys

    if "--closeout" in sys.argv:
        receipt["status"] = "CLOSEOUT_SAMPLE"
        receipt["closeout_proxy_markers_last_3k"] = _count_markers(PROXY_LOG, markers)
        receipt["closeout_watchdog_markers_last_200"] = _count_markers(
            WATCHDOG_LOG,
            ["storm_retriable", "permanent_fail", "grammar_crash", "provider_503", "failure_class_summary"],
            tail=400,
        )
        # Heuristic: fewer 503 markers and health up
        b503 = proxy_hits.get('"code": 503', 0)
        c503 = receipt["closeout_proxy_markers_last_3k"].get('"code": 503', 0)
        receipt["delta_code_503"] = c503 - b503
        receipt["pass_heuristic"] = bool(health.get("up")) and c503 <= b503 + 20

    RECEIPT_JSON.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT_JSON.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    md = [
        f"# Discord Router Soak ? {receipt['status']}",
        "",
        f"- **Start:** {receipt['soak_start_utc']}",
        f"- **Target end:** {receipt['soak_end_utc_target']}",
        f"- **Proxy up:** {receipt['proxy_health'].get('up')} status={receipt['proxy_health'].get('status')}",
        "",
        "## Baseline proxy markers (last 3k lines)",
        "```json",
        json.dumps(proxy_hits, indent=2),
        "```",
        "",
        "## Pass criteria (at closeout)",
    ]
    for c in receipt["pass_criteria_at_end"]:
        md.append(f"- {c}")
    md += ["", f"JSON: `{RECEIPT_JSON}`", "", receipt["operator_closeout"]]
    RECEIPT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
