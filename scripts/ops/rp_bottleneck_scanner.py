#!/usr/bin/env python3
"""Scan RP image pipeline bottlenecks and optionally auto-fix."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
try:
    from atomic_io import atomic_write_json
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore

STATE = ROOT / "state"
LOGS = ROOT / "logs"
REPORT = LOGS / "rp-bottleneck-report.json"
PY = ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe"
DEFAULT_CHANNEL = "1521146755985576116"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _lock_pid(lock_path: Path) -> int:
    if not lock_path.is_file():
        return 0
    try:
        return int(lock_path.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def _http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _process_running(pattern: str) -> bool:
    """True if any python/pythonw command line matches pattern. No PowerShell (focus steal)."""
    if os.name != "nt":
        return False
    try:
        import re

        pat = re.compile(pattern, re.I)
        # Pure WMI via ctypes-free path: use CreateProcess-less enumeration
        # through tasklist is lossy; use PowerShell only with CREATE_NO_WINDOW.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | "
                "ForEach-Object { $_.CommandLine }",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=flags,
        )
        for line in (proc.stdout or "").splitlines():
            if line and pat.search(line):
                return True
        return False
    except Exception:
        return False


def scan() -> dict:
    issues: list[dict] = []
    fixes_applied: list[str] = []
    checks: dict = {}

    render_lock = STATE / "roleplay-render.lock"
    daemon_lock = STATE / "comfy-delivery-daemon.lock"
    batch_file = STATE / "comfy-batch-session.json"
    posted_file = STATE / "comfy-discord-posted.json"
    daemon_state = STATE / "comfy-delivery-daemon.json"

    render_pid = _lock_pid(render_lock)
    checks["render_lock"] = {"path": str(render_lock), "pid": render_pid, "alive": _pid_alive(render_pid)}
    if render_pid and not _pid_alive(render_pid):
        issues.append({"code": "stale_render_lock", "severity": "high", "pid": render_pid})

    daemon_pid = _lock_pid(daemon_lock)
    daemon_alive = _pid_alive(daemon_pid)
    daemon_process = _process_running("comfy_delivery_daemon")
    checks["daemon_lock"] = {
        "path": str(daemon_lock),
        "pid": daemon_pid,
        "alive": daemon_alive,
        "process_running": daemon_process,
    }
    # filled after batch_active is known — see below

    batch: dict = {}
    if batch_file.is_file():
        try:
            batch = json.loads(batch_file.read_text(encoding="utf-8-sig"))
        except Exception:
            batch = {}
    checks["batch_session"] = batch
    batch_active = bool(batch.get("active"))
    checks["batch_active"] = batch_active

    if not daemon_alive and not daemon_process:
        if batch_active:
            issues.append({"code": "daemon_dead", "severity": "high", "pid": daemon_pid})
        else:
            issues.append({"code": "daemon_idle", "severity": "info", "pid": daemon_pid})

    checks["delivery_watcher"] = _process_running("watch_comfy_delivery")
    # When no RP batch is active, Comfy/watchers may be intentionally offline.
    # Do not spam cron as hard errors in idle state.
    if not checks["delivery_watcher"] and batch_active:
        issues.append({"code": "watcher_down", "severity": "medium"})
    elif not checks["delivery_watcher"]:
        issues.append({"code": "watcher_idle", "severity": "info"})

    # Production Comfy is 8189; 8188 is legacy. Prefer env COMFY_URL, else probe both.
    comfy_env = (os.environ.get("COMFY_URL") or "").strip().rstrip("/")
    comfy_candidates = []
    if comfy_env:
        comfy_candidates.append(comfy_env)
    for base in ("http://127.0.0.1:8189", "http://127.0.0.1:8188"):
        if base not in comfy_candidates:
            comfy_candidates.append(base)
    comfy_up = False
    comfy_url_hit = ""
    for base in comfy_candidates:
        if _http_ok(f"{base}/system_stats"):
            comfy_up = True
            comfy_url_hit = base
            break
    checks["comfy_up"] = comfy_up
    checks["comfy_url"] = comfy_url_hit or comfy_candidates[0]
    checks["comfy_8189"] = _http_ok("http://127.0.0.1:8189/system_stats")
    checks["comfy_8188"] = _http_ok("http://127.0.0.1:8188/system_stats")  # legacy probe
    if not comfy_up and batch_active:
        issues.append({"code": "comfy_down", "severity": "critical", "url": checks["comfy_url"]})
    elif not comfy_up:
        # Idle / intentional offline — info only (no score hit)
        issues.append({"code": "comfy_idle", "severity": "info", "url": checks["comfy_url"]})

    checks["gateway_8642"] = _http_ok("http://127.0.0.1:8642/health")
    if not checks["gateway_8642"]:
        issues.append({"code": "gateway_down", "severity": "high"})

    if batch_active:
        delivered = int(batch.get("delivered_count") or 0)
        total = int(batch.get("total") or 0)
        start = int(batch.get("series_start_png") or 0)
        if start and delivered < total:
            expected = start + delivered
            next_png = Path(rf"D:\ComfyUI\output\standard__{expected:05d}_.png")
            checks["next_expected_png"] = next_png.name
            render_done = int(batch.get("render_completed") or 0)
            queue_pending = 0
            try:
                from comfy_queue_client import queue_status as _qs  # noqa: WPS433

                q = _qs()
                queue_pending = len((q.get("queue_pending") or [])) if isinstance(q, dict) else 0
            except Exception:
                pass
            # Skip false alarm while Comfy still has work queued or renders ahead of delivery.
            if (
                delivered > 0
                and not next_png.is_file()
                and queue_pending == 0
                and render_done <= delivered
            ):
                issues.append(
                    {
                        "code": "batch_render_gap",
                        "severity": "medium",
                        "delivered": delivered,
                        "total": total,
                        "expected": next_png.name,
                    }
                )

    pipeline_metrics = STATE / "comfy-pipeline-metrics.json"
    if pipeline_metrics.is_file():
        try:
            checks["pipeline_metrics"] = json.loads(pipeline_metrics.read_text(encoding="utf-8-sig"))
        except Exception:
            checks["pipeline_metrics"] = {}
    else:
        try:
            from comfy_queue_client import comfy_up as _cu, queue_status as _qs

            if str(ROOT / "scripts" / "ops") not in sys.path:
                sys.path.insert(0, str(ROOT / "scripts" / "ops"))
            q = _qs()
            checks["pipeline_metrics"] = {
                "comfy_up": _cu(),
                "queue_running": len((q.get("queue_running") or [])),
                "queue_pending": len((q.get("queue_pending") or [])),
            }
        except Exception:
            pass

    if daemon_state.is_file() and posted_file.is_file():
        try:
            dstate = json.loads(daemon_state.read_text(encoding="utf-8-sig"))
            posted = json.loads(posted_file.read_text(encoding="utf-8-sig"))
            last = str(dstate.get("last_name") or "")
            if last and last not in (posted.get("names") or {}):
                issues.append({"code": "delivery_drift", "severity": "medium", "png": last})
        except Exception:
            pass

    score = 100
    for issue in issues:
        sev = issue.get("severity")
        if sev == "critical":
            score -= 30
        elif sev == "high":
            score -= 20
        elif sev == "medium":
            score -= 10
        elif sev == "info":
            score -= 0  # idle / intentional offline — not a failure
        else:
            score -= 5
    score = max(0, min(100, score))

    return {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "score": score,
        "checks": checks,
        "issues": issues,
        "fixes_applied": fixes_applied,
    }


def apply_fixes(report: dict, *, channel: str) -> dict:
    fixes: list[str] = []
    for issue in list(report.get("issues") or []):
        code = issue.get("code")
        if code == "stale_render_lock":
            lock = STATE / "roleplay-render.lock"
            lock.unlink(missing_ok=True)
            fixes.append("cleared_stale_render_lock")
        elif code in ("daemon_dead", "watcher_down"):
            ps1 = ROOT / "scripts" / "ops" / "Ensure-RP-Watchers.ps1"
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-WindowStyle",
                    "Hidden",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ps1),
                    "-Channel",
                    channel,
                    "-Quiet",
                ],
                timeout=30,
                check=False,
                creationflags=flags,
            )
            fixes.append(f"ensure_rp_watchers_{code}")
        elif code == "delivery_drift":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0
            subprocess.run(
                [str(PY), str(ROOT / "scripts" / "comfy_delivery_daemon.py"), "--once", "--channel", channel],
                timeout=90,
                check=False,
                creationflags=flags,
            )
            fixes.append("delivery_tick")
    report["fixes_applied"] = fixes
    if fixes:
        report["issues_after_fix"] = scan()["issues"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    report = scan()
    # Only auto-start watchers when a batch is actually active
    actionable = [
        i
        for i in (report.get("issues") or [])
        if i.get("severity") in ("critical", "high", "medium")
    ]
    if args.fix and actionable:
        report = apply_fixes(report, channel=args.channel)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    if atomic_write_json is not None:
        atomic_write_json(REPORT, report, indent=2, min_bytes=20)
    else:
        REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.json_only:
        print(json.dumps(report))
    else:
        print(f"RP bottleneck score: {report['score']}/100 issues={len(report.get('issues') or [])}")
        for issue in report.get("issues") or []:
            print(f"  - {issue.get('code')} ({issue.get('severity')})")
        if report.get("fixes_applied"):
            print(f"fixes: {', '.join(report['fixes_applied'])}")
        print(f"report: {REPORT}")
    # Cron contract: successful scan = 0. Hard-fail only when active batch still unhealthy.
    batch_active = bool((report.get("checks") or {}).get("batch_active"))
    if batch_active and report["score"] < 70:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())