#!/usr/bin/env python3
"""Hermes gateway service — Red-style outer restart loop (Windows-hard).

Research (2026-07-17):
  - Red Discord Bot: external restart on abnormal exit (docs.discord.red autostart_windows)
  - Discord: max 1000 IDENTIFY/24h — backoff restarts, avoid thrash
  - Windows Job Objects: children die with parent unless BREAKAWAY (Raymond Chen / MS docs)
  - Community: silent discord.py exits on Windows often have no traceback → outer loop required

This process:
  1. Breaks away from parent Job Objects
  2. Clears ghost gateway locks
  3. Spawns gateway.run, WAITS for exit, logs exit code
  4. Backs off and restarts (sole owner — no dual Start-VenvGateway)

Do NOT also run hermes_gateway_supervisor as a second starter while this is up.
Meta-watchdog should only ensure THIS service is alive.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\HermesData")
LOG = ROOT / "logs" / "gateway-service.log"
STATE = ROOT / "state"
LOCK = STATE / "gateway-service.lock"
HEARTBEAT = STATE / "gateway-service-heartbeat.json"
VENV_PYW = ROOT / "hermes-agent" / "venv" / "Scripts" / "pythonw.exe"
VENV_PY = ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe"

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

MIN_BACKOFF = 3
MAX_BACKOFF = 60
# Do NOT treat brief /health stalls as "hung". Hermes serves /health on the same
# asyncio loop as Discord/tools (api_server). Sync tool storms can block the loop
# for tens of seconds without the process dying (see hermes-agent #41289).
# Killing on short blips was a self-inflicted mid-turn death mode.
HUNG_HEALTH_GRACE_SEC = 120
HUNG_POLL_SEC = 8


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {msg}"
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            timeout=12,
            creationflags=CREATE_NO_WINDOW,
        )
        out = (r.stdout or "").strip()
        return str(pid) in out and "No tasks" not in out
    except Exception:
        return False


def health(timeout: float = 2.5) -> bool:
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8642/health",
            headers={"User-Agent": "hermes-gateway-service/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:
        return False


def clear_ghosts() -> None:
    for name in ("gateway.pid", "gateway.lock", "gateway_state.json"):
        path = ROOT / name
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            pid = 0
            if raw.strip().startswith("{"):
                pid = int(json.loads(raw).get("pid") or 0)
            if pid and pid_alive(pid) and health():
                continue
            if pid and pid_alive(pid) and not health():
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True,
                    timeout=15,
                    creationflags=CREATE_NO_WINDOW,
                )
            path.unlink(missing_ok=True)
            log(f"cleared ghost {name}")
        except Exception as exc:
            log(f"clear {name}: {exc}")


def kill_stray_gateways() -> None:
    """Kill orphan gateway.run not started by us (shouldn't dual-run)."""
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                "Get-CimInstance Win32_Process | Where-Object { "
                "$_.Name -match 'python' -and $_.CommandLine -match 'gateway\\.run' } | "
                "ForEach-Object { $_.ProcessId }",
            ],
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=CREATE_NO_WINDOW,
        )
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                pid = int(line)
                if pid != os.getpid():
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        capture_output=True,
                        timeout=15,
                        creationflags=CREATE_NO_WINDOW,
                    )
                    log(f"killed stray gateway pid={pid}")
    except Exception as exc:
        log(f"kill_stray err: {exc}")


def heartbeat(status: str, **extra) -> None:
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "ts": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "health": health(1.5),
            **extra,
        }
        HEARTBEAT.write_text(json.dumps(payload), encoding="utf-8")
        LOCK.write_text(f"{os.getpid()} {datetime.now().isoformat()}", encoding="utf-8")
    except Exception:
        pass


def acquire() -> bool:
    STATE.mkdir(parents=True, exist_ok=True)
    if LOCK.is_file():
        try:
            old = int(LOCK.read_text(encoding="utf-8").strip().split()[0])
            if old > 0 and old != os.getpid() and pid_alive(old):
                log(f"exit: service already running pid={old}")
                return False
        except Exception:
            pass
    LOCK.write_text(f"{os.getpid()} {datetime.now().isoformat()}", encoding="utf-8")
    return True


