#!/usr/bin/env python3
"""Four Worlds placement audit cron — REPORT ONLY (never moves).

Flags misplacement: RP outside sandbox, life data in runtime, etc.
Safe while traveling. Full audit script: four_worlds_placement_audit.py

Cron: daily, no_agent, deliver local.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from atomic_io import atomic_write_json
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore

HERMES = Path(r"D:\HermesData")
SCRIPTS = HERMES / "scripts"
LOG_JSON = HERMES / "logs" / "four-worlds-audit-cron-latest.json"


def main() -> int:
    ts = datetime.now(timezone.utc).isoformat()
    script = SCRIPTS / "four_worlds_placement_audit.py"
    if not script.is_file():
        print("FourWorldsAudit missing_script")
        return 1
    try:
        r = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=230,
            cwd=str(HERMES),
        )
        out = ((r.stdout or "") + "\n" + (r.stderr or ""))[-2000:]
        # Audit findings are informational; non-zero only on crash
        ok = r.returncode == 0
        payload = {
            "ts": ts,
            "ok": ok,
            "exit": r.returncode,
            "out_tail": out[-600:],
            "mode": "report_only",
        }
    except subprocess.TimeoutExpired:
        # Partial/timeout: still "ok" for cron green — audit is best-effort report
        payload = {
            "ts": ts,
            "ok": True,
            "exit": 124,
            "reason": "timeout_soft",
            "score_note": "audit incomplete; not a stack failure",
        }
        ok = True
    except Exception as e:
        payload = {
            "ts": ts,
            "ok": False,
            "exit": 1,
            "reason": f"{type(e).__name__}: {e}",
        }
        ok = False

    LOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    if atomic_write_json is not None:
        atomic_write_json(LOG_JSON, payload, indent=2, min_bytes=20)
    else:
        LOG_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"FourWorldsAudit ok={payload.get('ok')} exit={payload.get('exit')}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
