#!/usr/bin/env python3
"""Hermes no_agent bridge for model_management_agent light/full ticks.

Used by Hermes cron (jobs.json). Prefer this over PowerShell so no_agent script
runner stays Python-only under D:\\HermesData\\scripts.

Resilience (2026-07-18 research pass):
- Single-instance lock (skip if sibling tick still running)
- Subprocess timeout (light 10m / full 45m)
- One retry on non-zero exit (transient GPU/proxy blip)
- PYTHONPATH always includes Hermes + vault scripts

Usage:
  python model_management_cron_bridge.py light
  python model_management_cron_bridge.py full
  python model_mgmt_light_cron.py
  python model_mgmt_full_cron.py
"""
from __future__ import annotations

import atexit
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
AGENT = SCRIPTS / "model_management_agent.py"
DEFAULT_PY = Path(r"D:\HermesData\hermes-agent\venv\Scripts\python.exe")
LOCK_DIR = Path(r"D:\PhronesisVault\Operations\logs")
STATE_PATH = Path(r"D:\PhronesisVault\Operations\model-management-agent-state.json")
BRIDGE_JSONL = LOCK_DIR / "model-management-cron-bridge.jsonl"
# Stale lock older than this is stolen (crashed prior run).
LOCK_STALE_SEC = 3600
TIMEOUT_LIGHT_SEC = 600
TIMEOUT_FULL_SEC = 2700
MAX_ATTEMPTS = 2


def _resolve_python() -> str:
    core = SCRIPTS / "phronesis-core.json"
    if core.is_file():
        try:
            import json

            data = json.loads(core.read_text(encoding="utf-8-sig"))
            vp = data.get("venv_python")
            if vp and Path(vp).is_file():
                return str(vp)
        except Exception:
            pass
    if DEFAULT_PY.is_file():
        return str(DEFAULT_PY)
    return sys.executable


def _lock_path(mode: str) -> Path:
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    return LOCK_DIR / f"model-mgmt-{mode}.lock"


