#!/usr/bin/env python3
"""Headless CORE supervisor. Poll 60s. 3-fail restart of THAT service only.

Brain :8090 -> Proxy :8091 -> Gateway :8642. Never SAT heal. Never kill healthy 8090.

  pythonw D:\\HermesData\\scripts\\ops\\sovereign_supervisor.py
  python D:\\HermesData\\scripts\\ops\\sovereign_supervisor.py --once
  python D:\\HermesData\\scripts\\ops\\sovereign_supervisor.py --ensure
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(r"D:\HermesData")
OPS = HERMES / "scripts" / "ops"
SCRIPTS = HERMES / "scripts"
STATE = HERMES / "state"
LOG = HERMES / "logs" / "supervisor.log"
PIDF = STATE / "sovereign_supervisor.pid"
STOP = STATE / "sovereign_supervisor.STOP"
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
INTERVAL = 60
FAILS = 3
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

TARGETS = (
    ("8090", "http://127.0.0.1:8090/health", "brain"),
    ("8091", "http://127.0.0.1:8091/health", "proxy"),
    ("8642", "http://127.0.0.1:8642/health", "gateway"),
)


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = utc() + " " + msg + "\n"
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line)


def probe(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def silent_run(cmd: list[str], timeout: int = 90) -> int:
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        return int(p.returncode or 0)
    except Exception as exc:
        log("RUN_FAIL " + str(exc)[:160])
        return 1


def restart(kind: str) -> None:
    log("RESTART " + kind)
    if kind == "brain":
        silent_run([pythonw_path(), str(SCRIPTS / "ensure_qwythos_8090.py")], timeout=240)
    elif kind == "proxy":
        silent_run(
            [
                "powershell.exe",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPTS / "Start-Sovereign-Proxy-8091.ps1"),
                "-Force",
            ],
            timeout=120,
        )
    elif kind == "gateway":
        silent_run(
            [
                "powershell.exe",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPTS / "Ensure-HermesStack-Single.ps1"),
            ],
            timeout=180,
        )
    warn = f"Sovereign supervisor restarted {kind}. Kitchen check: speak_and_trust_once.py --status-only. No SAT heal unless still down."
    pending = HERMES / "pending_messages"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / f"supervisor-{kind}-{int(time.time())}.txt").write_text(warn, encoding="utf-8")
    # Best-effort Discord; never print tokens
    post = SCRIPTS / "ops_discord_post.py"
    if not post.is_file():
        post = SCRIPTS / "citadel_post_message.py"
    if post.is_file():
        silent_run([sys.executable, str(post), warn[:400]], timeout=30)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    return False


def pythonw_path() -> str:
    for p in (
        Path(r"D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"),
        Path(r"C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe"),
    ):
        if p.is_file():
            return str(p)
    return sys.executable


def ensure() -> int:
    if PIDF.is_file():
        try:
            pid = int(PIDF.read_text(encoding="utf-8").strip() or "0")
            if pid_alive(pid):
                print("SUPERVISOR already", pid)
                return 0
        except Exception:
            pass
    LOG.parent.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    pyw = pythonw_path()
    script = str(OPS / "sovereign_supervisor.py")
    cmdline = f'"{pyw}" "{script}"'
    # WMI Create lands outside the tool Job Object. Popen children die with the job.
    ps1 = STATE / "sovereign_supervisor_launch.ps1"
    ps1.write_text(
        "$cmd = @'\n"
        f"{cmdline}\n"
        "'@\n"
        "$p = Invoke-WmiMethod -Class Win32_Process -Name Create -ArgumentList $cmd\n"
        "if ($null -eq $p -or $p.ReturnValue -ne 0) { exit 1 }\n"
        "Write-Output $p.ProcessId\n",
        encoding="ascii",
    )
    try:
        r = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps1),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception as exc:
        log("SPAWN_FAIL " + str(exc)[:160])
        print("SUPERVISOR spawn failed")
        return 1
    if r.returncode != 0:
        log("SPAWN_FAIL " + (r.stderr or r.stdout or "")[:200])
        print("SUPERVISOR spawn failed", r.returncode)
        return 1
    wmi_pid = (r.stdout or "").strip().splitlines()[-1] if (r.stdout or "").strip() else ""
    log("SPAWN wmi_pid=" + wmi_pid + " exe=" + pyw)
    if wmi_pid.isdigit():
        PIDF.write_text(wmi_pid, encoding="utf-8")
    print("SUPERVISOR spawned", wmi_pid)
    return 0


def boot_missing() -> None:
    """Eager start of down CORE services in Brain -> Proxy -> Gateway order.

    Only starts a service that fails a health probe. Never tears down a live :8090.
    """
    log("BOOT_SCAN")
    for port, url, kind in TARGETS:
        if probe(url):
            log("BOOT_OK " + kind)
            continue
        log("BOOT_START " + kind)
        restart(kind)
        up = False
        for _ in range(18):
            time.sleep(5)
            if probe(url):
                log("BOOT_UP " + kind)
                up = True
                break
        if not up:
            log("BOOT_STILL_DOWN " + kind)


def loop() -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    PIDF.write_text(str(os.getpid()), encoding="utf-8")
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass
    fails = {k: 0 for k, _, _ in TARGETS}
    log("START pid=" + str(os.getpid()))
    boot_missing()
    while not STOP.is_file():
        for port, url, kind in TARGETS:
            ok = probe(url)
            if ok:
                fails[port] = 0
                continue
            fails[port] += 1
            log(f"FAIL {kind} :{port} n={fails[port]}")
            if fails[port] >= FAILS:
                restart(kind)
                fails[port] = 0
                time.sleep(8)
        time.sleep(INTERVAL)
    log("STOP file")
    return 0


def main() -> int:
    ap_once = "--once" in sys.argv
    if "--ensure" in sys.argv:
        return ensure()
    if ap_once:
        bits = {k: probe(u) for k, u, _ in TARGETS}
        print(json.dumps({"ts": utc(), "health": bits}))
        return 0 if all(bits.values()) else 1
    return loop()


if __name__ == "__main__":
    raise SystemExit(main())
