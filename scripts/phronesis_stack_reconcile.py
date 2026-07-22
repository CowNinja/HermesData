#!/usr/bin/env python3
"""Reconcile Phronesis/Hermes stack: no duplicate daemons, no console flashes.

- Clear stale *.lock files when claimed PID is dead
- Report (and optionally start) singleton roles: gateway, proxy, continuous, bridge, supervisor
- Prefer pythonw + CREATE_NO_WINDOW for all starts
- Does NOT kill healthy venv+base python pairs (normal Windows re-exec)

Usage:
  pythonw D:\\HermesData\\scripts\\phronesis_stack_reconcile.py
  python  D:\\HermesData\\scripts\\phronesis_stack_reconcile.py --start-missing
  python  D:\\HermesData\\scripts\\phronesis_stack_reconcile.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from atomic_io import atomic_write_json
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore

ROOT = Path(r"D:\HermesData")
SCRIPTS = ROOT / "scripts"
STATE = ROOT / "state"
LOG = ROOT / "logs" / "stack-reconcile.log"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)

VENV_PYW = ROOT / "hermes-agent" / "venv" / "Scripts" / "pythonw.exe"
SYS_PYW = Path(r"C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {msg}"
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            timeout=12,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        out = (r.stdout or "").strip()
        return str(pid) in out and "No tasks" not in out
    except Exception:
        return False


def list_procs(pattern: str) -> list[dict]:
    ps = (
        "Get-CimInstance Win32_Process | Where-Object { "
        "$_.CommandLine -and $_.Name -match 'python|wscript|llama' -and "
        f"$_.CommandLine -match '{pattern}' "
        "} | ForEach-Object { "
        "\"$($_.ProcessId)|$($_.Name)|$($_.CommandLine)\" }"
    )
    out: list[dict] = []
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            timeout=40,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            pid_s, name, *rest = line.split("|", 2)
            cmd = rest[0] if rest else ""
            if "phronesis_stack_reconcile" in cmd or "Write-Host" in cmd:
                continue
            try:
                out.append({"pid": int(pid_s), "name": name, "cmd": cmd[:240]})
            except ValueError:
                continue
    except Exception as exc:
        log(f"list_procs err: {exc}")
    return out


def port_listen(port: int) -> int | None:
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                f"(Get-NetTCPConnection -LocalPort {port} -State Listen -EA SilentlyContinue | Select-Object -First 1).OwningProcess",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        s = (r.stdout or "").strip()
        return int(s) if s.isdigit() else None
    except Exception:
        return None


def health(port: int) -> bool:
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/health",
            headers={"User-Agent": "stack-reconcile/1.0"},
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:
        return False


def clear_stale_lock(path: Path) -> str:
    if not path.is_file():
        return "absent"
    try:
        raw = path.read_text(encoding="utf-8").strip()
        m = re.search(r'"pid"\s*:\s*(\d+)', raw) or re.search(r"^(\d+)", raw)
        claim = int(m.group(1)) if m else 0
        if claim and pid_alive(claim):
            return f"kept live pid={claim}"
        path.unlink(missing_ok=True)
        return f"cleared dead claim={claim or raw[:40]}"
    except Exception as exc:
        return f"error {exc}"


def start_hidden(args: list[str], *, cwd: Path | None = None) -> None:
    env = os.environ.copy()
    env["HERMES_HOME"] = str(ROOT)
    env["HERMES_CONFIG_PATH"] = str(ROOT / "config.yaml")
    env["PHRONESIS_BOOT_INTEGRITY_FAIL"] = "warn"
    env["PHRONESIS_BOOT_INTEGRITY_MODE"] = "fast"
    flags = CREATE_NO_WINDOW | DETACHED | NEW_GROUP
    subprocess.Popen(
        args,
        cwd=str(cwd or ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags if sys.platform == "win32" else 0,
        close_fds=True,
        env=env,
    )


def pyw() -> str:
    if VENV_PYW.is_file():
        return str(VENV_PYW)
    if SYS_PYW.is_file():
        return str(SYS_PYW)
    return sys.executable


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-missing", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report: dict = {"ts": utc(), "actions": [], "roles": {}, "ports": {}, "locks": {}}

    # --- locks ---
    for name in (
        "gateway-keepalive.lock",
        "gateway-supervisor.lock",
        "silo_continuous.lock",
        "silo_continuous.pid",
        "grok-direct-bridge.lock",
    ):
        p = STATE / name
        # only clear .lock/.pid if dead
        result = clear_stale_lock(p) if p.suffix in {".lock", ".pid"} or name.endswith(".lock") else clear_stale_lock(p)
        report["locks"][name] = result
        if result.startswith("cleared"):
            report["actions"].append(f"lock:{name}:{result}")
            log(f"lock {name}: {result}")

    for name in ("gateway.pid", "gateway.lock", "gateway_state.json"):
        p = ROOT / name
        if not p.is_file():
            continue
        try:
            raw = p.read_text(encoding="utf-8")
            m = re.search(r'"pid"\s*:\s*(\d+)', raw)
            claim = int(m.group(1)) if m else 0
            if claim and not pid_alive(claim) and not port_listen(8642):
                p.unlink(missing_ok=True)
                report["actions"].append(f"cleared_stale_{name}")
                log(f"cleared stale {name} pid={claim}")
        except Exception:
            pass

    # --- roles ---
    roles = {
        "gateway": r"gateway\.run|hermes_cli\.main gateway",
        "proxy": r"sovereign_openai_proxy",
        "continuous": r"silo_continuous_loop\.py",
        "supervisor": r"hermes_gateway_supervisor\.py",
        "keepalive": r"Phronesis-Gateway-Keepalive",
        "bridge": r"discord_grok_bridge",
        "overnight_wd": r"silo_overnight_watchdog\.py",
        "autonomous_wd": r"silo_autonomous_watchdog\.py",
    }
    for role, pat in roles.items():
        procs = list_procs(pat)
        report["roles"][role] = {"count": len(procs), "pids": [p["pid"] for p in procs], "procs": procs}

    for port in (8090, 8091, 8642):
        owner = port_listen(port)
        report["ports"][str(port)] = {
            "listen_pid": owner,
            "health": health(port) if owner or port == 8642 else False,
        }

    # proxy/bridge: 2 pythonw (venv parent + base child) is NORMAL
    for role in ("proxy", "bridge"):
        c = report["roles"][role]["count"]
        if c > 2:
            report["actions"].append(f"WARN {role} count={c} (>2 may be real duplicate)")
            log(f"WARN {role} process count={c}")

    if args.start_missing:
        # supervisor — count venv+base re-exec as one instance (2 PIDs OK)
        if report["roles"]["supervisor"]["count"] == 0:
            start_hidden([pyw(), str(SCRIPTS / "hermes_gateway_supervisor.py")])
            report["actions"].append("started_supervisor")
            log("started supervisor")
            time.sleep(1)
        elif report["roles"]["supervisor"]["count"] > 2:
            report["actions"].append(
                f"WARN supervisor count={report['roles']['supervisor']['count']} (expected 1–2 for re-exec)"
            )

        # gateway — SSOT owner first (schtask), never -m gateway.run dual-argv
        if not report["ports"]["8642"]["listen_pid"] or not health(8642):
            try:
                import subprocess as _sp

                _sp.call(
                    ["schtasks", "/Run", "/TN", "Hermes_Gateway"],
                    timeout=60,
                    stdout=_sp.DEVNULL,
                    stderr=_sp.DEVNULL,
                )
                report["actions"].append("started_gateway_schtask")
                log("started gateway via Hermes_Gateway schtask")
            except Exception as exc:
                log(f"schtask gateway start err: {exc}")
                start_hidden(
                    [pyw(), "-m", "hermes_cli.main", "gateway", "run"], cwd=ROOT
                )
                report["actions"].append("started_gateway_direct_hermes_cli")
                log("started gateway direct hermes_cli.main")
            # wait health
            for _ in range(35):
                if health(8642):
                    break
                time.sleep(2)
            report["ports"]["8642"] = {
                "listen_pid": port_listen(8642),
                "health": health(8642),
            }

        # continuous via hidden VBS
        if report["roles"]["continuous"]["count"] == 0:
            vbs = SCRIPTS / "start_silo_continuous_only_hidden.vbs"
            if vbs.is_file():
                start_hidden(["wscript.exe", "//B", str(vbs)])
                report["actions"].append("started_continuous_vbs")
                log("started continuous via VBS")

        # keepalive (secondary; supervisor is primary)
        if report["roles"]["keepalive"]["count"] == 0:
            vbs = SCRIPTS / "Start-Gateway-Keepalive-Hidden.vbs"
            if vbs.is_file():
                start_hidden(["wscript.exe", "//B", str(vbs)])
                report["actions"].append("started_keepalive_vbs")
                log("started keepalive VBS")

        # refresh role counts
        for role, pat in roles.items():
            procs = list_procs(pat)
            report["roles"][role] = {
                "count": len(procs),
                "pids": [p["pid"] for p in procs],
            }

    # scheduled-task policy notes (cannot always disable without elevation)
    report["task_policy"] = {
        "prefer": [
            "Phronesis-Guardian-Hidden (not bare Phronesis-Guardian if both fire)",
            "Phronesis-Grok-Direct-Bridge-Hidden (not bare Bridge PS)",
            "Hermes_Silo_Overnight_Watchdog owns continuous; Autonomous owns sprint only",
            "hermes_gateway_supervisor.py is primary :8642 restarter (15s)",
        ],
        "disable_if_admin": [
            "Phronesis-Image-Rider without -WindowStyle Hidden",
            "Phronesis-Grok-Hermes-Loop using python.exe (use pythonw)",
            "Duplicate Bridge/Guardian non-Hidden tasks if Hidden pair is healthy",
        ],
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        log(
            f"summary gateway_health={report['ports'].get('8642', {}).get('health')} "
            f"proxy={report['roles'].get('proxy', {}).get('count')} "
            f"continuous={report['roles'].get('continuous', {}).get('count')} "
            f"supervisor={report['roles'].get('supervisor', {}).get('count')} "
            f"actions={len(report['actions'])}"
        )
        # write latest json
        try:
            out = ROOT / "logs" / "stack-reconcile-latest.json"
            if atomic_write_json is not None:
                atomic_write_json(out, report, indent=2, min_bytes=20)
            else:
                out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except Exception:
            pass
    return 0 if report["ports"].get("8642", {}).get("health") or not args.start_missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
