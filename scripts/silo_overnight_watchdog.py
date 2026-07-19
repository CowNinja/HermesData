#!/usr/bin/env python3
"""Overnight silo watchdog — restart continuous if state stale; never touch gateway.

Safe for Task Scheduler every 15–30 min. $0 LLM.
Always launches continuous with pythonw + CREATE_NO_WINDOW (no focus steal).

Critical: long ticks update heartbeat_at but not cycle `at` until complete.
Never treat an active tick as stale. When restarting, kill the full land tree
so orphan orchestrator/focus_land/drain cannot dual-write the registry.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from windows_subprocess import (  # noqa: E402
    hidden_powershell_command,
    run_hidden,
)

STATE = Path(r"D:\HermesData\state\silo_continuous_state.json")
HEARTBEAT = Path(r"D:\HermesData\state\silo_tick_heartbeat.json")
STOP = Path(r"D:\HermesData\state\silo_continuous.STOP")
PIDF = Path(r"D:\HermesData\state\silo_continuous.pid")
LOG = Path(r"D:\PhronesisVault\Operations\logs\silo-overnight-watchdog-latest.md")
# python.exe + FreeConsole in worker scripts (pythonw breaks piped child workers).
_PY_CANDIDATES = [
    Path(r"C:\Users\CowNi\AppData\Local\Programs\Python\Python311\python.exe"),
    Path(sys.executable),
]
PY = str(next((p for p in _PY_CANDIDATES if p.is_file()), Path(sys.executable)))
SCRIPT = r"D:\HermesData\scripts\silo_continuous_loop.py"
# Long drains legitimately exceed 15m; only restart if NO fresh heartbeat either.
STALE_S = 1800  # 30 min without cycle completion
HEARTBEAT_FRESH_S = 900  # 15 min — tick still progressing

# Full land tree — kill together to prevent multi-writer orphans
LAND_MARKERS = (
    "silo_continuous_loop.py",
    "silo_orchestrator_tick.py",
    "silo_focus_land.py",
    "g_to_k_safe_drain.py",
    "g_to_k_drain_autonomous.py",
)


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    prev = LOG.read_text(encoding="utf-8") if LOG.is_file() else "# overnight watchdog\n\n"
    LOG.write_text(prev + line + "\n", encoding="utf-8")


def _count_marker(marker: str) -> int:
    try:
        r = run_hidden(
            hidden_powershell_command(
                "Get-CimInstance Win32_Process | Where-Object { "
                f"$_.CommandLine -like '*{marker}*' "
                "-and $_.Name -like 'python*' } | Measure-Object | "
                "Select-Object -ExpandProperty Count"
            ),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return int((r.stdout or "0").strip() or "0")
    except Exception:
        return 0


def continuous_running() -> bool:
    return _count_marker("silo_continuous_loop.py") > 0


def dual_land_writers() -> dict[str, int]:
    """Detect multi-writer land storm (SQLite registry risk)."""
    counts = {
        "continuous": _count_marker("silo_continuous_loop.py"),
        "orchestrator": _count_marker("silo_orchestrator_tick.py"),
        "focus_land": _count_marker("silo_focus_land.py"),
        "drain": _count_marker("g_to_k_safe_drain.py"),
    }
    counts["bad"] = int(
        counts["continuous"] > 1
        or counts["focus_land"] > 1
        or counts["drain"] > 1
        or counts["orchestrator"] > 1
    )
    return counts


def kill_land_tree() -> None:
    """Kill continuous + all land workers (prevents dual-writer orphans)."""
    clauses = " -or ".join(
        f"$_.CommandLine -like '*{m}*'" for m in LAND_MARKERS
    )
    run_hidden(
        hidden_powershell_command(
            "Get-CimInstance Win32_Process | Where-Object { "
            "$_.Name -like 'python*' -and $_.CommandLine -and ("
            f"{clauses}"
            ") } | ForEach-Object { "
            "Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        ),
        timeout=90,
    )
    time.sleep(2)
    for name in ("silo_continuous.lock", "silo_continuous.pid"):
        p = Path(r"D:\HermesData\state") / name
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass


def start_continuous() -> int:
    # Do not start a second owner
    if continuous_running():
        return -1
    # Respect STOP — never clear it here (Jeff / operator owns STOP)
    if STOP.is_file():
        return -2
    # Prefer wscript (true detach from Job Objects) so schtasks/Grok shells
    # never kill continuous when the watchdog process exits.
    vbs = Path(r"D:\HermesData\scripts\start_silo_continuous_only_hidden.vbs")
    if not vbs.is_file():
        vbs.write_text(
            'Set sh = CreateObject("WScript.Shell")\r\n'
            f'sh.Run """{PY}"" ""{SCRIPT}"" --max-cycles 0 --force-mode aggressive", 0, False\r\n',
            encoding="ascii",
        )
    run_hidden(
        ["wscript.exe", "//B", str(vbs)],
        timeout=15,
    )
    # Resolve pid after brief settle
    time.sleep(1.0)
    pid = -3
    try:
        r = run_hidden(
            hidden_powershell_command(
                "(Get-CimInstance Win32_Process | Where-Object { "
                "$_.CommandLine -like '*silo_continuous_loop.py*' "
                "-and $_.Name -like 'python*' } | "
                "Select-Object -First 1 -ExpandProperty ProcessId)"
            ),
            capture_output=True,
            text=True,
            timeout=20,
        )
        pid = int((r.stdout or "0").strip().splitlines()[-1])
    except Exception:
        pid = -3
    if pid > 0:
        PIDF.write_text(str(pid), encoding="utf-8")
    return pid


