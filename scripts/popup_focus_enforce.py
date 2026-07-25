#!/usr/bin/env python3
"""Recurring no-popup enforcer (Hermes codify -- user-level, pythonw-safe).

Runs as schtask Hermes_Popup_Focus_Guard:
  - If focus STOP files present: re-disable user kitchen ticks; refresh law state
  - Always: audit known flashy names; write receipt
  - Never starts gateway/forge kill; never needs Admin for user ticks
  - Admin flashy tasks: trampolines already no-op under STOP; report residual

ASCII-only.

Usage:
  pythonw popup_focus_enforce.py
  pythonw popup_focus_enforce.py --json
  pythonw popup_focus_enforce.py --register-task
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
sys.path.insert(0, str(SCRIPTS))

from no_popup_law import (  # noqa: E402
    ADMIN_FLASY,
    CREATE_NO_WINDOW,
    USER_TICKS_QUIET,
    audit_named,
    focus_mode_on,
    pythonw_path,
    quiet_user_ticks,
    write_law_state,
)

STATE = Path(r"D:\HermesData\state\popup_focus_enforce_latest.json")
VAULT = Path(
    r"D:\PhronesisVault\Operations\logs\popup-focus-enforce-latest.md"
)
TASK_NAME = "Hermes_Popup_Focus_Guard"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def register_task() -> dict:
    """Register/refresh user-level enforcer every 15 minutes via pythonw."""
    pyw = pythonw_path()
    script = str(SCRIPTS / "popup_focus_enforce.py")
    # Delete old if present
    subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True,
        text=True,
        creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    # schtasks /Create with pythonw -- 15 min, indefinite via /RI /DU
    # /SC MINUTE /MO 15 /RI 15 works with /DU 9999:00
    cmd = [
        "schtasks",
        "/Create",
        "/TN",
        TASK_NAME,
        "/TR",
        f'"{pyw}" "{script}"',
        "/SC",
        "MINUTE",
        "/MO",
        "15",
        "/F",
        "/RL",
        "LIMITED",
    ]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    ok = r.returncode == 0
    return {
        "ok": ok,
        "rc": r.returncode,
        "out": ((r.stdout or "") + (r.stderr or ""))[-500:],
        "task": TASK_NAME,
        "tr": f"{pyw} {script}",
    }


def _stop_cua_and_flashy() -> dict:
    """While focus_mode is on, keep Cua overlay and flashy schtasks down."""
    out: dict = {}
    try:
        from focus_mode import _stop_cua_driver, _end_admin_flashy_tasks

        out["cua"] = _stop_cua_driver()
        out["ended"] = _end_admin_flashy_tasks()
    except Exception as exc:
        out["error"] = str(exc)[:200]
    # Dedup Forge launch.py (VRAM/popup thrash)
    try:
        import re

        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "$f=Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                    "Where-Object { $_.CommandLine -match 'forge\\\\launch\\.py' }; "
                    "if($f.Count -gt 1){ $k=($f|Sort-Object ProcessId|Select-Object -First 1).ProcessId; "
                    "$f|Where-Object{$_.ProcessId -ne $k}|ForEach-Object{Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue; "
                    "\"killed:$($_.ProcessId)\"} }"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        out["forge_dedup"] = ((r.stdout or "") + (r.stderr or ""))[-200:]
    except Exception as exc:
        out["forge_dedup_err"] = str(exc)[:120]
    return out


def enforce() -> dict:
    focused = focus_mode_on()
    quiet = {}
    cua_flash = {}
    if focused:
        quiet = quiet_user_ticks()
        cua_flash = _stop_cua_and_flashy()
    audit_user = audit_named(USER_TICKS_QUIET)
    # Include Cua serve task in admin audit surface
    extra_admin = list(ADMIN_FLASY) + ["cua-driver-serve"]
    audit_admin = audit_named(extra_admin)
    bad_user = [a for a in audit_user if a.get("bad")]
    bad_admin = [a for a in audit_admin if a.get("bad")]
    rep = {
        "at": utc(),
        "version": "1.1.0",
        "focus_mode": focused,
        "quiet_user_ticks": quiet,
        "cua_and_flashy": cua_flash,
        "audit_user": audit_user,
        "audit_admin": audit_admin,
        "bad_user_n": len(bad_user),
        "bad_admin_n": len(bad_admin),
        "bad_admin": bad_admin,
        "policy": {
            "user_ticks_while_focus": "disabled",
            "cua": "stop while focus_mode; on-demand for computer_use only",
            "admin_residual": "trampoline no-op under STOP; elevate bat for permanent rebind",
            "admin_bat": r"D:\HermesData\scripts\ops\Run-Popup-Kill-Admin-Once.bat",
            "cua_task": "cua-driver-serve",
        },
    }
    STATE.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    write_law_state({"enforce": rep})
    lines = [
        f"# Popup focus enforce - {rep['at']}",
        "",
        f"focus_mode=**{focused}** bad_user={len(bad_user)} bad_admin={len(bad_admin)}",
        "",
        "## Quiet results",
        "```json",
        json.dumps(quiet, indent=2)[:1500],
        "```",
        "",
        "## Admin residual (needs elevate for permanent fix)",
    ]
    for a in bad_admin:
        lines.append(f"- `{a.get('task')}`: `{(a.get('action') or '')[:160]}`")
    VAULT.parent.mkdir(parents=True, exist_ok=True)
    VAULT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--register-task",
        action="store_true",
        help="Create/refresh Hermes_Popup_Focus_Guard (pythonw every 15m)",
    )
    args = ap.parse_args()
    if args.register_task:
        reg = register_task()
        print(json.dumps(reg, indent=2))
        # still enforce once
        rep = enforce()
        if args.json:
            print(json.dumps(rep, indent=2)[:3000])
        return 0 if reg.get("ok") else 1
    rep = enforce()
    print(json.dumps(rep if args.json else {
        "at": rep["at"],
        "focus_mode": rep["focus_mode"],
        "bad_user_n": rep["bad_user_n"],
        "bad_admin_n": rep["bad_admin_n"],
        "quiet_ok": sum(1 for v in (rep.get("quiet_user_ticks") or {}).values() if v),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
