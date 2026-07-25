#!/usr/bin/env python3
"""Ensure at most one Forge launch.py / one listener on :7860 (P4 anti-reentry).

ASCII-only. Safe under focus_mode (CREATE_NO_WINDOW).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\ensure-forge-single-latest.json")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_forge_pids() -> list[tuple[int, str]]:
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -match 'forge\\\\launch\\.py' } | "
        "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=CREATE_NO_WINDOW,
    )
    out: list[tuple[int, str]] = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        pid_s, cl = line.split("|", 1)
        try:
            out.append((int(pid_s), cl[:200]))
        except ValueError:
            pass
    return out


def main() -> int:
    before = list_forge_pids()
    killed: list[int] = []
    kept = None
    if len(before) > 1:
        before_sorted = sorted(before, key=lambda x: x[0])
        kept = before_sorted[0][0]
        for pid, _ in before_sorted[1:]:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    creationflags=CREATE_NO_WINDOW,
                )
                killed.append(pid)
            except Exception:
                pass
    elif len(before) == 1:
        kept = before[0][0]

    after = list_forge_pids()
    rep = {
        "ts": utc(),
        "seal": "ensure-forge-single-p4-2026-07-25",
        "before_n": len(before),
        "after_n": len(after),
        "kept_pid": kept,
        "killed": killed,
        "pass": len(after) <= 1,
        "before": [{"pid": p, "cl": c} for p, c in before],
        "after": [{"pid": p, "cl": c} for p, c in after],
    }
    # Optional: free Comfy weights if both tenants fight (best-effort)
    try:
        sys.path.insert(0, str(Path(r"D:\HermesData\scripts")))
        from image_stack_single_tenant import enforce

        rep["tenant"] = enforce("forge", stop_idle_comfy=False, free_comfy_models=True)
    except Exception as exc:
        rep["tenant_err"] = str(exc)[:200]

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(json.dumps(rep, indent=2))
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