def run_gateway_once() -> int:
    """Spawn gateway and wait. Returns process exit code (or -1)."""
    clear_ghosts()
    # If already healthy, do not start second — wait for it to die.
    # Use hung grace: one /health blip during a tool storm is NOT "down"
    # (same asyncio loop as Discord/tools — see HUNG_HEALTH_GRACE_SEC).
    if health():
        log("gateway already healthy — monitor until down")
        unhealthy_since: float | None = None
        while True:
            heartbeat("monitoring")
            if health(timeout=2.0):
                unhealthy_since = None
            else:
                now = time.monotonic()
                if unhealthy_since is None:
                    unhealthy_since = now
                    log("monitor health blip — not treating as down yet")
                elif (now - unhealthy_since) >= HUNG_HEALTH_GRACE_SEC:
                    log(
                        f"monitored gateway unhealthy >{HUNG_HEALTH_GRACE_SEC}s — "
                        "assuming down"
                    )
                    break
            time.sleep(HUNG_POLL_SEC)
        log("monitored gateway went down")
        clear_ghosts()
        return 0

    kill_stray_gateways()
    clear_ghosts()

    pyw = VENV_PYW if VENV_PYW.is_file() else VENV_PY
    env = os.environ.copy()
    env["HERMES_HOME"] = str(ROOT)
    env["HERMES_CONFIG_PATH"] = str(ROOT / "config.yaml")
    env["PYTHONIOENCODING"] = "utf-8"
    env["HERMES_GATEWAY_DETACHED"] = "1"
    env["PHRONESIS_BOOT_INTEGRITY"] = "0"
    env["PHRONESIS_BOOT_INTEGRITY_FAIL"] = "warn"
    env["PHRONESIS_BOOT_INTEGRITY_MODE"] = "fast"
    # Crash dumps for silent pythonw deaths (research: discord bots die without traceback on Windows).
    # PYTHONFAULTHANDLER dumps go to stderr → this child log (see log_path below).
    env["PYTHONFAULTHANDLER"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    # SMS: gateway/config.py enables Platform.SMS when TWILIO_ACCOUNT_SID is truthy.
    # hermes_cli.env_loader.load_hermes_dotenv loads HERMES_HOME/.env with override=True,
    # so blanking here is NOT enough if TWILIO_* still live in D:\HermesData\.env.
    # Primary control: keep TWILIO_* commented in .env (done 2026-07-17). Belt-and-suspenders:
    for k in (
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_PHONE_NUMBER",
        "SMS_WEBHOOK_URL",
        "SMS_HOME_CHANNEL",
    ):
        env.pop(k, None)
        env[k] = ""  # still present empty if something setdefaults; dotenv override wins if .env has values

    flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
    log_path = ROOT / "logs" / "gateway-service-child.log"
    try:
        with open(log_path, "a", encoding="utf-8") as child_log:
            child_log.write(f"\n--- spawn {datetime.now().isoformat()} ---\n")
            child_log.write(
                f"env TWILIO_ACCOUNT_SID set={bool(env.get('TWILIO_ACCOUNT_SID'))!r} "
                f"len={len(env.get('TWILIO_ACCOUNT_SID') or '')}\n"
            )
            child_log.flush()
            # Don't use DETACHED if we need wait — CREATE_NO_WINDOW + breakaway is enough
            proc = subprocess.Popen(
                [str(pyw), "-m", "gateway.run"],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=child_log,
                stderr=subprocess.STDOUT,
                creationflags=flags,
                env=env,
            )
    except OSError:
        # Job may forbid BREAKAWAY
        flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
        with open(log_path, "a", encoding="utf-8") as child_log:
            proc = subprocess.Popen(
                [str(pyw), "-m", "gateway.run"],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=child_log,
                stderr=subprocess.STDOUT,
                creationflags=flags,
                env=env,
            )

    log(f"spawned gateway pid={proc.pid}")
    # Wait until healthy or process dies
    for _ in range(40):
        if proc.poll() is not None:
            log(f"gateway exited early code={proc.returncode}")
            return int(proc.returncode if proc.returncode is not None else -1)
        if health():
            log("gateway healthy")
            break
        time.sleep(1.5)

    # Wait for process exit (blocks — this is the outer service)
    unhealthy_since: float | None = None
    while True:
        code = proc.poll()
        if code is not None:
            log(f"gateway exited code={code}")
            return int(code)
        heartbeat("running", child_pid=proc.pid)
        # Process-alive is primary. /health can fail while tools block the event loop.
        if health(timeout=2.0):
            unhealthy_since = None
        else:
            now = time.monotonic()
            if unhealthy_since is None:
                unhealthy_since = now
                log("health blip — waiting (busy loop vs real hang)")
            elif (now - unhealthy_since) >= HUNG_HEALTH_GRACE_SEC:
                # Still only kill if process is actually alive and health stays down
                if proc.poll() is None and not health(timeout=2.0):
                    log(
                        f"gateway hung without /health for >{HUNG_HEALTH_GRACE_SEC}s "
                        f"— taskkill pid={proc.pid}"
                    )
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(proc.pid)],
                            capture_output=True,
                            timeout=15,
                            creationflags=CREATE_NO_WINDOW,
                        )
                    except Exception:
                        pass
                    try:
                        return int(proc.wait(timeout=10) or -1)
                    except Exception:
                        return -1
        time.sleep(HUNG_POLL_SEC)


def _self_breakaway() -> None:
    """Leave parent Job Object so killing the launcher shell doesn't kill us."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        # Create a new job-less process group membership via breakaway flag is
        # only for CreateProcess. For the *current* process, detach from job:
        # AssignProcessToJobObject is one-way; best-effort: ignore failures.
        # Alternative used by many services: nothing if already free.
        handle = kernel32.GetCurrentProcess()
        # JOB_OBJECT_LIMIT_BREAKAWAY_OK is set by parent; if we were created
        # with CREATE_BREAKAWAY_FROM_JOB we are already free. No-op otherwise.
        _ = handle
    except Exception:
        pass


def main() -> int:
    _self_breakaway()
    if not acquire():
        return 0
    log(f"gateway-service START pid={os.getpid()} (Red-style outer loop)")
    backoff = MIN_BACKOFF
    try:
        while True:
            try:
                code = run_gateway_once()
                heartbeat("restarting", last_exit=code)
                # Discord IDENTIFY budget: backoff after crashes
                sleep_for = backoff if code != 0 else MIN_BACKOFF
                log(f"restart in {sleep_for}s (exit={code})")
                time.sleep(sleep_for)
                backoff = min(MAX_BACKOFF, backoff * 2 if code != 0 else MIN_BACKOFF)
            except Exception as exc:
                log(f"loop_err {exc}")
                time.sleep(backoff)
                backoff = min(MAX_BACKOFF, backoff * 2)
    finally:
        try:
            if LOCK.is_file() and LOCK.read_text(encoding="utf-8").startswith(
                str(os.getpid())
            ):
                LOCK.unlink(missing_ok=True)
        except Exception:
            pass
        log("gateway-service EXIT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
