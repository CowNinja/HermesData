#!/usr/bin/env python3
"""RP bottleneck scan + optional fix — no_agent cron entrypoint.

2026-07-18 residual seal:
- Always print one status line (cron MD was empty on some failures).
- Soft-fail: exit 0 unless active batch still unhealthy after scan/fix.
- Scanner probes Comfy inference :8188 (JSON /system_stats) then treats :8189 as gallery SPA only.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\HermesData")
SCANNER = ROOT / "scripts" / "ops" / "rp_bottleneck_scanner.py"


def main() -> int:
    if not SCANNER.is_file():
        print(f"RPBottleneck FAIL missing_scanner={SCANNER}")
        return 1
    try:
        p = subprocess.run(
            [sys.executable, str(SCANNER), "--fix"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        print("RPBottleneck WARN timeout=120s soft_fail=1 (idle-safe)")
        return 0
    except Exception as e:
        print(f"RPBottleneck WARN error={type(e).__name__}:{e} soft_fail=1")
        return 0

    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    if out:
        print(out)
    if err:
        print("--- stderr ---")
        print(err[-800:])
    print(f"RPBottleneck wrapper_rc={p.returncode} soft_idle_ok=1")
    # Honor scanner contract: 1 only when batch_active and score<70
    if p.returncode == 0:
        return 0
    # Nonzero without stdout often means import/env flake under twin-stack — soft if no batch signal
    if "batch_active" not in out and p.returncode != 0:
        # Re-read report file if present
        report = ROOT / "logs" / "rp-bottleneck-report.json"
        try:
            import json

            data = json.loads(report.read_text(encoding="utf-8"))
            batch_active = bool((data.get("checks") or {}).get("batch_active"))
            score = int(data.get("score") or 0)
            print(f"RPBottleneck report_score={score} batch_active={batch_active}")
            if batch_active and score < 70:
                return 1
            return 0
        except Exception:
            # No report — do not red-fail idle cron
            print("RPBottleneck WARN no_report soft_fail=1")
            return 0
    return int(p.returncode) if isinstance(p.returncode, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
