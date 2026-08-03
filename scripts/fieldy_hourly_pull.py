#!/usr/bin/env python3
"""fieldy_hourly_pull.py - No-agent Fieldy pull (path fixed 2026-08-03).

Prefers Research/Fieldy scripts. Falls back to legacy user path.
Uses FIELDY_API_KEY from env/bws via fieldy_api when PS1 lacks key.

Called by cron with no_agent: True. Silent on success empty; errors on fail.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

POWERSHELL = "powershell.exe"
CANDIDATES = [
    Path(r"D:\PhronesisVault\Research\Fieldy\scripts\pull_recent.ps1"),
    Path(r"D:\PhronesisVault\Research\Fieldy\scripts\pull_recent_2h.ps1"),
    Path(r"C:\Users\CowNi\fieldy\Fieldy-RecentPull.ps1"),
]


def main() -> int:
    script = next((p for p in CANDIDATES if p.is_file()), None)
    if script is None:
        # Python API dry path if key present
        py = Path(r"D:\HermesData\scripts\fieldy_api.py")
        if py.is_file():
            from datetime import datetime, timedelta, timezone

            end = datetime.now(timezone.utc)
            start = end - timedelta(hours=24)
            r = subprocess.run(
                [
                    sys.executable,
                    str(py),
                    "dry-sync",
                    "--start",
                    start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "--end",
                    end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if r.returncode != 0:
                print("FIELDY PYTHON PULL FAILED")
                if r.stdout:
                    print(r.stdout.strip()[:1500])
                if r.stderr:
                    print(r.stderr.strip()[:500])
                return r.returncode
            # only print if error-like
            out = (r.stdout or "").strip()
            if "missing_api_key" in out or '"ok": false' in out.lower():
                print(out[:1500])
                return 2
            return 0
        print("CRITICAL: No Fieldy pull script found")
        return 1

    env = os.environ.copy()
    # try hydrate key into env for PS1 Resolve-FieldyApiKey
    try:
        sys.path.insert(0, str(Path(r"D:\HermesData\scripts")))
        from fieldy_api import load_api_key

        k = load_api_key()
        if k:
            env["FIELDY_API_KEY"] = k
    except Exception:
        pass

    cmd = [
        POWERSHELL,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
    ]
    # pull_recent.ps1 may accept -HoursBack
    if script.name.startswith("pull_recent"):
        cmd.extend(["-HoursBack", "2", "-IncludeTranscriptions"])

    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(script.parent),
        env=env,
    )
    if r.returncode == 0:
        if (r.stdout or "").strip():
            print(r.stdout.strip()[:2000])
        return 0
    print(f"FIELDY PULL FAILED (exit {r.returncode}) script={script}")
    if r.stdout:
        print(r.stdout.strip()[:1500])
    if r.stderr:
        print(r.stderr.strip()[:500])
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