def _pid_alive(pid: int) -> bool:
    """True if process exists. Windows: OpenProcess (os.kill signal 0 is unreliable)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def _try_acquire_lock(mode: str) -> Path | None:
    """Exclusive lock file. Returns path if acquired, else None (skip run)."""
    path = _lock_path(mode)
    now = time.time()
    if path.is_file():
        try:
            age = now - path.stat().st_mtime
            text = path.read_text(encoding="utf-8").strip()
            old_pid = int(text.split()[0]) if text else 0
        except Exception:
            age, old_pid = 0, 0
        if age < LOCK_STALE_SEC and _pid_alive(old_pid):
            print(
                f"[model_mgmt_cron] SKIP mode={mode}: lock held by pid={old_pid} age={int(age)}s",
                flush=True,
            )
            return None
        try:
            path.unlink(missing_ok=True)  # type: ignore[call-arg]
        except TypeError:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        except Exception:
            pass
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, f"{os.getpid()} {now}\n".encode("utf-8"))
        finally:
            os.close(fd)
    except FileExistsError:
        print(f"[model_mgmt_cron] SKIP mode={mode}: lock race", flush=True)
        return None
    except Exception as exc:
        print(f"[model_mgmt_cron] WARN lock_acquire_failed: {exc}", flush=True)
        return path  # proceed without hard lock

    def _release() -> None:
        try:
            if path.is_file():
                path.unlink()
        except Exception:
            pass

    atexit.register(_release)
    return path


def _write_bridge_receipt(mode: str, rc: int, attempts: int, elapsed_s: float) -> None:
    """Durable cron proof: JSON snapshot + JSONL append (rotated)."""
    import json
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    status = "ok" if rc == 0 else "fail"
    snap: dict = {
        "timestamp": now,
        "mode": mode,
        "exit_code": rc,
        "status": status,
        "attempts": attempts,
        "elapsed_s": round(elapsed_s, 3),
        "agent": str(AGENT),
        "state_path": str(STATE_PATH),
    }
    try:
        if STATE_PATH.is_file():
            state = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
            snap["agent_status"] = state.get("status")
            snap["agent_mode"] = state.get("mode")
            snap["agent_updated_at"] = state.get("updated_at")
            issues = state.get("issues") or []
            snap["issue_codes"] = [
                (i.get("code") if isinstance(i, dict) else str(i)) for i in issues[:24]
            ]
            local = (state.get("assessments") or {}).get("local") or {}
            smoke = local.get("smoke") if isinstance(local, dict) else None
            if isinstance(smoke, dict):
                snap["smoke_ok"] = smoke.get("ok")
                snap["smoke_latency_ms"] = smoke.get("latency_ms")
                snap["smoke_slo"] = smoke.get("slo")
            stack = state.get("stack") or {}
            if isinstance(stack, dict):
                snap["stack_ready"] = stack.get("stack_ready")
                # Prefer scalar status/color; "overall" may be a nested dict
                color = stack.get("status") or stack.get("stack_color")
                overall = stack.get("overall")
                if color is None and isinstance(overall, str):
                    color = overall
                elif color is None and isinstance(overall, dict):
                    color = overall.get("status") or overall.get("color")
                snap["stack_color"] = color
    except Exception as exc:
        snap["state_read_error"] = str(exc)[:200]

    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    # Per-mode latest snapshot (easy human/cron proof path)
    snap_path = LOCK_DIR / f"model-mgmt-cron-{mode}.json"
    try:
        snap_path.write_text(json.dumps(snap, indent=2, default=str) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"[model_mgmt_cron] WARN snap_write: {exc}", flush=True)

    # Append JSONL history (size-rotate)
    try:
        try:
            sys.path.insert(0, str(SCRIPTS))
            from jsonl_log_rotator import append_jsonl as _rot_append

            _rot_append(BRIDGE_JSONL, snap, mode="rename", stamp=False)
        except Exception:
            with open(BRIDGE_JSONL, "a", encoding="utf-8") as f:
                f.write(json.dumps(snap, default=str) + "\n")
    except Exception as exc:
        print(f"[model_mgmt_cron] WARN jsonl_write: {exc}", flush=True)

    print(
        f"[model_mgmt_cron] receipt mode={mode} rc={rc} status={status} "
        f"snap={snap_path} issues={snap.get('issue_codes')}",
        flush=True,
    )


def run(mode: str) -> int:
    mode = (mode or "light").strip().lower()
    if mode not in ("light", "full"):
        print(f"unknown mode: {mode!r} (use light|full)", file=sys.stderr)
        return 2
    if not AGENT.is_file():
        print(f"missing agent: {AGENT}", file=sys.stderr)
        return 2

    lock = _try_acquire_lock(mode)
    if lock is None:
        # Overlap is not a hard failure for the scheduler — next slot retries.
        return 0

    py = _resolve_python()
    args = [py, str(AGENT)]
    if mode == "full":
        args.append("--full-tick")
        timeout = TIMEOUT_FULL_SEC
    else:
        args.append("--tick")
        timeout = TIMEOUT_LIGHT_SEC
    args.append("--summary")

    env = os.environ.copy()
    extra = f"{SCRIPTS};D:\\PhronesisVault\\scripts"
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{extra};{prev}" if prev else extra

    t0 = time.time()
    last_rc = 1
    attempts_used = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempts_used = attempt
        print(
            f"[model_mgmt_cron] mode={mode} attempt={attempt}/{MAX_ATTEMPTS} "
            f"timeout={timeout}s cmd={' '.join(args)}",
            flush=True,
        )
        try:
            proc = subprocess.run(
                args,
                env=env,
                cwd=str(SCRIPTS),
                timeout=timeout,
            )
            last_rc = int(proc.returncode)
        except subprocess.TimeoutExpired:
            print(f"[model_mgmt_cron] TIMEOUT mode={mode} after {timeout}s", flush=True)
            last_rc = 124
        except Exception as exc:
            print(f"[model_mgmt_cron] ERROR mode={mode}: {exc}", flush=True)
            last_rc = 1

        if last_rc == 0:
            print(f"[model_mgmt_cron] OK mode={mode}", flush=True)
            _write_bridge_receipt(mode, last_rc, attempts_used, time.time() - t0)
            return 0
        if attempt < MAX_ATTEMPTS:
            time.sleep(5.0 * attempt)

    print(f"[model_mgmt_cron] FAIL mode={mode} rc={last_rc}", flush=True)
    _write_bridge_receipt(mode, last_rc, attempts_used, time.time() - t0)
    return last_rc


def main(argv: list[str] | None = None) -> int:
    av = list(argv if argv is not None else sys.argv[1:])
    mode = av[0] if av else "light"
    return run(mode)


if __name__ == "__main__":
    raise SystemExit(main())
