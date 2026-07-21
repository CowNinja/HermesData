#!/usr/bin/env python3
"""Resource-aware continuous silo builder.

Goal: constant G->K cook + light enrich WITHOUT crashing the box.
Monitors VRAM/RAM/disk; backs off when Comfy or system is hot.

Modes (auto):
  aggressive - free GPU/RAM, larger drain
  normal     - default
  gentle     - Comfy/VRAM high: scripts only, smaller batches, longer sleep
  pause      - critical resources; sleep only

Usage:
  python D:\\HermesData\\scripts\\silo_continuous_loop.py --once
  python D:\\HermesData\\scripts\\silo_continuous_loop.py --max-cycles 0
      # 0 = forever until Ctrl+C or STOP file

Stop file: D:\\HermesData\\state\\silo_continuous.STOP
State:     D:\\HermesData\\state\\silo_continuous_state.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

try:
    from atomic_io import atomic_write_json, atomic_write_text
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore
    atomic_write_text = None  # type: ignore

# Detach console immediately so hidden python.exe never steals focus while typing.
try:
    from win_free_console import free_console  # type: ignore

    free_console()
except Exception:
    try:
        import ctypes

        if sys.platform == "win32":
            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass

SCRIPTS = Path(r"D:\HermesData\scripts")
STATE = Path(r"D:\HermesData\state\silo_continuous_state.json")
VRAM_STATE = Path(r"D:\HermesData\state\vram-priority.json")
STOP = Path(r"D:\HermesData\state\silo_continuous.STOP")

LOCK = Path(r"D:\HermesData\state\silo_continuous.lock")


def _pid_alive(pid: int) -> bool:
    try:
        import ctypes

        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))
        if h:
            k.CloseHandle(h)
            return True
        return False
    except Exception:
        return False


def acquire_singleton() -> bool:
    """Only one continuous land owner. Stale lock safe."""
    if LOCK.is_file():
        try:
            pid = int(LOCK.read_text(encoding="utf-8").split()[0])
            # Never use bare wmic/powershell here - that flashes conhost on Windows.
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/V"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=flags if sys.platform == "win32" else 0,
            )
            out = ((r.stdout or "") + (r.stderr or "")).lower()
            if str(pid) in out and "silo_continuous" in out:
                return False
            # If process alive but title unknown, still treat as owned if pid alive
            if _pid_alive(pid) and "no tasks" not in out:
                # second check: command line via CIM hidden
                r2 = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-NonInteractive",
                        "-WindowStyle",
                        "Hidden",
                        "-Command",
                        f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    creationflags=flags if sys.platform == "win32" else 0,
                )
                if "silo_continuous_loop" in ((r2.stdout or "") + (r2.stderr or "")):
                    return False
        except Exception:
            pass
        try:
            LOCK.unlink(missing_ok=True)
        except Exception:
            pass
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    lock_body = str(__import__("os").getpid()) + " " + datetime.now(timezone.utc).isoformat() + chr(10)
    if atomic_write_text is not None:
        atomic_write_text(LOCK, lock_body, min_bytes=1)
    else:
        LOCK.write_text(lock_body, encoding="utf-8")
    return True



def release_singleton() -> None:
    import os

    try:
        if not LOCK.is_file():
            return
        txt = LOCK.read_text(encoding="utf-8").strip()
        if txt.startswith(str(os.getpid())):
            LOCK.unlink(missing_ok=True)
    except Exception:
        pass


LOG = Path(r"D:\PhronesisVault\Operations\logs\silo-continuous-loop-latest.md")

# Thresholds (RTX 3060 12GB class)
VRAM_GENTLE_MIB = 9000      # above -> no local LLM grunt (dual-stack / Comfy hot)
VRAM_SILO_PRIMARY_GENTLE_MIB = 11000  # Qwythos-only baseline ~9.3GB is expected
VRAM_PAUSE_MIB = 11800      # above -> pause cook
RAM_GENTLE_PCT = 85
RAM_PAUSE_PCT = 93
DISK_K_MIN_GB = 50
DISK_D_MIN_GB = 30


def _worker_python() -> str:
    """Prefer pythonw for child workers so they never allocate a console."""
    try:
        from windows_subprocess import prefer_pythonw  # type: ignore

        return prefer_pythonw(sys.executable)
    except Exception:
        exe = Path(sys.executable)
        pyw = exe.with_name("pythonw.exe")
        return str(pyw) if pyw.is_file() else sys.executable


def _run(cmd, timeout=120) -> Tuple[int, str]:
    """Run child; for long timeouts pulse tick heartbeat so supervisors see liveness."""
    try:
        # CREATE_NO_WINDOW: child ticks must not flash conhost / steal focus.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        # Normalize python.exe -> pythonw.exe for Hermes script children
        if (
            sys.platform == "win32"
            and isinstance(cmd, (list, tuple))
            and cmd
            and str(cmd[0]).lower().endswith("python.exe")
        ):
            cmd = list(cmd)
            cmd[0] = _worker_python()
        # Short commands: simple run
        if timeout <= 120:
            p = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=flags if sys.platform == "win32" else 0,
            )
            return p.returncode, ((p.stdout or "") + (p.stderr or ""))[-2000:]
        # Long tick: Popen + heartbeat pulse every 60s (stall visibility)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=flags if sys.platform == "win32" else 0,
        )
        t0 = time.time()
        while True:
            try:
                out, err = proc.communicate(timeout=60)
                code = int(proc.returncode or 0)
                return code, ((out or "") + (err or ""))[-2000:]
            except subprocess.TimeoutExpired:
                elapsed = time.time() - t0
                if elapsed >= timeout:
                    # Tree-kill: parent-only kill orphans drain/focus (dual-writer).
                    try:
                        from windows_subprocess import kill_process_tree  # type: ignore

                        kill_process_tree(int(proc.pid or 0))
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    try:
                        out, err = proc.communicate(timeout=15)
                    except Exception:
                        out, err = "", ""
                    return 124, f"timeout {timeout}s after {elapsed:.0f}s tree-killed\n" + (
                        (out or "") + (err or "")
                    )[-1500:]
                # pulse heartbeat / phase so external watchers don't false-dead
                try:
                    hb = {
                        "at": datetime.now(timezone.utc).isoformat(),
                        "phase": "tick_running",
                        "elapsed_s": int(elapsed),
                        "child_pid": proc.pid,
                    }
                    hb_path = Path(r"D:/HermesData/state") / "silo_tick_heartbeat.json"
                    if atomic_write_json is not None:
                        atomic_write_json(hb_path, hb, indent=2, min_bytes=20)
                    else:
                        hb_path.write_text(json.dumps(hb, indent=2), encoding="utf-8")
                    if STATE.is_file():
                        cur = json.loads(STATE.read_text(encoding="utf-8"))
                        if isinstance(cur, dict):
                            cur["phase"] = "tick_running"
                            cur["heartbeat_at"] = hb["at"]
                            cur["tick_elapsed_s"] = int(elapsed)
                            if atomic_write_json is not None:
                                atomic_write_json(STATE, cur, indent=2, min_bytes=20)
                            else:
                                STATE.write_text(json.dumps(cur, indent=2), encoding="utf-8")
                except Exception:
                    pass
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


def vram_used_mib() -> int | None:
    code, out = _run(
        [
            "nvidia-smi",
            "--query-gpu=memory.used",
            "--format=csv,noheader,nounits",
        ],
        10,
    )
    if code != 0:
        return None
    try:
        return int(out.strip().splitlines()[0].strip())
    except Exception:
        return None


def ram_used_pct() -> float | None:
    try:
        import psutil  # type: ignore

        return float(psutil.virtual_memory().percent)
    except Exception:
        # fallback wmic-ish via powershell
        code, out = _run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_OperatingSystem | "
                "ForEach-Object { [math]::Round(100*($_.TotalVisibleMemorySize-$_.FreePhysicalMemory)/$_.TotalVisibleMemorySize,1) })",
            ],
            15,
        )
        try:
            return float(out.strip().splitlines()[-1])
        except Exception:
            return None


def disk_free_gb(root: str) -> float | None:
    try:
        u = shutil.disk_usage(root)
        return u.free / (1024**3)
    except Exception:
        return None


def silo_primary_active() -> bool:
    if not VRAM_STATE.is_file():
        return False
    try:
        data = json.loads(VRAM_STATE.read_text(encoding="utf-8-sig"))
        return bool(data.get("silo_primary")) and str(data.get("mode", "")).lower() == "text"
    except Exception:
        return False


def port_up(port: int) -> bool:
    import urllib.request

    for path in (f"http://127.0.0.1:{port}/health", f"http://127.0.0.1:{port}/"):
        try:
            with urllib.request.urlopen(path, timeout=1.5) as r:
                return True
        except Exception:
            continue
    return False


def image_gpu_lock_held() -> tuple[bool, str]:
    """Yield to Forge/image gen when GPU tenant lock is held (2026-07-21 codify)."""
    try:
        from image_job_lock import status as ls

        st = ls()
        if st.get("held") and not st.get("stale"):
            meta = st.get("meta") or {}
            return True, f"image_lock owner={meta.get('owner')} job={meta.get('job')}"
    except Exception:
        pass
    return False, ""


def assess() -> Dict[str, Any]:
    vram = vram_used_mib()
    ram = ram_used_pct()
    k_free = disk_free_gb("K:\\")
    d_free = disk_free_gb("D:\\")
    qwy = port_up(8090)
    proxy = port_up(8091)
    comfy = port_up(8188)
    img_held, img_reason = image_gpu_lock_held()

    mode = "normal"
    reasons = []
    if k_free is not None and k_free < DISK_K_MIN_GB:
        mode = "pause"
        reasons.append(f"K free {k_free:.0f}GB < {DISK_K_MIN_GB}")
    if d_free is not None and d_free < DISK_D_MIN_GB:
        mode = "pause"
        reasons.append(f"D free {d_free:.0f}GB < {DISK_D_MIN_GB}")
    # Image gen owns GPU - never aggressive; pause enrich/grunt (drain may still gentle)
    if img_held:
        mode = "gentle"
        reasons.append(f"yield_image_gpu: {img_reason}")
    if vram is not None and vram >= VRAM_PAUSE_MIB:
        # Critical VRAM: pause unless only image lock (then already gentle)
        if not img_held:
            mode = "pause"
            reasons.append(f"VRAM {vram}MiB critical")
        else:
            mode = "gentle"
            reasons.append(f"VRAM {vram}MiB critical + image_lock - gentle land only")
    elif ram is not None and ram >= RAM_PAUSE_PCT:
        mode = "pause"
        reasons.append(f"RAM {ram}% critical")
    # Disk copy does NOT need GPU. Only pause when system is critically loaded.
    # "gentle" = reduce enrich/train + disable Qwythos grunt, NOT starve drain.
    elif mode != "gentle" and ram is not None and ram >= RAM_GENTLE_PCT:
        mode = "gentle"
        reasons.append(f"RAM {ram}% high")
    elif mode != "gentle" and (
            silo_primary_active()
            and qwy
            and not comfy
            and vram is not None
            and vram < VRAM_PAUSE_MIB
            and not img_held
        ):
            # Jeff overnight high-gear 2026-07-13: silo_primary still aggressive land
            mode = "aggressive"
            reasons.append(
                f"silo_primary overnight high-gear - VRAM {vram}MiB Qwythos-only, drain max"
            )
    elif mode != "gentle" and vram is not None and vram >= (
        VRAM_SILO_PRIMARY_GENTLE_MIB if silo_primary_active() else VRAM_GENTLE_MIB
    ):
        mode = "gentle"
        reasons.append(f"VRAM {vram}MiB high - drain full, no LLM grunt")
    elif mode != "gentle":
        mode = "aggressive" if (k_free or 0) > 200 else "normal"
        reasons.append("disk free enough for stepped-up drain")

    return {
        "mode": mode,
        "reasons": reasons,
        "vram_mib": vram,
        "ram_pct": ram,
        "k_free_gb": k_free,
        "d_free_gb": d_free,
        "qwythos_8090": qwy,
        "proxy_8091": proxy,
        "comfy_8188": comfy,
        "image_lock_held": img_held,
    }


def limits_for(mode: str) -> Dict[str, int]:
    # FULL THROTTLE (Jeff 2026-07-12) - still pauses on critical resources.
    if mode == "aggressive":
        return {"drain": 1800, "enrich": 60, "train": 40, "reroute": 30, "sleep": 15}
    if mode == "gentle":
        # Drain still hot; cut LLM-side only
        return {"drain": 700, "enrich": 20, "train": 12, "reroute": 15, "sleep": 45}
    if mode == "pause":
        return {"drain": 0, "enrich": 0, "train": 0, "reroute": 0, "sleep": 600}
    # normal - elevated (night-capable)
    return {"drain": 1500, "enrich": 50, "train": 35, "reroute": 28, "sleep": 18}


def apply_force_resource_contract(
    assess_info: Dict[str, Any], forced: str
) -> Dict[str, Any]:
    """Apply --force-mode without violating resource / image_lock safety.

    Rules (2026-07-21 dual-verify harden):
      - image_lock held or VRAM >= VRAM_PAUSE_MIB -> floor to gentle (pause if assess pause)
      - assess already gentle/pause -> force cannot upgrade to aggressive/normal
      - otherwise force may set mode
    """
    base = str(assess_info.get("mode") or "normal")
    reasons = list(assess_info.get("reasons") or [])
    vram = assess_info.get("vram_mib")
    lock_held = bool(assess_info.get("image_lock_held"))
    vram_critical = vram is not None and float(vram or 0) >= VRAM_PAUSE_MIB
    hard_floor = lock_held or vram_critical
    if hard_floor and forced in ("aggressive", "normal"):
        # Keep pause if assess already paused; else gentle land only
        floor = "pause" if base == "pause" and not lock_held else "gentle"
        if lock_held and base == "pause":
            floor = "gentle"  # land may still gentle-copy while gen holds GPU
        assess_info["mode"] = floor
        reasons.append(f"force={forced}_downgraded_to_{floor}_resource_contract")
    elif base in ("gentle", "pause") and forced in ("aggressive", "normal"):
        # Never force past resource assess (high VRAM/RAM already soft)
        assess_info["mode"] = base
        reasons.append(f"force={forced}_blocked_resource_assess_keeps_{base}")
    else:
        assess_info["mode"] = forced
        reasons.append(f"force={forced}")
    assess_info["reasons"] = reasons
    return assess_info


def recheck_hard_yield(assess_info: Dict[str, Any]) -> Dict[str, Any]:
    """Second-look image lock / VRAM critical immediately before tick start."""
    img_held, img_reason = image_gpu_lock_held()
    vram = assess_info.get("vram_mib")
    if vram is None:
        vram = vram_used_mib()
        assess_info["vram_mib"] = vram
    assess_info["image_lock_held"] = img_held
    reasons = list(assess_info.get("reasons") or [])
    mode = str(assess_info.get("mode") or "normal")
    if img_held and mode in ("aggressive", "normal"):
        assess_info["mode"] = "gentle"
        reasons.append(f"pre_tick_yield_image_gpu: {img_reason}")
    elif (
        vram is not None
        and float(vram) >= VRAM_PAUSE_MIB
        and mode in ("aggressive", "normal")
        and not img_held
    ):
        assess_info["mode"] = "pause"
        reasons.append(f"pre_tick_VRAM {vram}MiB critical")
    assess_info["reasons"] = reasons
    return assess_info



def run_tick(limits: Dict[str, int], allow_grunt: bool) -> Dict[str, Any]:
    # Heartbeat only (never clobber full continuous state mid-tick)
    try:
        hb = {
            "at": datetime.now(timezone.utc).isoformat(),
            "phase": "tick_running",
            "limits": limits,
        }
        hb_path = Path(r"D:/HermesData/state") / "silo_tick_heartbeat.json"
        if atomic_write_json is not None:
            atomic_write_json(hb_path, hb, indent=2, min_bytes=20)
        else:
            hb_path.write_text(json.dumps(hb, indent=2), encoding="utf-8")
        # merge phase into existing STATE if present
        if STATE.is_file():
            try:
                cur = json.loads(STATE.read_text(encoding="utf-8"))
                if isinstance(cur, dict):
                    cur["phase"] = "tick_running"
                    cur["heartbeat_at"] = hb["at"]
                    if atomic_write_json is not None:
                        atomic_write_json(STATE, cur, indent=2, min_bytes=20)
                    else:
                        STATE.write_text(json.dumps(cur, indent=2), encoding="utf-8")
            except Exception:
                pass
    except Exception:
        pass
    cmd = [
        _worker_python(),
        str(SCRIPTS / "silo_orchestrator_tick.py"),
        "--drain-limit",
        str(limits["drain"]),
        "--enrich-limit",
        str(limits["enrich"]),
        "--train-limit",
        str(limits["train"]),
        "--reroute-limit",
        str(limits["reroute"]),
    ]
    if not allow_grunt or limits["drain"] == 0:
        cmd.append("--no-grunt")
    if limits["drain"] == 0:
        cmd.append("--no-drain")
    # 2026-07-19: parent must exceed focus_land worker timeout (2700s) + depth tail.
    # Was 2400 with focus_land 1800 -> skip-heavy waves tree-killed mid-copy (exit 124)
    # and wasted drain budget. Keep single-writer: tree-kill still on true hang only.
    code, out = _run(cmd, timeout=4200)
    try:
        # last json block
        j = out[out.rfind("{") : out.rfind("}") + 1]
        parsed = json.loads(j) if j else {}
    except Exception:
        parsed = {"raw": out[-500:]}
    return {"exit": code, "result": parsed}


def write_state(state: Dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    if atomic_write_json is not None:
        atomic_write_json(STATE, state, indent=2, min_bytes=20)
    else:
        STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Silo continuous loop - {state.get('at')}",
        "",
        f"**Cycle:** {state.get('cycle')} | **mode:** `{state.get('assess', {}).get('mode')}`",
        f"**Sleep next:** {state.get('sleep_s')}s",
        f"**VRAM:** {state.get('assess', {}).get('vram_mib')} MiB | **RAM:** {state.get('assess', {}).get('ram_pct')}%",
        f"**Qwythos:** {state.get('assess', {}).get('qwythos_8090')} | **Comfy:** {state.get('assess', {}).get('comfy_8188')}",
        f"**Last tick:** {json.dumps(state.get('last_tick', {}), default=str)[:400]}",
        "",
        "Stop: create `D:\\\\HermesData\\\\state\\\\silo_continuous.STOP`",
        "[[Operations/Silo-Continuous-Resource-Aware-Loop-CANONICAL-2026-07-11]]",
    ]
    body = "\n".join(lines)
    if atomic_write_text is not None:
        atomic_write_text(LOG, body, min_bytes=20)
    else:
        LOG.write_text(body, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="Single assess+tick then exit")
    ap.add_argument(
        "--max-cycles",
        type=int,
        default=0,
        help="0=forever; else stop after N cycles",
    )
    ap.add_argument("--force-mode", choices=["aggressive", "normal", "gentle", "pause"])
    args = ap.parse_args()

    if not acquire_singleton():
        return 2
    try:
        return _main_loop(args)
    finally:
        release_singleton()


def _main_loop(args) -> int:
    cycle = 0
    while True:
        if STOP.is_file():
            print(json.dumps({"stopped": True, "reason": "STOP file present"}))
            return 0
        cycle += 1
        assess_info = assess()
        if args.force_mode:
            # force-mode resource contract (2026-07-21 rock-solid):
            # 1) NEVER override image_lock yield or VRAM>=critical pause
            # 2) NEVER upgrade past assess gentle/pause (high VRAM/RAM already chose soft)
            # Was stuck aggressive at ~11.8GB + Forge when force ignored assess.
            forced = args.force_mode
            assess_info = apply_force_resource_contract(assess_info, forced)
        # Re-check lock immediately before tick (sleep gap / mid-cycle gen start)
        assess_info = recheck_hard_yield(assess_info)
        mode = assess_info["mode"]
        limits = limits_for(mode)
        allow_grunt = bool(
            assess_info.get("qwythos_8090")
            and assess_info.get("proxy_8091")
            and mode in ("aggressive", "normal")
        )
        # gentle: still drain, no grunt
        if mode == "gentle":
            allow_grunt = False

        last_tick: Dict[str, Any] = {"skipped": True}
        if mode != "pause" and limits["drain"] > 0:
            last_tick = run_tick(limits, allow_grunt=allow_grunt)
        elif mode != "pause":
            # enrich-only possible
            last_tick = run_tick(limits, allow_grunt=False)

        # Adaptive sleep: short after long ticks (already spent wall clock cooking)
        sleep_s = int(limits["sleep"])
        try:
            elapsed = float((last_tick.get("result") or {}).get("elapsed_s") or 0)
            if elapsed >= 900:
                sleep_s = 5  # tick already ~15m+; minimal pause
            elif elapsed >= 400:
                sleep_s = min(sleep_s, 10)
        except Exception:
            pass
        state = {
            "at": datetime.now(timezone.utc).isoformat(),
            "cycle": cycle,
            "assess": assess_info,
            "limits": limits,
            "allow_grunt": allow_grunt,
            "last_tick": last_tick,
            "sleep_s": sleep_s,
            "phase": "idle",
        }
        write_state(state)
        print(json.dumps(state, indent=2, default=str)[:2500])

        if args.once:
            return 0 if last_tick.get("exit", 0) == 0 or mode == "pause" else 1
        if args.max_cycles and cycle >= args.max_cycles:
            return 0
        time.sleep(sleep_s)


if __name__ == "__main__":
    raise SystemExit(main())
