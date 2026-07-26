#!/usr/bin/env python3
"""Hermes cron wrapper: weekly vault gardener suite (no_agent-safe).

Hermes no_agent outer kill is ~120s. Full weekly suite can exceed that.
Contract: best-effort run inside the window; soft-exit 0 with receipt on
timeout/partial so last_status stays infrastructure-green (Tony: cron as
infra, alert via stdout/logs not false RED).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(r"D:\HermesData")
SUITE = HERMES / "scripts" / "vault_gardener_autonomy_suite.py"
LOG = HERMES / "logs" / "vault-gardener-weekly-wrapper-latest.json"
# Stay under typical no_agent outer kill (~120s)
INNER_TIMEOUT = 100


def main() -> int:
    ts = datetime.now(timezone.utc).isoformat()
    if not SUITE.is_file():
        print(f"MISSING {SUITE}")
        return 1
    try:
        r = subprocess.run(
            [sys.executable, str(SUITE), "--mode", "weekly", "--execute-safe"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=INNER_TIMEOUT,
            cwd=str(HERMES),
        )
        out = ((r.stdout or "") + "\n" + (r.stderr or ""))[-1500:]
        # Suite may return non-zero for residual hard fails; soft for cron green
        # if it produced a payload (real crashes still surface in log).
        soft_ok = r.returncode in (0, 1, 124)
        payload = {
            "ts": ts,
            "wrapper": "vault_gardener_autonomy_weekly",
            "inner_timeout_s": INNER_TIMEOUT,
            "exit": r.returncode,
            "soft_ok": soft_ok,
            "out_tail": out[-800:],
        }
        code = 0 if soft_ok else r.returncode
    except subprocess.TimeoutExpired as e:
        partial = ""
        if e.stdout:
            partial = e.stdout if isinstance(e.stdout, str) else e.stdout.decode("utf-8", "replace")
        payload = {
            "ts": ts,
            "wrapper": "vault_gardener_autonomy_weekly",
            "inner_timeout_s": INNER_TIMEOUT,
            "exit": 124,
            "soft_ok": True,
            "reason": "timeout_soft_under_no_agent_window",
            "out_tail": (partial or "")[-800:],
        }
        code = 0
        print("VaultGardenerWeekly timeout_soft (partial OK for cron green)")
    except Exception as ex:
        payload = {
            "ts": ts,
            "wrapper": "vault_gardener_autonomy_weekly",
            "exit": 1,
            "soft_ok": False,
            "reason": f"{type(ex).__name__}: {ex}",
        }
        code = 1

    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if code == 0 and payload.get("exit") not in (None, 0):
        print(
            f"VaultGardenerWeekly soft_ok exit_inner={payload.get('exit')} "
            f"reason={payload.get('reason', 'softened')}"
        )
    elif code == 0:
        print("VaultGardenerWeekly ok")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
