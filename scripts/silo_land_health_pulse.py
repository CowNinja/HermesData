#!/usr/bin/env python3
"""Silo land health pulse — freeze/crash/dual-writer detector ($0 LLM).

Run every 10–20 min via schtasks or ad-hoc. Never touches gateway.
Writes:
  D:/HermesData/state/silo_land_health_pulse.json
  D:/PhronesisVault/Operations/logs/silo-land-health-pulse-latest.md

Actions (safe, reversible):
  - If drain count > 1 and continuous heartbeat fresh → soft-prune excess drains
  - If continuous missing and no STOP → invoke overnight watchdog start path
  - Never taskkill gateway; never start second continuous if one is alive

Research anchors (2026-07-18):
  - SQLite WAL still single-writer (sqlite.org/wal.html)
  - Windows orphan children after parent timeout → taskkill /T tree kill
  - Heartbeat vs cycle `at` — long ticks are healthy if heartbeat pulses
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
VAULT_LOG = Path(r"D:\PhronesisVault\Operations\logs\silo-land-health-pulse-latest.md")
OUT_JSON = STATE / "silo_land_health_pulse.json"
PREV_JSON = STATE / "silo_land_health_pulse_prev.json"
CONT_STATE = STATE / "silo_continuous_state.json"
TICK_HB = STATE / "silo_tick_heartbeat.json"
STOP = STATE / "silo_continuous.STOP"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

MARKERS = {
    "continuous": "silo_continuous_loop.py",
    "orchestrator": "silo_orchestrator_tick.py",
    "focus_land": "silo_focus_land.py",
    "drain": "g_to_k_safe_drain.py",
    "sprint": "silo_autonomous_sprint.py",
}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _count(marker: str) -> int:
    try:
        from windows_subprocess import hidden_powershell_command, run_hidden

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
        return -1


def _pids(marker: str) -> list[int]:
    try:
        from windows_subprocess import hidden_powershell_command, run_hidden

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


def _parse_iso(s: str):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def six_numbers() -> dict:
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "silo_discord_six_numbers.py")],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(SCRIPTS),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = (r.stdout or "") + (r.stderr or "")
        # prefer JSON line
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("JSON "):
                return json.loads(line[5:])
            if line.startswith("{") and "registry_total" in line or "1_registry_total" in line:
                try:
                    return json.loads(line)
                except Exception:
                    pass
        return {"raw": text[-500:], "exit": r.returncode}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def heartbeat_age_s() -> tuple[float | None, str]:
    now = datetime.now(timezone.utc)
    cands: list[tuple[float, str]] = []
    for path, keys in (
        (CONT_STATE, ("heartbeat_at", "at")),
        (TICK_HB, ("at",)),
    ):
        if not path.is_file():
            continue
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            for k in keys:
                if d.get(k):
                    dt = _parse_iso(str(d[k]))
                    if dt:
                        cands.append(((now - dt).total_seconds(), f"{path.name}:{k}"))
            cands.append((time.time() - path.stat().st_mtime, f"{path.name}:mtime"))
        except Exception:
            pass
    if not cands:
        return None, "none"
    age, src = min(cands, key=lambda x: x[0])
    return age, src


def soft_prune_drains() -> list[int]:
    pids = _pids("g_to_k_safe_drain.py")
    if len(pids) <= 1:
        return []
    keep = min(pids)
    killed = []
    try:
        from windows_subprocess import kill_process_tree
    except Exception:
        kill_process_tree = None  # type: ignore
    for p in pids:
        if p == keep:
            continue
        if kill_process_tree:
            kill_process_tree(p)
        else:
            subprocess.run(
                ["taskkill", "/PID", str(p), "/T", "/F"],
                capture_output=True,
                timeout=60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        killed.append(p)
    return killed


def main() -> int:
    actions: list[str] = []
    counts = {k: _count(v) for k, v in MARKERS.items()}
    dual_bad = int(
        counts.get("continuous", 0) > 1
        or counts.get("drain", 0) > 1
        or counts.get("orchestrator", 0) > 1
        or counts.get("focus_land", 0) > 1
    )
    age, src = heartbeat_age_s()
    six = six_numbers()
    prev = {}
    if PREV_JSON.is_file():
        try:
            prev = json.loads(PREV_JSON.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
    reg_now = six.get("1_registry_total") or six.get("registry_total")
    reg_prev = (prev.get("six") or {}).get("1_registry_total") or (prev.get("six") or {}).get(
        "registry_total"
    )
    reg_delta = None
    if isinstance(reg_now, int) and isinstance(reg_prev, int):
        reg_delta = reg_now - reg_prev
    prev_at = prev.get("at")
    elapsed_prev_s = None
    if prev_at:
        dt = _parse_iso(str(prev_at))
        if dt:
            elapsed_prev_s = (datetime.now(timezone.utc) - dt).total_seconds()

    # Soft prune dual drains without killing continuous
    if counts.get("drain", 0) > 1 and (age is None or age < 900):
        killed = soft_prune_drains()
        if killed:
            actions.append(f"soft_prune_drains={killed}")
            counts["drain"] = _count("g_to_k_safe_drain.py")
            dual_bad = int(
                counts.get("continuous", 0) > 1
                or counts.get("drain", 0) > 1
                or counts.get("orchestrator", 0) > 1
                or counts.get("focus_land", 0) > 1
            )

    # Continuous dead + no STOP → ask overnight watchdog to start
    if counts.get("continuous", 0) <= 0 and not STOP.is_file():
        try:
            r = subprocess.run(
                [sys.executable, str(SCRIPTS / "silo_overnight_watchdog.py")],
                capture_output=True,
                text=True,
                timeout=180,
                cwd=str(SCRIPTS),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            actions.append(f"overnight_watchdog_exit={r.returncode}")
            actions.append(((r.stdout or "") + (r.stderr or ""))[-200:])
            counts["continuous"] = _count("silo_continuous_loop.py")
        except Exception as e:
            actions.append(f"overnight_watchdog_err={type(e).__name__}")

    # Freeze signal: heartbeat old OR registry flat across long gap while drain alive
    freeze = False
    freeze_reasons = []
    if age is not None and age > 1800:
        freeze = True
        freeze_reasons.append(f"heartbeat_stale_{int(age)}s")
    if (
        counts.get("drain", 0) >= 1
        and isinstance(reg_delta, int)
        and reg_delta == 0
        and elapsed_prev_s is not None
        and elapsed_prev_s >= 900
    ):
        freeze = True
        freeze_reasons.append("registry_flat_15m_with_drain")

    alert = bool(dual_bad or freeze or counts.get("continuous", 0) != 1)

    msg = {
        "at": utc(),
        "counts": counts,
        "dual_bad": dual_bad,
        "heartbeat_age_s": age,
        "heartbeat_src": src,
        "six": six,
        "reg_delta_since_prev": reg_delta,
        "prev_pulse_gap_s": elapsed_prev_s,
        "freeze": freeze,
        "freeze_reasons": freeze_reasons,
        "alert": alert,
        "actions": actions,
        "stop_present": STOP.is_file(),
    }

    # rotate prev
    if OUT_JSON.is_file():
        try:
            PREV_JSON.write_text(OUT_JSON.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass
    OUT_JSON.write_text(json.dumps(msg, indent=2), encoding="utf-8")
    VAULT_LOG.parent.mkdir(parents=True, exist_ok=True)
    VAULT_LOG.write_text(
        f"# Silo land health pulse — {msg['at']}\n\n"
        f"**alert:** `{alert}` · **dual_bad:** `{dual_bad}` · **freeze:** `{freeze}`\n\n"
        f"```json\n{json.dumps(msg, indent=2)}\n```\n\n"
        f"## Notes\n"
        f"- Single-writer land (SQLite WAL) — drain count must stay ≤1\n"
        f"- Heartbeat fresher than cycle `at` during long ticks is healthy\n"
        f"- Soft prune keeps oldest drain; full tree restart only if soft fails\n",
        encoding="utf-8",
    )
    print(json.dumps(msg, indent=2))
    return 1 if alert and freeze else 0


if __name__ == "__main__":
    raise SystemExit(main())
