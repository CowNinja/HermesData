#!/usr/bin/env python3
"""No-popup law SSOT -- codify focus-steal prevention for Hermes/Phronesis.

Research / canon:
  Operations/Focus-Steal-Prevention-CANONICAL-2026-07-17.md
  Operations/logs/research-popup-focus-steal-remote-2026-07-21.md
  Operations/logs/Popup-Kill-Implementation-2026-07-21.md

Rules (programmatic):
  1) Schtask entry: pythonw.exe or wscript //B -- never bare python.exe / powershell.exe
  2) Nested children: CREATE_NO_WINDOW (+ FreeConsole for long python.exe workers)
  3) Focus mode STOP files pause land/sprint and trampolines
  4) Dual PS+Hidden twins: prefer Hidden only
  5) Agents must not invent bare-console schtasks

ASCII-only module.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CREATE_NO_WINDOW = 0x08000000
HERMES = Path(r"D:\HermesData")
SCRIPTS = HERMES / "scripts"
STATE = HERMES / "state"
# Silo STOP is operator-owned (silo_ctl). Popup law must not freeze land/depth.
STOPS = [
    STATE / "focus_mode.STOP",
]
LAW_JSON = STATE / "no_popup_law.json"
VAULT_MD = Path(
    r"D:\PhronesisVault\Operations\logs\no-popup-law-latest.md"
)

# Prefer venv pythonw, else 3.11 pythonw
_PYW_CANDIDATES = [
    HERMES / "hermes-agent" / "venv" / "Scripts" / "pythonw.exe",
    Path(r"C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe"),
]


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def pythonw_path() -> str:
    for p in _PYW_CANDIDATES:
        if p.is_file():
            return str(p)
    # last resort: swap current exe
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        alt = exe.with_name("pythonw.exe")
        if alt.is_file():
            return str(alt)
    return str(sys.executable)


def focus_mode_on() -> bool:
    return all(p.is_file() for p in STOPS[:2]) or (STATE / "focus_mode.STOP").is_file()


def ensure_focus_stops(reason: str = "no_popup_law") -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    body = f"{reason} {utc()}\n"
    for p in STOPS:
        p.write_text(body, encoding="utf-8")


def clear_focus_stops() -> None:
    for p in STOPS:
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


# User-level ticks we can disable/enable without Admin.
# 2026-07-26: do NOT quiet Phronesis-*-Hidden ? those are the CREATE_NO_WINDOW
# pythonw entrypoints. Bare Phronesis-Guardian / Bridge (powershell.exe) hang
# under Win11 default-terminal and mint 267014 when force-Ended. Prefer Hidden.
USER_TICKS_QUIET: list[str] = [
    "Hermes_Silent_Green_Pulse",
    "Hermes_Image_Queue_Pulse",
    "Hermes_Silo_Depth_Priority",
    "Hermes_Silo_Autonomous_Watchdog",
    "Hermes_Silo_Overnight_Watchdog",
    "Hermes_Silo_Travel_Heartbeat",
    "Hermes_Gateway_Watchdog_5m",
    "ComfyUI-Gallery-Watchdog",
]

# Keep these ENABLED (user-IL) even under focus/lockdown ? silent pythonw path.
USER_TICKS_KEEP_ENABLED: list[str] = [
    "Phronesis-Guardian-Hidden",
    "Phronesis-Grok-Direct-Bridge-Hidden",
    "Hermes_Popup_Storm_Suppress",
    "Hermes_Popup_Focus_Guard",
    "Hermes_Popup_End_Flashy_30m",
]

# Admin-owned flashy entries (document + trampoline no-op only)
ADMIN_FLASY: list[str] = [
    "Phronesis-Guardian",
    "Phronesis-Grok-Direct-Bridge",
    "Phronesis-Grok-Hermes-Loop",
    "Phronesis-Image-Rider",
    "Phronesis-Start-At-Logon",
    "cua-driver-serve",  # Cua AgentCursorOverlay logon serve (Highest; needs Admin disable)
]

BAD_ENTRY_RE = re.compile(
    r"(?:^|[\\/\s\"'])(?:python\.exe|powershell\.exe|pwsh\.exe|cmd\.exe)(?:\s|\"|$)",
    re.I,
)


def is_bad_schtask_action(action: str) -> bool:
    a = action or ""
    al = a.lower()
    if "pythonw.exe" in al and "launch_hidden" in al:
        return False
    if "pythonw.exe" in al and "powershell.exe" not in al:
        return False
    if re.search(r"wscript(\.exe)?\s+//B", a, re.I):
        return False
    if BAD_ENTRY_RE.search(a):
        return True
    if re.search(r"(^|[\\/\s\"'])python\.exe", a, re.I) and "pythonw" not in al:
        return True
    return False


def schtasks_change(name: str, enable: bool) -> bool:
    flag = "/ENABLE" if enable else "/DISABLE"
    try:
        r = subprocess.run(
            ["schtasks", "/Change", "/TN", name, flag],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return r.returncode == 0
    except Exception:
        return False


def quiet_user_ticks() -> dict[str, bool]:
    out = {n: schtasks_change(n, enable=False) for n in USER_TICKS_QUIET}
    # Always re-assert silent Hidden twins + protectors stay on
    for n in USER_TICKS_KEEP_ENABLED:
        out[f"keep:{n}"] = schtasks_change(n, enable=True)
    return out


def resume_user_ticks() -> dict[str, bool]:
    out = {n: schtasks_change(n, enable=True) for n in USER_TICKS_QUIET}
    for n in USER_TICKS_KEEP_ENABLED:
        out[f"keep:{n}"] = schtasks_change(n, enable=True)
    return out


def ensure_hidden_twins_enabled() -> dict[str, bool]:
    """Prefer pythonw Hidden twins over bare powershell.exe parents."""
    return {n: schtasks_change(n, enable=True) for n in USER_TICKS_KEEP_ENABLED}


def schtask_action_line(name: str) -> str:
    """Best-effort Task To Run for a task name."""
    try:
        r = subprocess.run(
            ["schtasks", "/Query", "/TN", name, "/V", "/FO", "LIST"],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        for line in (r.stdout or "").splitlines():
            if line.strip().lower().startswith("task to run:"):
                return line.split(":", 1)[-1].strip()
    except Exception:
        pass
    return ""


def audit_named(names: list[str]) -> list[dict[str, Any]]:
    rows = []
    for n in names:
        act = schtask_action_line(n)
        if not act:
            continue
        rows.append(
            {
                "task": n,
                "action": act[:240],
                "bad": is_bad_schtask_action(act),
            }
        )
    return rows


def write_law_state(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    rep: dict[str, Any] = {
        "at": utc(),
        "version": "1.0.0",
        "focus_mode": focus_mode_on(),
        "stops": {p.name: p.is_file() for p in STOPS},
        "pythonw": pythonw_path(),
        "rules": [
            "schtask entry: pythonw or wscript //B only",
            "nested: CREATE_NO_WINDOW + FreeConsole for python.exe workers",
            "focus STOP files pause land/sprint + trampolines",
            "prefer Hidden twin over PS entry dual",
            "agents must not create bare console schtasks",
        ],
        "user_ticks_quiet": USER_TICKS_QUIET,
        "admin_flashy": ADMIN_FLASY,
        # Travel stub bat is no-UAC; permanent kill is REAL.bat (elevated once when home).
        "admin_one_shot": str(SCRIPTS / "ops" / "Run-Popup-Kill-Admin-Once.REAL.bat"),
        "admin_one_shot_stub_travel": str(SCRIPTS / "ops" / "Run-Popup-Kill-Admin-Once.bat"),
        "enforce_cli": f'{pythonw_path()} "{SCRIPTS / "popup_focus_enforce.py"}"',
    }
    if extra:
        rep.update(extra)
    STATE.mkdir(parents=True, exist_ok=True)
    LAW_JSON.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    lines = [
        f"# No-popup law - {rep['at']}",
        "",
        f"focus_mode=**{rep['focus_mode']}** pythonw=`{rep['pythonw']}`",
        "",
        "## Rules",
    ]
    for r in rep["rules"]:
        lines.append(f"- {r}")
    lines += ["", "## Stops", f"```json", json.dumps(rep["stops"], indent=2), "```", ""]
    if extra:
        lines += ["## Extra", "```json", json.dumps(extra, indent=2)[:3000], "```", ""]
    VAULT_MD.parent.mkdir(parents=True, exist_ok=True)
    VAULT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rep
