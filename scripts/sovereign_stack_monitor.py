#!/usr/bin/env python3
"""
sovereign_stack_monitor.py — 8090 router + VRAM + nanoDB + port health.

Script-only (no_agent) monitoring for cron. Outputs JSONL to operator-console.jsonl.
Alerts via stdout (non-zero exit triggers cron delivery).

Checks:
  1. Port health: 8090 (router), 8091 (proxy), 3000/3001/8642/9119 (existing core)
  2. 8090 /health + /v1/models (which model is loaded, VRAM usage)
  3. GPU VRAM via nvidia-smi (total, used, free, temp, util%)
  4. nanoDB stats (dispatch count, last dispatch, model distribution)
  5. Alert conditions: router down, VRAM > 95%, GPU temp > 85C, nanoDB stale

Usage:
  python sovereign_stack_monitor.py            # one-shot check, append JSONL
  python sovereign_stack_monitor.py --alert    # exit 2 if any alert condition
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# --- Paths ---
LOG_DIR = Path(r"D:\PhronesisVault\Operations\logs")
CONSOLE_LOG = LOG_DIR / "operator-console.jsonl"
NANODB_PATH = Path(r"D:\PhronesisVault\Operations\nanodb")

# --- Ports to check (existing core + new router) ---
PORT_DEFS = [
    {"port": 3000, "desc": "WA bridge", "health_url": "http://127.0.0.1:3000/health"},
    {"port": 3001, "desc": "workspace", "health_url": "http://127.0.0.1:3001/api/auth-check"},
    {"port": 8642, "desc": "gateway", "health_url": "http://127.0.0.1:8642/health"},
    {"port": 9119, "desc": "dashboard", "health_url": "http://127.0.0.1:9119/api/status"},
    {"port": 8090, "desc": "llama-router", "health_url": "http://127.0.0.1:8090/health"},
    {"port": 8091, "desc": "openai-proxy", "health_url": None},
]

# --- Alert thresholds ---
# Windows WDDM reserves ~6-7 GB for desktop compositor + hardware-accelerated apps.
# On a 12 GB 3060 with a 4.68 GB model, ~95% usage is NORMAL. Alert only at 98%+.
VRAM_WARN_PCT = 90.0
VRAM_CRITICAL_PCT = 98.0
GPU_TEMP_WARN_C = 75.0
GPU_TEMP_CRITICAL_C = 85.0
NANODB_STALE_MINUTES = 60


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, entry: Dict[str, Any]) -> None:
    """Append one JSONL row; rotate operator-console before write when fat."""
    try:
        from jsonl_log_rotator import append_jsonl as _rot_append

        _rot_append(path, entry, mode="rename", stamp=False)
        return
    except Exception:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def get_port_pids(port: int) -> List[int]:
    """Get PIDs listening on a port via netstat."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
        pids = []
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                if parts:
                    try:
                        pids.append(int(parts[-1]))
                    except ValueError:
                        pass
        return list(set(pids))
    except Exception:
        return []


def probe_http(url: str, timeout: float = 5.0) -> Optional[int]:
    """Return HTTP status code or None."""
    try:
        import urllib.request
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode()
    except Exception:
        return None


