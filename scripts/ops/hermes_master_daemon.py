#!/usr/bin/env python3
"""Local perpetual loop. Drop-Zone watch + weekly immune/sanity/fuzzy.

Maps, sanity, and sovereign queries run on 127.0.0.1 Ollama only.
Grok/xAI/OpenAI keys are stripped from child env so token expiry is a no-op.
Google writes still go through google_token_bucket inside child scripts.

  python D:\\HermesData\\scripts\\ops\\hermes_master_daemon.py
  python D:\\HermesData\\scripts\\ops\\hermes_master_daemon.py --once
  python D:\\HermesData\\scripts\\ops\\hermes_master_daemon.py --ensure
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

OPS = Path(r"D:\HermesData\scripts\ops")
STATE = Path(r"D:\HermesData\state")
INBOX = Path(r"K:\Phronesis-Sovereign\Drop-Zone\inbox")
QUAR = Path(r"K:\Phronesis-Sovereign\Drop-Zone\quarantine")
LOCK = STATE / "hermes_master_daemon.pid"
STAMP = STATE / "hermes_master_daemon.json"
LOG = STATE / "hermes_master_daemon.log"
PY = sys.executable
POLL = 45
WEEK = 7 * 24 * 3600
CLOUD_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "GROK_API_KEY",
    "GROK_API_TOKEN",
    "XAI_API_TOKEN",
)
SKIP_INBOX = frozenset({"put-files-here.txt", "readme.md", "sources.json"})


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    line = utc()[:19] + "Z " + msg
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def load_stamp() -> dict:
    if not STAMP.is_file():
        return {}
    try:
        return json.loads(STAMP.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_stamp(rec: dict) -> None:
    rec = dict(rec)
    rec["ts"] = utc()
    rec["pid"] = os.getpid()
    STAMP.write_text(json.dumps(rec, indent=2), encoding="utf-8")


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except SystemError:
        return False


def already_running() -> bool:
    if not LOCK.is_file():
        return False
    try:
        pid = int(LOCK.read_text(encoding="utf-8").strip() or "0")
    except ValueError:
        return False
    if pid == os.getpid():
        return False
    return pid_alive(pid)


def write_lock() -> None:
    LOCK.write_text(str(os.getpid()), encoding="utf-8")


def local_env() -> dict:
    env = os.environ.copy()
    env["OLLAMA_HOST"] = "127.0.0.1:11434"
    env["HERMES_LOCAL_ONLY"] = "1"
    for k in CLOUD_KEYS:
        env.pop(k, None)
    return env


def inbox_sig() -> str:
    if not INBOX.is_dir():
        return ""
    rows = []
    for p in INBOX.iterdir():
        if p.name.startswith(".") or p.name.lower() in SKIP_INBOX:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        rows.append(f"{p.name}:{int(st.st_mtime)}:{st.st_size}")
    rows.sort()
    return "|".join(rows)


CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _pythonw() -> str:
    exe = Path(PY)
    if exe.name.lower() == "python.exe":
        alt = exe.with_name("pythonw.exe")
        if alt.is_file():
            return str(alt)
    venvw = Path(r"D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe")
    if venvw.is_file():
        return str(venvw)
    return PY


def run(script: str, args: list[str] | None = None) -> int:
    cmd = [PY, "-u", str(OPS / script), *(args or [])]
    try:
        r = subprocess.run(
            cmd,
            cwd=str(OPS),
            capture_output=True,
            text=True,
            timeout=3600,
            env=local_env(),
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        log("TIMEOUT " + script)
        return 1
    except Exception as e:
        log("RUN_FAIL " + script + " " + type(e).__name__)
        return 1
    tail = ((r.stdout or "") + (r.stderr or ""))[-300:].replace("\n", " ")
    log(script + " rc=" + str(r.returncode) + " " + tail[:200])
    return r.returncode


def quarantine_new(st: dict) -> None:
    QUAR.mkdir(parents=True, exist_ok=True)
    last = st.get("inbox_sig") or ""
    known = set()
    for bit in last.split("|"):
        if bit:
            known.add(bit.split(":")[0])
    if not INBOX.is_dir():
        return
    for p in list(INBOX.iterdir()):
        if p.name.startswith(".") or p.name.lower() in SKIP_INBOX:
            continue
        if p.name in known:
            continue
        dest = QUAR / (utc()[:19].replace(":", "") + "_" + p.name)
        try:
            p.replace(dest)
            log("quarantine " + p.name + " → " + dest.name)
        except OSError as e:
            log("quarantine fail " + p.name + " " + type(e).__name__)


def tick(st: dict) -> dict:
    try:
        run("grok_wallet_sunset.py")
        run("sovereign_supervisor.py", ["--ensure"])
        sig = inbox_sig()
        if sig and sig != st.get("inbox_sig"):
            log("inbox change → ingest")
            rc = run("universal_ingestor.py")
            if rc != 0:
                quarantine_new(st)
            else:
                run("contacts_comms_sync.py")
                st["inbox_sig"] = sig
                st["last_ingest"] = utc()
        last_w = st.get("last_weekly_unix")
        now = time.time()
        if last_w is None:
            st["last_weekly_unix"] = now
            st["last_weekly"] = utc()
        elif now - float(last_w or 0) >= WEEK:
            log("weekly sanity + fuzzy + immune")
            run("contacts_sanity_check.py")
            run("fuzzy_deconfliction.py")
            run("global_sanity.py")
            st["last_weekly_unix"] = now
            st["last_weekly"] = utc()
        st["heartbeat"] = utc()
        st["local_only"] = True
        st["ollama"] = "http://127.0.0.1:11434"
        save_stamp(st)
    except Exception as e:
        log("TICK_FAIL " + type(e).__name__)
        st["last_error"] = type(e).__name__
        try:
            save_stamp(st)
        except Exception:
            pass
    return st


def spawn_detached() -> int:
    if already_running():
        print("HERMES_MASTER_DAEMON already", flush=True)
        return 0
    STATE.mkdir(parents=True, exist_ok=True)
    py = str(PY)
    script = str(OPS / "hermes_master_daemon.py")
    if sys.platform == "win32":
        # WMI Create lands outside the tool Job Object. Popen/wscript children die with the job.
        pyw = _pythonw()
        cmdline = f'"{pyw}" "{script}"'
        ps1 = STATE / "hermes_master_daemon_launch.ps1"
        ps1.write_text(
            "$cmd = @'\n"
            f"{cmdline}\n"
            "'@\n"
            "$p = Invoke-WmiMethod -Class Win32_Process -Name Create -ArgumentList $cmd\n"
            "if ($null -eq $p -or $p.ReturnValue -ne 0) { exit 1 }\n"
            "Write-Output $p.ProcessId\n",
            encoding="ascii",
        )
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-File", str(ps1)],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            log("WMI spawn fail " + (r.stderr or r.stdout or "")[:200])
            return 1
        print("HERMES_MASTER_DAEMON spawned", flush=True)
        return 0
    logf = LOG.open("a", encoding="utf-8")
    subprocess.Popen(
        [_pythonw(), script],
        cwd=str(OPS),
        stdout=logf,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        creationflags=CREATE_NO_WINDOW,
    )
    print("HERMES_MASTER_DAEMON spawned", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--ensure", action="store_true")
    ap.add_argument("--hours", type=float, default=0.0)
    args = ap.parse_args()
    if args.ensure:
        return spawn_detached()
    if already_running() and not args.once:
        print("HERMES_MASTER_DAEMON already", flush=True)
        return 0
    write_lock()
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass
    os.environ["OLLAMA_HOST"] = "127.0.0.1:11434"
    os.environ["HERMES_LOCAL_ONLY"] = "1"
    for k in CLOUD_KEYS:
        os.environ.pop(k, None)
    INBOX.mkdir(parents=True, exist_ok=True)
    QUAR.mkdir(parents=True, exist_ok=True)
    st = load_stamp()
    log("start pid=" + str(os.getpid()) + " local_only=1 ollama=127.0.0.1:11434")
    if args.once:
        tick(st)
        print("HERMES_MASTER_DAEMON once", flush=True)
        return 0
    deadline = time.time() + args.hours * 3600 if args.hours > 0 else 0.0
    while True:
        try:
            st = tick(st)
            if deadline and time.time() >= deadline:
                log("hours elapsed — looping anyway")
                deadline = 0.0
            time.sleep(POLL)
        except KeyboardInterrupt:
            log("interrupt ignored — daemon stays up")
            time.sleep(POLL)
        except Exception as e:
            log("LOOP_FAIL " + type(e).__name__)
            time.sleep(POLL)


if __name__ == "__main__":
    raise SystemExit(main())
