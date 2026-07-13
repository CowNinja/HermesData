#!/usr/bin/env python3
"""Resource-aware continuous silo builder.

Goal: constant G→K cook + light enrich WITHOUT crashing the box.
Monitors VRAM/RAM/disk; backs off when Comfy or system is hot.

Modes (auto):
  aggressive — free GPU/RAM, larger drain
  normal     — default
  gentle     — Comfy/VRAM high: scripts only, smaller batches, longer sleep
  pause      — critical resources; sleep only

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
            import subprocess
            r = subprocess.run(
                ["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine"],
                capture_output=True, text=True, timeout=15,
            )
            if "silo_continuous_loop" in ((r.stdout or "") + (r.stderr or "")):
                return False
        except Exception:
            pass
        try:
            LOCK.unlink(missing_ok=True)
        except Exception:
            pass
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(
        str(__import__("os").getpid()) + " " + datetime.now(timezone.utc).isoformat() + chr(10),
        encoding="utf-8",
    )
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
VRAM_GENTLE_MIB = 9000      # above → no local LLM grunt (dual-stack / Comfy hot)
VRAM_SILO_PRIMARY_GENTLE_MIB = 11000  # Qwythos-only baseline ~9.3GB is expected
VRAM_PAUSE_MIB = 11800      # above → pause cook
RAM_GENTLE_PCT = 85
RAM_PAUSE_PCT = 93
DISK_K_MIN_GB = 50
DISK_D_MIN_GB = 30


def _run(cmd, timeout=120) -> Tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, ((p.stdout or "") + (p.stderr or ""))[-2000:]
    except Exception as e:
        return 1, str(e)


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


def assess() -> Dict[str, Any]:
    vram = vram_used_mib()
    ram = ram_used_pct()
    k_free = disk_free_gb("K:\\")
    d_free = disk_free_gb("D:\\")
    qwy = port_up(8090)
    proxy = port_up(8091)
    comfy = port_up(8188)

    mode = "normal"
    reasons = []
    if k_free is not None and k_free < DISK_K_MIN_GB:
        mode = "pause"
        reasons.append(f"K free {k_free:.0f}GB < {DISK_K_MIN_GB}")
    if d_free is not None and d_free < DISK_D_MIN_GB:
        mode = "pause"
        reasons.append(f"D free {d_free:.0f}GB < {DISK_D_MIN_GB}")
    if vram is not None and vram >= VRAM_PAUSE_MIB:
        mode = "pause"
        reasons.append(f"VRAM {vram}MiB critical")
    elif ram is not None and ram >= RAM_PAUSE_PCT:
        mode = "pause"
        reasons.append(f"RAM {ram}% critical")
    # Disk copy does NOT need GPU. Only pause when system is critically loaded.
    # "gentle" = reduce enrich/train + disable Qwythos grunt, NOT starve drain.
    elif ram is not None and ram >= RAM_GENTLE_PCT:
        mode = "gentle"
        reasons.append(f"RAM {ram}% high")
    elif (
            silo_primary_active()
            and qwy
            and not comfy
            and vram is not None
            and vram < VRAM_PAUSE_MIB
        ):
            # Jeff overnight high-gear 2026-07-13: silo_primary still aggressive land
            mode = "aggressive"
            reasons.append(
                f"silo_primary overnight high-gear — VRAM {vram}MiB Qwythos-only, drain max"
            )
    elif vram is not None and vram >= (
        VRAM_SILO_PRIMARY_GENTLE_MIB if silo_primary_active() else VRAM_GENTLE_MIB
    ):
        mode = "gentle"
        reasons.append(f"VRAM {vram}MiB high — drain full, no LLM grunt")
    else:
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
    }


def limits_for(mode: str) -> Dict[str, int]:
    # FULL THROTTLE (Jeff 2026-07-12) — still pauses on critical resources.
    if mode == "aggressive":
        return {"drain": 1800, "enrich": 60, "train": 40, "reroute": 30, "sleep": 15}
    if mode == "gentle":
        # Drain still hot; cut LLM-side only
        return {"drain": 700, "enrich": 20, "train": 12, "reroute": 15, "sleep": 45}
    if mode == "pause":
        return {"drain": 0, "enrich": 0, "train": 0, "reroute": 0, "sleep": 600}
    # normal — elevated (night-capable)
        return {"drain": 1500, "enrich": 50, "train": 35, "reroute": 28, "sleep": 18}



def run_tick(limits: Dict[str, int], allow_grunt: bool) -> Dict[str, Any]:
    # Heartbeat only (never clobber full continuous state mid-tick)
    try:
        hb = {
            "at": datetime.now(timezone.utc).isoformat(),
            "phase": "tick_running",
            "limits": limits,
        }
        (Path(r"D:/HermesData/state") / "silo_tick_heartbeat.json").write_text(
            json.dumps(hb, indent=2), encoding="utf-8"
        )
        # merge phase into existing STATE if present
        if STATE.is_file():
            try:
                cur = json.loads(STATE.read_text(encoding="utf-8"))
                if isinstance(cur, dict):
                    cur["phase"] = "tick_running"
                    cur["heartbeat_at"] = hb["at"]
                    STATE.write_text(json.dumps(cur, indent=2), encoding="utf-8")
            except Exception:
                pass
    except Exception:
        pass
    cmd = [
        sys.executable,
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
    code, out = _run(cmd, timeout=2400)
    try:
        # last json block
        j = out[out.rfind("{") : out.rfind("}") + 1]
        parsed = json.loads(j) if j else {}
    except Exception:
        parsed = {"raw": out[-500:]}
    return {"exit": code, "result": parsed}


def write_state(state: Dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Silo continuous loop — {state.get('at')}",
        "",
        f"**Cycle:** {state.get('cycle')} · **mode:** `{state.get('assess', {}).get('mode')}`",
        f"**Sleep next:** {state.get('sleep_s')}s",
        f"**VRAM:** {state.get('assess', {}).get('vram_mib')} MiB · **RAM:** {state.get('assess', {}).get('ram_pct')}%",
        f"**Qwythos:** {state.get('assess', {}).get('qwythos_8090')} · **Comfy:** {state.get('assess', {}).get('comfy_8188')}",
        f"**Last tick:** {json.dumps(state.get('last_tick', {}), default=str)[:400]}",
        "",
        "Stop: create `D:\\\\HermesData\\\\state\\\\silo_continuous.STOP`",
        "[[Operations/Silo-Continuous-Resource-Aware-Loop-CANONICAL-2026-07-11]]",
    ]
    LOG.write_text("\n".join(lines), encoding="utf-8")


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
            assess_info["mode"] = args.force_mode
            assess_info["reasons"] = list(assess_info.get("reasons") or []) + [
                f"force={args.force_mode}"
            ]
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