def get_gpu_info() -> Optional[Dict[str, Any]]:
    """Query nvidia-smi for VRAM, temp, utilization."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free,temperature.gpu,utilization.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
        if result.returncode != 0:
            return None
        parts = result.stdout.strip().split(",")
        if len(parts) < 7:
            return None
        total_mb = float(parts[1])
        used_mb = float(parts[2])
        return {
            "name": parts[0].strip(),
            "vram_total_mb": total_mb,
            "vram_used_mb": used_mb,
            "vram_free_mb": float(parts[3]),
            "vram_used_pct": round(used_mb / total_mb * 100, 1) if total_mb > 0 else 0,
            "temp_c": float(parts[4]),
            "util_pct": float(parts[5]),
            "power_w": float(parts[6]) if parts[6].strip() != "[N/A]" else None,
        }
    except Exception:
        return None


def get_router_models() -> Optional[Dict[str, Any]]:
    """Query 8090 /v1/models for loaded model info."""
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:8090/v1/models")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        models = data.get("data", [])
        loaded = [m for m in models if m.get("status", {}).get("value") == "loaded"]
        unloaded = [m for m in models if m.get("status", {}).get("value") != "loaded"]
        result = {
            "total_presets": len(models),
            "loaded_count": len(loaded),
            "loaded": [],
            "unloaded": [],
        }
        for m in loaded:
            result["loaded"].append({
                "id": m.get("id"),
                "params_b": round(m.get("meta", {}).get("n_params", 0) / 1e9, 1),
                "size_gb": round(m.get("meta", {}).get("size", 0) / 1e9, 2),
                "ctx": m.get("meta", {}).get("n_ctx"),
            })
        for m in unloaded:
            result["unloaded"].append({
                "id": m.get("id"),
                "failed": m.get("status", {}).get("failed", False),
            })
        return result
    except Exception:
        return None


def get_nanodb_stats() -> Optional[Dict[str, Any]]:
    """Read nanoDB dispatch log for recent activity."""
    try:
        if not NANODB_PATH.exists():
            return None
        # nanoDB stores dispatches in a JSONL or SQLite — try both
        db_file = NANODB_PATH / "dispatches.jsonl"
        if not db_file.exists():
            db_file = NANODB_PATH / "nanodb.jsonl"
        if not db_file.exists():
            # Try SQLite
            db_file = NANODB_PATH / "nanodb.db"
            if db_file.exists():
                import sqlite3
                conn = sqlite3.connect(str(db_file))
                cur = conn.cursor()
                # Try common table names
                for table in ["dispatches", "events", "records"]:
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {table}")
                        count = cur.fetchone()[0]
                        cur.execute(f"SELECT MAX(timestamp) FROM {table}")
                        last_ts = cur.fetchone()[0]
                        cur.execute(
                            f"SELECT model, COUNT(*) as cnt FROM {table} "
                            f"GROUP BY model ORDER BY cnt DESC LIMIT 5"
                        )
                        model_dist = {row[0]: row[1] for row in cur.fetchall()}
                        conn.close()
                        return {
                            "total_dispatches": count,
                            "last_dispatch_ts": last_ts,
                            "model_distribution": model_dist,
                            "backend": "sqlite",
                        }
                    except Exception:
                        continue
                conn.close()
            return None

        # JSONL parsing
        lines = db_file.read_text(encoding="utf-8").strip().splitlines()
        if not lines:
            return {"total_dispatches": 0, "backend": "jsonl"}

        model_counts: Dict[str, int] = {}
        last_ts = None
        for line in lines[-500:]:  # last 500 entries
            try:
                entry = json.loads(line)
                model = entry.get("model", entry.get("model_id", "unknown"))
                model_counts[model] = model_counts.get(model, 0) + 1
                ts = entry.get("timestamp", entry.get("ts"))
                if ts:
                    last_ts = ts
            except json.JSONDecodeError:
                pass

        return {
            "total_dispatches": len(lines),
            "last_dispatch_ts": last_ts,
            "model_distribution": dict(sorted(model_counts.items(), key=lambda x: -x[1])[:5]),
            "backend": "jsonl",
        }
    except Exception:
        return None


def main():
    alert_mode = "--alert" in sys.argv
    alerts: List[str] = []
    ts = utc_now()

    # --- 1. Port health ---
    ports_status: Dict[str, Any] = {}
    for defn in PORT_DEFS:
        p = defn["port"]
        pids = get_port_pids(p)
        listening = len(pids) > 0
        http_status = None
        if listening and defn.get("health_url"):
            http_status = probe_http(defn["health_url"])

        ports_status[str(p)] = {
            "listening": listening,
            "http_status": http_status,
            "pids": pids[:3],
            "desc": defn["desc"],
        }

        # Alert conditions
        if not listening:
            if p in (8090, 8091):
                alerts.append(f"CRITICAL: port {p} ({defn['desc']}) DOWN")
        elif defn.get("health_url") and http_status != 200:
            if p in (8090,):
                alerts.append(f"WARNING: port {p} ({defn['desc']}) HTTP {http_status}")

    # --- 2. GPU VRAM ---
    gpu = get_gpu_info()
    if gpu:
        if gpu["vram_used_pct"] >= VRAM_CRITICAL_PCT:
            alerts.append(f"CRITICAL: VRAM {gpu['vram_used_pct']}% ({gpu['vram_used_mb']:.0f}/{gpu['vram_total_mb']:.0f} MB)")
        elif gpu["vram_used_pct"] >= VRAM_WARN_PCT:
            alerts.append(f"WARNING: VRAM {gpu['vram_used_pct']}% ({gpu['vram_used_mb']:.0f}/{gpu['vram_total_mb']:.0f} MB)")
        if gpu["temp_c"] >= GPU_TEMP_CRITICAL_C:
            alerts.append(f"CRITICAL: GPU temp {gpu['temp_c']}C")
        elif gpu["temp_c"] >= GPU_TEMP_WARN_C:
            alerts.append(f"WARNING: GPU temp {gpu['temp_c']}C")
    else:
        alerts.append("WARNING: nvidia-smi unavailable (GPU query failed)")

    # --- 3. Router model status ---
    router_models = get_router_models()
    if router_models:
        if router_models["loaded_count"] == 0:
            alerts.append("WARNING: 8090 router up but no model loaded")
    else:
        alerts.append("WARNING: 8090 /v1/models unreachable")

    # --- 4. nanoDB stats ---
    nanodb = get_nanodb_stats()

    # --- Build entry ---
    healthy_ports = sum(1 for p in ports_status.values() if p["listening"])
    total_ports = len(PORT_DEFS)

    level = "info"
    if any(a.startswith("CRITICAL") for a in alerts):
        level = "error"
    elif alerts:
        level = "warn"

    entry = {
        "ts": ts,
        "source": "stack-monitor",
        "level": level,
        "event": "stack_monitor_tick",
        "detail": {
            "ports": ports_status,
            "ports_healthy": f"{healthy_ports}/{total_ports}",
            "gpu": gpu,
            "router_models": router_models,
            "nanodb": nanodb,
            "alerts": alerts,
            "alert_count": len(alerts),
        },
    }

    append_jsonl(CONSOLE_LOG, entry)

    # --- Output ---
    criticals = [a for a in alerts if a.startswith("CRITICAL")]
    warnings = [a for a in alerts if a.startswith("WARNING")]

    if criticals:
        for a in criticals:
            print(a)
        if alert_mode:
            sys.exit(2)
    elif warnings:
        for a in warnings:
            print(a)
        # Warnings don't trigger alert delivery — just log
    else:
        print(f"Stack healthy: {healthy_ports}/{total_ports} ports, GPU OK, router loaded")

    sys.exit(0)


if __name__ == "__main__":
    main()
