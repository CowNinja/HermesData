#!/usr/bin/env python3
"""Travel autonomy heartbeat — progress snapshot + gray queue + continuous kick if needed.

Safe for Task Scheduler every 30–60 min. No Grok. No gateway restarts.
Always kicks continuous with pythonw + CREATE_NO_WINDOW (no focus steal).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from windows_subprocess import (  # noqa: E402
    hidden_powershell_command,
    popen_daemon,
    run_hidden,
)
try:
    from atomic_io import atomic_write_text, atomic_write_json  # noqa: E402
except ImportError:  # pragma: no cover
    atomic_write_text = None  # type: ignore
    atomic_write_json = None  # type: ignore

STATE = Path(r"D:\HermesData\state\silo_continuous_state.json")
STOP = Path(r"D:\HermesData\state\silo_continuous.STOP")
PROGRESS = Path(r"D:\HermesData\state\travel_progress.jsonl")
BRIEF_LOG = Path(r"D:\PhronesisVault\Operations\logs\travel-heartbeat-latest.md")
DB = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
# python.exe + FreeConsole in worker (pythonw unstable for long multi-child loops).
_PY_CANDIDATES = [
    Path(r"C:\Users\CowNi\AppData\Local\Programs\Python\Python311\python.exe"),
    Path(sys.executable),
]
PY = str(next((p for p in _PY_CANDIDATES if p.is_file()), Path(sys.executable)))
STALE_S = 1200  # 20 min


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def continuous_running() -> bool:
    try:
        # Match python.exe AND pythonw.exe (background relaunch uses pythonw).
        r = run_hidden(
            hidden_powershell_command(
                "(Get-CimInstance Win32_Process | Where-Object { "
                "$_.CommandLine -like '*silo_continuous_loop.py*' "
                "-and $_.Name -like 'python*' } | Measure-Object).Count"
            ),
            capture_output=True,
            text=True,
            timeout=45,
        )
        return int((r.stdout or "0").strip() or "0") > 0
    except Exception:
        return False


def kick_continuous() -> str:
    if STOP.is_file():
        return "STOP present"
    # Jeff 2026-07-13: never kill+respawn if already running (multi-writer storm)
    if continuous_running():
        return "already_running"
    vbs = Path(r"D:\HermesData\scripts\start_silo_continuous_only_hidden.vbs")
    run_hidden(["wscript.exe", "//B", str(vbs)], timeout=15)
    import time as _t

    _t.sleep(1.0)
    pid = "?"
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
        pid = (r.stdout or "?").strip().splitlines()[-1]
        if pid.isdigit():
            pid_path = Path(r"D:\HermesData\state\silo_continuous.pid")
            if atomic_write_text is not None:
                atomic_write_text(pid_path, pid, min_bytes=1)
            else:
                pid_path.write_text(pid, encoding="utf-8")
    except Exception:
        pass
    return f"started {pid}"


def main() -> int:
    reg = uniq = None
    if DB.is_file():
        con = sqlite3.connect(str(DB))
        reg = con.execute("SELECT COUNT(*) FROM ingest").fetchone()[0]
        uniq = con.execute(
            "SELECT COUNT(DISTINCT sha256) FROM ingest WHERE sha256 IS NOT NULL AND sha256!=''"
        ).fetchone()[0]
        con.close()

    age = None
    mode = None
    if STATE.is_file():
        try:
            d = json.loads(STATE.read_text(encoding="utf-8"))
            at = datetime.fromisoformat(d["at"].replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - at).total_seconds()
            mode = (d.get("assess") or {}).get("mode") or d.get("mode")
        except Exception:
            pass

    actions = []
    running = continuous_running()
    if STOP.is_file():
        actions.append("STOP file — not restarting")
    elif not running or (age is not None and age > STALE_S):
        actions.append(kick_continuous())
    else:
        actions.append(f"continuous ok age={int(age or 0)}s")

    # gray queue refresh
    try:
        r = run_hidden(
            [PY, str(SCRIPTS / "silo_gray_entities_queue.py")],
            capture_output=True,
            text=True,
            timeout=120,
        )
        actions.append(f"gray_queue {(r.stdout or '')[:120]}")
    except Exception as e:
        actions.append(f"gray_err {e}")

    # ensure silo_primary flags
    try:
        sp = Path(r"D:\HermesData\state\silo_primary.json")
        if sp.is_file():
            j = json.loads(sp.read_text(encoding="utf-8"))
            if not j.get("enabled"):
                j["enabled"] = True
                j["reason"] = "travel_autonomy_reassert"
                if atomic_write_json is not None:
                    atomic_write_json(sp, j, indent=2, min_bytes=20)
                else:
                    sp.write_text(json.dumps(j, indent=2), encoding="utf-8")
                actions.append("reasserted silo_primary")
    except Exception:
        pass

    entry = {
        "at": utc(),
        "registry": reg,
        "unique": uniq,
        "continuous_age_s": age,
        "mode": mode,
        "running": running,
        "actions": actions,
    }
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    with PROGRESS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    BRIEF_LOG.parent.mkdir(parents=True, exist_ok=True)
    brief = (
        f"# Travel heartbeat — {entry['at']}\n\n"
        f"- registry: **{reg}** · unique: **{uniq}**\n"
        f"- continuous age: {age}\n"
        f"- actions: {actions}\n"
    )
    if atomic_write_text is not None:
        atomic_write_text(BRIEF_LOG, brief, min_bytes=20)
    else:
        BRIEF_LOG.write_text(brief, encoding="utf-8")
    print(json.dumps(entry))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
