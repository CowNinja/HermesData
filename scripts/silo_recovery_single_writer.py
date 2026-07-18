#!/usr/bin/env python3
"""One-shot data-silo recovery: kill multi-writers, start single continuous (+ optional sprint).

Safe for travel: CREATE_NO_WINDOW / wscript detach. Does not touch gateway.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
STATE = Path(r"D:\HermesData\state")
LOG = Path(r"D:\PhronesisVault\Operations\logs\silo-recovery-single-writer-latest.md")
CREATE_NO_WINDOW = 0x08000000

# Patterns that must not dual-run (land multi-writer risk)
KILL_MARKERS = (
    "silo_continuous_loop.py",
    "silo_orchestrator_tick.py",
    "silo_autonomous_sprint.py",
    "silo_autonomous_launch.py",
    "silo_focus_land.py",
    "g_to_k_safe_drain.py",
    "g_to_k_drain_autonomous.py",
    "silo_booksbloom_pilot_land.py",
)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_python_cmds() -> list[tuple[int, str]]:
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-Command",
                "Get-CimInstance Win32_Process | Where-Object { "
                "$_.Name -like 'python*' -and $_.CommandLine } | "
                "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except Exception as e:
        return [(-1, f"list_err {e}")]
    out = []
    for line in (r.stdout or "").splitlines():
        if "|" not in line:
            continue
        pid_s, cmd = line.split("|", 1)
        try:
            out.append((int(pid_s.strip()), cmd.strip()))
        except ValueError:
            continue
    return out


def kill_multi_writers() -> list[str]:
    actions = []
    for pid, cmd in list_python_cmds():
        if pid < 0:
            continue
        if any(m in cmd for m in KILL_MARKERS):
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True,
                    timeout=15,
                    creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                actions.append(f"killed {pid}")
            except Exception as e:
                actions.append(f"kill_fail {pid} {e}")
    time.sleep(2.0)
    # clear locks / STOP so recovery can start
    for name in (
        "silo_continuous.lock",
        "silo_continuous.pid",
        "silo_autonomous_sprint.pid",
        "silo_continuous.STOP",
        "silo_autonomous.STOP",
    ):
        p = STATE / name
        if p.is_file():
            try:
                p.unlink()
                actions.append(f"removed {name}")
            except Exception as e:
                actions.append(f"remove_fail {name} {e}")
    return actions


def start_via_wscript(vbs: Path) -> None:
    subprocess.run(
        ["wscript.exe", "//B", str(vbs)],
        timeout=20,
        creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def count_markers() -> dict[str, int]:
    counts: dict[str, int] = {m: 0 for m in KILL_MARKERS}
    for _, cmd in list_python_cmds():
        for m in KILL_MARKERS:
            if m in cmd:
                counts[m] += 1
    return counts


def main() -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    actions = kill_multi_writers()
    # continuous first (single land owner)
    cont_vbs = SCRIPTS / "start_silo_continuous_only_hidden.vbs"
    if cont_vbs.is_file():
        start_via_wscript(cont_vbs)
        actions.append("started continuous_vbs")
    time.sleep(3.0)
    # sprint second (depth; no land multi-write if focus is continuous)
    sprint_vbs = SCRIPTS / "start_silo_sprint_only_hidden.vbs"
    if not sprint_vbs.is_file():
        # create default
        py = r"C:\Users\CowNi\AppData\Local\Programs\Python\Python311\python.exe"
        sprint = str(SCRIPTS / "silo_autonomous_sprint.py")
        sprint_vbs.write_text(
            "Option Explicit\r\n"
            "Dim sh\r\n"
            "Set sh = CreateObject(\"WScript.Shell\")\r\n"
            f'sh.Run """{py}"" ""{sprint}"" --hours 4 --sleep 40 --smoke", 0, False\r\n',
            encoding="ascii",
        )
    start_via_wscript(sprint_vbs)
    actions.append("started sprint_vbs")
    time.sleep(5.0)
    counts = count_markers()
    report = {
        "at": utc(),
        "actions": actions,
        "counts": counts,
        "ok_single_continuous": counts.get("silo_continuous_loop.py", 0) == 1,
        "ok_no_dual_focus": counts.get("silo_focus_land.py", 0) <= 1,
        "ok_no_dual_drain": counts.get("g_to_k_safe_drain.py", 0) <= 1,
    }
    # resolve continuous pid
    cont_pid = None
    for pid, cmd in list_python_cmds():
        if "silo_continuous_loop.py" in cmd:
            cont_pid = pid
            break
    if cont_pid:
        (STATE / "silo_continuous.pid").write_text(str(cont_pid), encoding="utf-8")
        report["continuous_pid"] = cont_pid
    sprint_pid = None
    for pid, cmd in list_python_cmds():
        if "silo_autonomous_sprint.py" in cmd:
            sprint_pid = pid
            break
    if sprint_pid:
        (STATE / "silo_autonomous_sprint.pid").write_text(str(sprint_pid), encoding="utf-8")
        report["sprint_pid"] = sprint_pid

    LOG.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Silo recovery single-writer — {report['at']}",
        "",
        f"- continuous_pid: `{report.get('continuous_pid')}`",
        f"- sprint_pid: `{report.get('sprint_pid')}`",
        f"- ok_single_continuous: **{report['ok_single_continuous']}**",
        f"- ok_no_dual_focus: **{report['ok_no_dual_focus']}**",
        f"- ok_no_dual_drain: **{report['ok_no_dual_drain']}**",
        "",
        "## Counts",
        "```json",
        json.dumps(counts, indent=2),
        "```",
        "",
        "## Actions",
        "```json",
        json.dumps(actions, indent=2),
        "```",
        "",
        "[[Operations/Autonomous-Silo-Runbook-CANONICAL-2026-07-14]]",
        "",
    ]
    LOG.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok_single_continuous"] and report["ok_no_dual_focus"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
