#!/usr/bin/env python3
"""Single 30m stack/gateway healer — one shot, never daemonize.

FIRST PRINCIPLES (one authority, no double-boot):
  1. Port probe is truth for "remote access healthy" (:8642).
  2. Process probe is truth for "something already starting/running".
  3. Exactly ONE automatic restorer: this script (cron Stack-Healing-30m).
  4. Exactly ONE launcher: Phronesis.ps1 gateway start (ForkGuard
     Start-VenvGateway, -m gateway.run). schtasks Hermes_Gateway is
     legacy fallback only. Direct pythonw --replace is LAST RESORT.
  5. Exclusive file lock → concurrent healers cannot both start gateways.
  6. Cooldown is enforced (not merely logged).
  7. Boot-wait: if a gateway PID exists but port is closed, WAIT — do not
     spawn a second instance.
  8. Never kill a healthy listener. Kill orphans only when port is down.
  9. Clear restart_loop when restoring (breaker must not block recovery).
 10. Optional stack tick (watchdog --once) under hard timeout; it does NOT
     start the gateway.
 11. Silent empty stdout when green + no action (cron no_agent).

Cron pitfall: no_agent runs [python, script] with NO argv — never point
cron at sovereign_stack_watchdog.py (defaults to infinite daemon → timeout).

Canonical home for this host: HERMES_HOME=D:\\HermesData
(matches Hermes_Gateway scheduled task WorkingDirectory + dual pid files).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(r"D:\HermesData")
SCRIPTS = ROOT / "scripts"
WATCHDOG = SCRIPTS / "sovereign_stack_watchdog.py"
# Hermes gateway state lives under HERMES_HOME (task + live dual write).
HERMES_HOME = ROOT
# Secondary home sometimes used by ad-hoc launches / defaults.
HERMES_HOME_ALT = Path.home() / ".hermes"
GATEWAY_DIR = HERMES_HOME / "gateway"
RESTART_LOOP = GATEWAY_DIR / "restart_loop.json"
LAST_HEAL = GATEWAY_DIR / ".last_heal"
HEAL_LOCK = GATEWAY_DIR / ".heal.lock"
LOG = ROOT / "logs" / "stack-healing-once.jsonl"
GATEWAY_PORT = 8642
TASK_NAME = "Hermes_Gateway"
WATCHDOG_TIMEOUT_SEC = 150
# How long to wait for an already-running process to bind the port.
BOOT_WAIT_SEC = 45
# How long after schtasks / direct start before declaring failure.
START_WAIT_SEC = 50
# Min seconds between aggressive restore attempts.
RESTART_COOLDOWN_SEC = 300
# Patterns that identify a Hermes gateway process (CommandLine).
_GATEWAY_CMDLINE_MARKERS = (
    "hermes_cli.main gateway",
    "hermes_cli.main\" gateway",
    " gateway run",
    "gateway.run",
    r"hermes-agent\gateway\run.py",
    r"hermes-agent/gateway/run.py",
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(event: dict) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": _utc(), **event}) + "\n")
    except Exception:
        pass


def port_open(port: int = GATEWAY_PORT, host: str = "127.0.0.1", timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def health_ok(timeout: float = 2.5) -> bool:
    """HTTP /health 2xx only.

    Do NOT fall back to bare TCP connect: a half-dead process, wrong service, or
    stale ESTABLISHED traffic can make port_open() true while Discord is silent.
    That false-positive caused stack_healing_once to report already_up with empty
    listeners while the gateway was effectively dead (2026-07-17 outages).
    """
    try:
        import urllib.request

        req = urllib.request.Request(
            f"http://127.0.0.1:{GATEWAY_PORT}/health",
            method="GET",
            headers={"User-Agent": "stack-healing-once/1.1"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:
        return False


def clear_stale_pid_files() -> list[dict]:
    """Remove gateway.pid / gateway.lock when claimed PID is not alive."""
    results: list[dict] = []
    for home in (HERMES_HOME, HERMES_HOME_ALT):
        for name in ("gateway.pid", "gateway.lock", "gateway_state.json"):
            path = home / name
            if not path.is_file():
                continue
            try:
                raw = path.read_text(encoding="utf-8").strip()
                pid = 0
                if raw.startswith("{"):
                    data = json.loads(raw)
                    pid = int(data.get("pid") or 0)
                else:
                    try:
                        pid = int(raw.split()[0])
                    except Exception:
                        pid = 0
                if pid and _pid_alive(pid):
                    results.append({"path": str(path), "action": "kept", "pid": pid})
                    continue
                path.unlink(missing_ok=True)
                results.append(
                    {"path": str(path), "action": "cleared", "pid": pid or None, "reason": "dead_or_unparseable"}
                )
            except Exception as exc:
                results.append({"path": str(path), "action": "error", "error": str(exc)})
    return results


# ---------------------------------------------------------------------------
# Single-instance heal lock (Windows + POSIX)
# ---------------------------------------------------------------------------


class HealLock:
    """Exclusive non-blocking lock so two healers cannot both launch."""

    def __init__(self, path: Path = HEAL_LOCK) -> None:
        self.path = path
        self._fh: Any = None
        self.held = False

    def acquire(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a+", encoding="utf-8")
            if sys.platform == "win32":
                import msvcrt

                self._fh.seek(0)
                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    self._fh.close()
                    self._fh = None
                    return False
            else:
                import fcntl

                try:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    self._fh.close()
                    self._fh = None
                    return False
            self._fh.seek(0)
            self._fh.truncate()
            self._fh.write(json.dumps({"pid": os.getpid(), "ts": _utc()}) + "\n")
            self._fh.flush()
            self.held = True
            return True
        except Exception:
            try:
                if self._fh:
                    self._fh.close()
            except Exception:
                pass
            self._fh = None
            return False

    def release(self) -> None:
        if not self._fh:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                self._fh.seek(0)
                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
            self.held = False


# ---------------------------------------------------------------------------
# Cooldown / restart_loop
# ---------------------------------------------------------------------------


def read_last_heal_age() -> Optional[float]:
    if not LAST_HEAL.is_file():
        return None
    try:
        raw = LAST_HEAL.read_text(encoding="utf-8").strip()
        if raw.replace(".", "", 1).isdigit():
            return max(0.0, time.time() - float(raw))
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, time.time() - ts.timestamp())
    except Exception:
        try:
            return max(0.0, time.time() - LAST_HEAL.stat().st_mtime)
        except Exception:
            return None


def write_last_heal() -> None:
    try:
        GATEWAY_DIR.mkdir(parents=True, exist_ok=True)
        LAST_HEAL.write_text(_utc(), encoding="utf-8")
    except Exception:
        pass


def clear_restart_loop(*, force: bool = False, max_age_sec: float = 600.0) -> dict:
    """Clear gateway restart_loop breaker state under HERMES_HOME/gateway/.

    Note: restart_loop.json is a *session auto-resume* breaker inside Hermes,
    not a process spawn lock. We still clear it when port is down so a trip
    file never confuses operators or side tools.
    """
    paths = [RESTART_LOOP, HERMES_HOME_ALT / "gateway" / "restart_loop.json"]
    results = []
    for path in paths:
        if not path.is_file():
            results.append({"path": str(path), "action": "none", "reason": "absent"})
            continue
        if force:
            try:
                path.unlink(missing_ok=True)
                results.append({"path": str(path), "action": "cleared", "reason": "force_gateway_down"})
            except Exception as exc:
                results.append({"path": str(path), "action": "error", "error": str(exc)})
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            boots = data.get("boots") or []
            if not boots:
                path.unlink(missing_ok=True)
                results.append({"path": str(path), "action": "cleared", "reason": "empty_boots"})
                continue
            newest = max(float(b) for b in boots)
            age = time.time() - newest
            if age > max_age_sec or age < -60:
                path.unlink(missing_ok=True)
                results.append(
                    {"path": str(path), "action": "cleared", "reason": "stale", "age_sec": round(age, 1)}
                )
            else:
                results.append(
                    {
                        "path": str(path),
                        "action": "kept",
                        "age_sec": round(age, 1),
                        "boots": len(boots),
                    }
                )
        except Exception as exc:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
            results.append({"path": str(path), "action": "cleared", "reason": f"parse_error:{exc}"})
    return {"files": results}


# ---------------------------------------------------------------------------
# Process / PID awareness (anti double-boot)
# ---------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            out = (r.stdout or "").strip()
            return str(pid) in out and "No tasks" not in out
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def read_pid_files() -> list[dict]:
    """Read known gateway.pid locations (canonical + alt home)."""
    found: list[dict] = []
    for home in (HERMES_HOME, HERMES_HOME_ALT):
        path = home / "gateway.pid"
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8").strip()
            pid: Optional[int] = None
            meta: dict = {"path": str(path)}
            if raw.startswith("{"):
                data = json.loads(raw)
                pid = int(data.get("pid") or 0)
                meta["meta"] = {k: data.get(k) for k in ("kind", "argv", "start_time") if k in data}
            else:
                # plain integer pid
                pid = int(raw.split()[0])
            meta["pid"] = pid
            meta["alive"] = _pid_alive(pid) if pid else False
            found.append(meta)
        except Exception as exc:
            found.append({"path": str(path), "error": str(exc), "alive": False})
    return found


def list_gateway_pids() -> list[int]:
    """Enumerate live gateway processes via CIM (Windows) or pgrep-like scan.

    Hermes on Windows often has a parent+child pythonw tree (venv re-exec into
    system python -m gateway.run). Multiple PIDs here is NORMAL — not a double
    boot. A true double boot = multiple distinct LISTENING PIDs on :8642.
    """
    pids: set[int] = set()
    # PID files first (fast + authoritative for this profile)
    for rec in read_pid_files():
        if rec.get("alive") and rec.get("pid"):
            pids.add(int(rec["pid"]))

    if sys.platform == "win32":
        # Narrow CIM filter — only real python gateway processes.
        # Exclude powershell/cmd whose *script text* mentions gateway.run (false positives
        # caused healers to treat diagnostic shells as hung gateways).
        ps = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { "
            "$_.CommandLine -and "
            "$_.Name -match 'python(w)?\\.exe' -and "
            "$_.CommandLine -notmatch 'powershell|pwsh|cmd\\.exe' -and ("
            "$_.CommandLine -match 'hermes_cli\\.main.*gateway' -or "
            "$_.CommandLine -match '-m\\s+gateway\\.run' -or "
            "$_.CommandLine -match 'gateway\\.run' -or "
            "$_.CommandLine -match 'hermes-agent[\\\\/]gateway[\\\\/]run\\.py'"
            ") } | ForEach-Object { $_.ProcessId }"
        )
        try:
            flags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                if sys.platform == "win32"
                else 0
            )
            r = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-WindowStyle",
                    "Hidden",
                    "-Command",
                    ps,
                ],
                capture_output=True,
                text=True,
                timeout=45,
                creationflags=flags,
            )
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.add(int(line))
        except Exception:
            pass
    else:
        try:
            r = subprocess.run(
                ["pgrep", "-f", "hermes_cli.main gateway|gateway.run"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            for line in (r.stdout or "").splitlines():
                if line.strip().isdigit():
                    pids.add(int(line.strip()))
        except Exception:
            pass
    return sorted(p for p in pids if p > 4)


def serving_listener_pids(port: int = GATEWAY_PORT) -> list[int]:
    """PIDs actually LISTENING on the gateway port (true multi-instance signal)."""
    return listeners_on_port(port)


def multi_listener_conflict(port: int = GATEWAY_PORT) -> bool:
    """True if more than one process is LISTENING on the gateway port."""
    return len(serving_listener_pids(port)) > 1


def listeners_on_port(port: int = GATEWAY_PORT) -> list[int]:
    pids: set[int] = set()
    try:
        r = subprocess.run(
            ["cmd.exe", "/c", f"netstat -ano | findstr :{port}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        for line in (r.stdout or "").splitlines():
            if "LISTENING" not in line.upper():
                continue
            parts = line.split()
            if len(parts) >= 5:
                try:
                    pid = int(parts[-1])
                    if pid > 4:
                        pids.add(pid)
                except ValueError:
                    pass
    except Exception:
        pass
    return sorted(pids)


def kill_pids(pids: list[int]) -> dict:
    killed: list[int] = []
    errors: list[str] = []
    for pid in pids:
        if pid <= 4:
            continue
        try:
            r = subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if r.returncode == 0:
                killed.append(pid)
            else:
                errors.append(f"{pid}:{(r.stderr or r.stdout or '')[-80:]}")
        except Exception as exc:
            errors.append(f"{pid}:{exc}")
    return {"killed": killed, "errors": errors}


def wait_until(
    predicate,
    timeout_sec: float,
    interval: float = 2.0,
) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


# ---------------------------------------------------------------------------
# Restore path — single launcher
# ---------------------------------------------------------------------------


def start_via_phronesis_gateway() -> dict:
    """Canonical launcher — matches ForkGuard / Phronesis-Guardian."""
    ps1 = SCRIPTS / "Phronesis.ps1"
    try:
        flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            if sys.platform == "win32"
            else 0
        )
        r = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps1),
                "gateway",
                "start",
            ],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=str(ROOT),
            creationflags=flags,
        )
        return {
            "step": "phronesis_gateway_start",
            "code": r.returncode,
            "stdout": (r.stdout or "")[-200:],
            "stderr": (r.stderr or "")[-200:],
            "ok": r.returncode == 0,
        }
    except Exception as exc:
        return {"step": "phronesis_gateway_start", "error": str(exc), "ok": False}


def start_via_schtasks() -> dict:
    """Legacy fallback — Hermes_Gateway task may use an older argv."""
    try:
        r = subprocess.run(
            ["schtasks", "/Run", "/TN", TASK_NAME],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {
            "step": "schtasks_run",
            "code": r.returncode,
            "stdout": (r.stdout or "")[-200:],
            "stderr": (r.stderr or "")[-200:],
            "ok": r.returncode == 0,
        }
    except Exception as exc:
        return {"step": "schtasks_run", "error": str(exc), "ok": False}


def start_via_direct_pythonw() -> dict:
    """Last-resort single launch. HERMES_HOME forced to canonical ROOT.

    Never use --replace here: legacy watchdogs treated --replace as an eviction
    trigger and killed the process. Clear dead pid/lock first, then start clean
    via -m gateway.run (same as ForkGuard Start-VenvGateway).
    """
    clear_stale_pid_files()
    pyw = ROOT / "hermes-agent" / "venv" / "Scripts" / "pythonw.exe"
    if not pyw.is_file():
        pyw = Path(sys.executable)
    env = os.environ.copy()
    env["HERMES_HOME"] = str(HERMES_HOME)
    env["HERMES_CONFIG_PATH"] = str(ROOT / "config.yaml")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("HERMES_GATEWAY_DETACHED", "1")
    creation = 0
    if sys.platform == "win32":
        creation = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | 0x08000000  # CREATE_NO_WINDOW
        )
    try:
        # Prefer -m gateway.run (matches live Windows process tree).
        subprocess.Popen(
            [str(pyw), "-m", "gateway.run"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creation if sys.platform == "win32" else 0,
            close_fds=True,
            env=env,
        )
        return {"step": "direct_pythonw", "ok": True, "pyw": str(pyw), "replace": False, "argv": "gateway.run"}
    except Exception as exc:
        return {"step": "direct_pythonw", "error": str(exc), "ok": False}


def restore_gateway(*, force: bool = False) -> dict:
    """Idempotent restore. Never double-boots a live/starting gateway."""
    actions: list[dict] = []
    actions.append({"step": "clear_stale_pid_files", "results": clear_stale_pid_files()})

    listeners = serving_listener_pids()
    if health_ok():
        note = "already_healthy"
        if multi_listener_conflict():
            note = "already_healthy_but_multi_listener"
        return {
            "action": "none",
            "restored": False,
            "port_8642": True,
            "health": True,
            "note": note,
            "pids": list_gateway_pids(),
            "listeners": listeners,
            "restart_loop": clear_restart_loop(force=False),
        }

    # Port down but process(es) already present → wait for bind, do NOT spawn.
    existing = list_gateway_pids()
    if existing:
        actions.append(
            {
                "step": "boot_wait",
                "pids": existing,
                "listeners": listeners,
                "sec": BOOT_WAIT_SEC,
                "note": "process_present_no_health_wait_not_spawn",
            }
        )
        up = wait_until(health_ok, BOOT_WAIT_SEC, 2.0)
        if up:
            return {
                "action": "waited_boot",
                "restored": True,
                "port_8642": True,
                "health": True,
                "pids": list_gateway_pids(),
                "listeners": serving_listener_pids(),
                "actions": actions,
            }
        # Hung process tree: port never bound. Kill whole gateway PID set, then one start.
        # (Parent+child re-exec is one instance — kill all listed gateway PIDs.)
        actions.append({"step": "kill_hung_gateways", **kill_pids(existing)})
        time.sleep(2)

    # Cooldown — enforced
    age = read_last_heal_age()
    if not force and age is not None and age < RESTART_COOLDOWN_SEC:
        # Re-check: maybe it recovered during cooldown window
        if health_ok():
            return {
                "action": "none",
                "restored": False,
                "port_8642": True,
                "health": True,
                "note": "recovered_during_cooldown",
                "cooldown_age_sec": round(age, 1),
            }
        return {
            "action": "blocked_cooldown",
            "restored": False,
            "port_8642": False,
            "health": False,
            "cooldown_age_sec": round(age, 1),
            "cooldown_sec": RESTART_COOLDOWN_SEC,
            "pids": list_gateway_pids(),
            "note": "last_heal_too_recent; refuse restart storm",
            "actions": actions,
        }

    actions.append({"restart_loop": clear_restart_loop(force=True)})

    # Orphan listeners claiming the port without health (rare)
    listeners = listeners_on_port()
    still_down = not health_ok()
    if still_down and listeners and not list_gateway_pids():
        actions.append({"step": "taskkill_orphan_listeners", **kill_pids(listeners)})
        time.sleep(1)

    # --- Single primary launcher (Phronesis / ForkGuard) ---
    primary = start_via_phronesis_gateway()
    actions.append(primary)
    write_last_heal()  # stamp even if start fails — cooldown still applies

    up = wait_until(health_ok, START_WAIT_SEC, 2.0)
    if up:
        return {
            "action": "restore",
            "restored": True,
            "port_8642": True,
            "health": True,
            "method": "phronesis_gateway_start",
            "pids": list_gateway_pids(),
            "actions": actions,
        }

    # After primary wait: if a process appeared, wait more — never dual-start.
    spawned = list_gateway_pids()
    if spawned:
        actions.append({"step": "post_phronesis_boot_wait", "pids": spawned})
        up = wait_until(health_ok, BOOT_WAIT_SEC, 2.0)
        if up:
            return {
                "action": "restore",
                "restored": True,
                "port_8642": True,
                "health": True,
                "method": "phronesis_slow_bind",
                "pids": list_gateway_pids(),
                "actions": actions,
            }
        actions.append({"step": "kill_hung_after_phronesis", **kill_pids(spawned)})
        time.sleep(2)

    # Legacy schtasks fallback (disabled Hermes_Gateway task may no-op)
    sch = start_via_schtasks()
    actions.append(sch)
    up = wait_until(health_ok, START_WAIT_SEC, 2.0)
    if up:
        return {
            "action": "restore",
            "restored": True,
            "port_8642": True,
            "health": True,
            "method": "schtasks_fallback",
            "pids": list_gateway_pids(),
            "actions": actions,
        }

    spawned = list_gateway_pids()
    if spawned:
        actions.append({"step": "post_schtasks_boot_wait", "pids": spawned})
        up = wait_until(health_ok, BOOT_WAIT_SEC, 2.0)
        if up:
            return {
                "action": "restore",
                "restored": True,
                "port_8642": True,
                "health": True,
                "method": "schtasks_slow_bind",
                "pids": list_gateway_pids(),
                "actions": actions,
            }
        actions.append({"step": "kill_hung_after_schtasks", **kill_pids(spawned)})
        time.sleep(2)

    # --- Last resort: only if still zero processes and still down ---
    if list_gateway_pids() or health_ok():
        return {
            "action": "restore",
            "restored": health_ok(),
            "port_8642": port_open(),
            "health": health_ok(),
            "method": "launchers_exhausted",
            "pids": list_gateway_pids(),
            "actions": actions,
            "note": "skipped_direct_fallback_process_present_or_up",
        }

    direct = start_via_direct_pythonw()
    actions.append(direct)
    up = wait_until(health_ok, START_WAIT_SEC, 2.0)
    return {
        "action": "restore",
        "restored": up,
        "port_8642": port_open(),
        "health": up,
        "method": "direct_pythonw" if up else "failed",
        "pids": list_gateway_pids(),
        "actions": actions,
    }


def run_watchdog_once() -> dict:
    if not WATCHDOG.is_file():
        return {"ok": False, "error": "watchdog_missing", "path": str(WATCHDOG)}
    py = ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe"
    if not py.is_file():
        py = Path(sys.executable)
    try:
        r = subprocess.run(
            [str(py), str(WATCHDOG), "--once"],
            capture_output=True,
            text=True,
            timeout=WATCHDOG_TIMEOUT_SEC,
            cwd=str(SCRIPTS),
        )
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        parsed = None
        if out:
            try:
                parsed = json.loads(out)
            except Exception:
                try:
                    start = out.rfind("{")
                    if start >= 0:
                        parsed = json.loads(out[start:])
                except Exception:
                    parsed = None
        status = None
        if isinstance(parsed, dict):
            status = (parsed.get("matrix") or {}).get("status")
        return {
            "ok": r.returncode == 0,
            "code": r.returncode,
            "status": status,
            "stdout_tail": out[-800:] if out else "",
            "stderr_tail": err[-600:] if err else "",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"watchdog_timeout_{WATCHDOG_TIMEOUT_SEC}s"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> int:
    force = "--force" in sys.argv
    skip_watchdog = "--no-watchdog" in sys.argv
    probe_only = "--probe" in sys.argv

    lock = HealLock()
    if not lock.acquire():
        summary = {
            "event": "stack_healing_once",
            "action": "skipped_lock",
            "note": "another_healer_holds_lock",
            "port_8642": port_open(),
            "health": health_ok(),
            "pids": list_gateway_pids(),
            "healer": "stack_healing_once",
            "policy": "single_loop",
        }
        _log(summary)
        # Exit 0 if gateway healthy — concurrent healer is fine.
        if summary["health"]:
            return 0
        print(json.dumps(summary, indent=2))
        return 0  # do not fight the other healer

    try:
        if probe_only:
            listeners = listeners_on_port()
            summary = {
                "event": "stack_healing_probe",
                "port_8642": port_open(),
                "health": health_ok(),
                "pids": list_gateway_pids(),
                "pid_files": read_pid_files(),
                "listeners": listeners,
                "multi_listener": len(listeners) > 1,
                "last_heal_age_sec": read_last_heal_age(),
                "task": TASK_NAME,
                "hermes_home": str(HERMES_HOME),
            }
            print(json.dumps(summary, indent=2))
            # Probe stays soft on multi_listener (measure signal only).
            return 0 if summary["health"] else 1

        # Always drop ghost pid/lock before health decisions.
        stale = clear_stale_pid_files()
        if health_ok():
            gateway_result = {
                "action": "none",
                "port_8642": port_open(),
                "health": True,
                "restored": False,
                "note": "already_up",
                "pids": list_gateway_pids(),
                "listeners": serving_listener_pids(),
                "stale_cleared": stale,
                "restart_loop": clear_restart_loop(force=False, max_age_sec=600.0),
            }
        else:
            gateway_result = restore_gateway(force=force)
            gateway_result["stale_cleared"] = stale

        wd: dict
        if skip_watchdog:
            wd = {"ok": True, "status": None, "skipped": True}
        else:
            wd = run_watchdog_once()

        summary = {
            "event": "stack_healing_once",
            "gateway": gateway_result,
            "watchdog": {
                "ok": wd.get("ok"),
                "status": wd.get("status"),
                "error": wd.get("error"),
                "code": wd.get("code"),
                "skipped": wd.get("skipped"),
                "stderr_tail": (wd.get("stderr_tail") or "")[:400] or None,
            },
            "port_8642": port_open(),
            "health": health_ok(),
            "pids": list_gateway_pids(),
            "listeners": serving_listener_pids(),
            "multi_listener": multi_listener_conflict(),
            "healer": "stack_healing_once",
            "policy": "single_loop",
            "authority": {
                "auto_restore": "stack_healing_once (cron Stack-Healing-30m)",
                "launcher": "Phronesis.ps1 gateway start (ForkGuard)",
                "fallback": f"schtasks {TASK_NAME}, then direct pythonw --replace",
            },
        }
        if summary["watchdog"].get("stderr_tail") is None:
            del summary["watchdog"]["stderr_tail"]
        if summary["watchdog"].get("skipped") is None:
            summary["watchdog"].pop("skipped", None)

        _log(summary)

        # Soft-fail receipt for single-instance guard (measure; no kill here).
        try:
            from pathlib import Path as _Path
            import datetime as _dt

            _recv = _Path(r"D:\PhronesisVault\Operations\logs\single-gateway-instance-latest.json")
            _recv.parent.mkdir(parents=True, exist_ok=True)
            _multi = bool(summary.get("multi_listener"))
            _listeners = summary.get("listeners") or []
            _health = bool(summary.get("health"))
            _n = len(_listeners) if isinstance(_listeners, list) else 0
            _ok = _health and not _multi and _n == 1
            _payload = {
                "at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "ok": _ok,
                "partial": (not _ok),
                "soft_fail": (not _ok),
                "seal": "2026-07-18-single-gateway-soft-fail",
                "status": (
                    "ok"
                    if _ok
                    else ("multi_listener" if _multi else ("down" if not _health else "unknown"))
                ),
                "listener_count": _n,
                "listeners": _listeners,
                "multi_listener": _multi,
                "health": _health,
                "source": "stack_healing_once",
                "gateway_action": gateway_result.get("action"),
                "receipt": str(_recv),
            }
            _tmp = _recv.with_suffix(".json.tmp")
            _tmp.write_text(json.dumps(_payload, indent=2) + "\n", encoding="utf-8")
            _tmp.replace(_recv)
        except Exception:
            pass

        port_ok = bool(summary["health"])
        multi = bool(summary.get("multi_listener"))
        silent = (
            port_ok
            and not multi
            and gateway_result.get("action") == "none"
            and bool(wd.get("ok"))
            and wd.get("status") in ("GREEN", "YELLOW")
            and not wd.get("error")
            and not wd.get("skipped")
        )
        if silent:
            return 0

        print(json.dumps(summary, indent=2))
        # Soft-fail: multi_listener while health up is advisory (exit 0) + printed.
        # Exit 0 if Discord path is up — critical remote-access path.
        return 0 if port_ok else 1
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