def _parse_iso(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def freshness_seconds() -> tuple[float | None, str]:
    """Best-effort age of last progress signal (lower = fresher)."""
    now = datetime.now(timezone.utc)
    candidates: list[tuple[float, str]] = []
    if STATE.is_file():
        try:
            d = json.loads(STATE.read_text(encoding="utf-8"))
            for key in ("heartbeat_at", "at"):
                if d.get(key):
                    dt = _parse_iso(str(d[key]))
                    if dt:
                        candidates.append(((now - dt).total_seconds(), key))
            # mid-tick phase is healthy if heartbeat exists
            if d.get("phase") == "tick_running" and d.get("heartbeat_at"):
                dt = _parse_iso(str(d["heartbeat_at"]))
                if dt:
                    candidates.append(((now - dt).total_seconds(), "phase_tick_running"))
        except Exception as e:
            log(f"state parse err {e}")
    if HEARTBEAT.is_file():
        try:
            hb = json.loads(HEARTBEAT.read_text(encoding="utf-8"))
            if hb.get("at"):
                dt = _parse_iso(str(hb["at"]))
                if dt:
                    candidates.append(((now - dt).total_seconds(), "tick_heartbeat"))
        except Exception:
            pass
        try:
            mtime_age = time.time() - HEARTBEAT.stat().st_mtime
            candidates.append((mtime_age, "tick_heartbeat_mtime"))
        except Exception:
            pass
    if not candidates:
        return None, "none"
    age, src = min(candidates, key=lambda x: x[0])
    return age, src


def _list_marker_pids(marker: str) -> list[int]:
    try:
        r = run_hidden(
            hidden_powershell_command(
                "Get-CimInstance Win32_Process | Where-Object { "
                f"$_.CommandLine -like '*{marker}*' "
                "-and $_.Name -like 'python*' } | "
                "Select-Object -ExpandProperty ProcessId"
            ),
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = []
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                out.append(int(line))
        return out
    except Exception:
        return []


def prune_excess_drains() -> list[int]:
    """If multiple drains, keep oldest PID and kill the rest (soft dual fix).

    Prefer this over full land-tree restart when continuous heartbeat is fresh —
    full restart interrupts a healthy multi-hour Google_Backups wave.
    """
    pids = _list_marker_pids("g_to_k_safe_drain.py")
    if len(pids) <= 1:
        return []
    # Keep lowest PID as proxy for oldest; kill others
    keep = min(pids)
    killed = []
    for p in pids:
        if p == keep:
            continue
        try:
            from windows_subprocess import kill_process_tree

            kill_process_tree(p)
            killed.append(p)
        except Exception:
            run_hidden(
                hidden_powershell_command(
                    f"Stop-Process -Id {p} -Force -ErrorAction SilentlyContinue"
                ),
                timeout=30,
            )
            killed.append(p)
    return killed


def main() -> int:
    if STOP.is_file():
        log("STOP file present — no restart")
        return 0
    # Dual-writer gate first (research: SQLite = one writer; orphans from parent-only kill)
    dual = dual_land_writers()
    if dual.get("bad"):
        # Soft path: only excess drains, continuous heartbeat fresh → prune not thrash
        age, src = freshness_seconds()
        only_drain = (
            dual.get("drain", 0) > 1
            and dual.get("continuous", 0) <= 1
            and dual.get("orchestrator", 0) <= 1
            and dual.get("focus_land", 0) <= 1
        )
        if only_drain and continuous_running() and age is not None and age < HEARTBEAT_FRESH_S:
            killed = prune_excess_drains()
            log(
                f"soft_prune_excess_drains killed={killed} kept_oldest dual_was={dual} "
                f"age={int(age)}s src={src}"
            )
            # re-check
            dual2 = dual_land_writers()
            if not dual2.get("bad"):
                return 0
            log(f"soft_prune insufficient dual2={dual2} — escalate full tree restart")
        log(
            f"dual_land_writers counts={dual} — kill full land tree then single restart"
        )
        kill_land_tree()
        pid = start_continuous()
        log(f"started pid={pid} after dual-writer cleanup")
        return 0

    age, src = freshness_seconds()
    running = continuous_running()
    # Fresh heartbeat during long tick = healthy (do not restart)
    if running and age is not None and age < HEARTBEAT_FRESH_S:
        log(f"ok running age={int(age)}s src={src} dual={dual}")
        return 0
    if running and age is not None and age < STALE_S:
        log(f"ok running soft-age={int(age)}s src={src} (under hard stale)")
        return 0
    if running and age is not None and age >= STALE_S:
        log(f"stale age={int(age)}s src={src} — kill land tree then single restart")
        kill_land_tree()
    elif not running:
        # Overnight 2026-07-18 lesson: continuous can die while a healthy single
        # focus/drain wave is still copying. Full land-tree cleanup then aborts
        # multi-hour Google_Backups progress. If writers are single and drain/focus
        # is live, only restart continuous — do not kill the active wave.
        healthy_orphan_wave = (
            dual.get("drain", 0) <= 1
            and dual.get("focus_land", 0) <= 1
            and dual.get("orchestrator", 0) <= 1
            and (dual.get("drain", 0) == 1 or dual.get("focus_land", 0) == 1)
        )
        if healthy_orphan_wave:
            log(
                f"not running — start WITHOUT land-tree kill "
                f"(preserve live single drain/focus) dual={dual}"
            )
        else:
            log("not running — start (after orphan land tree cleanup)")
            kill_land_tree()
    else:
        log("running age unknown — leave alone")
        return 0
    pid = start_continuous()
    log(f"started pid={pid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
