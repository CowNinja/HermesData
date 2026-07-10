#!/usr/bin/env python3
"""Local health report for Phronesis Full Stack dashboard tile + travel ops."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\HermesData")
CORE = ROOT / "scripts" / "phronesis-core.json"
REPORT = ROOT / "logs" / "phronesis-fullstack-health.json"
TILE_LIVE = Path(r"D:\PhronesisVault\Dashboard\Tiles\phronesis-fullstack-live.json")
BRIDGE_STATE = ROOT / "state" / "grok-direct-bridge.json"
BRIDGE_LOCK = ROOT / "state" / "grok-direct-bridge.lock"
INBOX_FILE = ROOT / "state" / "grok-inbox.json"
HEARTBEAT_STATE = ROOT / "state" / "grok-direct-heartbeat.json"
COMFY_METRICS = ROOT / "state" / "comfy-pipeline-metrics.json"
RP_BOTTLENECK = ROOT / "logs" / "rp-bottleneck-report.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _probe(url: str, timeout: int = 5) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PhronesisFullStackHealth/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(800).decode("utf-8", errors="replace")
            return {"ok": resp.status == 200, "status": resp.status, "snippet": body[:120]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        return os.path.exists(f"/proc/{pid}")
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    alive = bool(handle)
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
    return alive


def _bridge_health() -> dict:
    pid = 0
    if BRIDGE_LOCK.is_file():
        try:
            pid = int(BRIDGE_LOCK.read_text(encoding="utf-8").strip())
        except Exception:
            pid = 0
    state = {}
    if BRIDGE_STATE.is_file():
        try:
            state = json.loads(BRIDGE_STATE.read_text(encoding="utf-8-sig"))
        except Exception:
            state = {}
    last_reply = str(state.get("last_reply_at") or "")
    age_min = None
    if last_reply:
        try:
            dt = datetime.strptime(last_reply, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            age_min = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
        except Exception:
            pass
    alive = _pid_alive(pid)
    return {
        "ok": alive,
        "pid": pid,
        "last_reply_at": last_reply,
        "last_reply_age_min": age_min,
        "history_turns": len(state.get("history") or []),
    }


def _inbox_pending() -> int:
    if not INBOX_FILE.is_file():
        return 0
    try:
        inbox = json.loads(INBOX_FILE.read_text(encoding="utf-8-sig"))
        return sum(1 for i in inbox.get("items") or [] if i.get("status") == "pending")
    except Exception:
        return 0


def _fifo_queue() -> dict:
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8091/v1/queue",
            headers={"User-Agent": "PhronesisFullStackHealth/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        lanes = data.get("fifo_lanes") or {}
        waiting = int(data.get("waiting_count") or 0)
        active = data.get("active")
        stuck = False
        if active and active.get("run_so_far_sec"):
            stuck = float(active["run_so_far_sec"]) >= 600
        admission = data.get("admission") or {}
        priority_counts = data.get("priority_counts") or {}
        return {
            "ok": True,
            "waiting": waiting,
            "roleplay_waiting": int((lanes.get("roleplay") or {}).get("count") or 0),
            "normal_waiting": int((lanes.get("normal") or {}).get("count") or 0),
            "interactive_waiting": int(
                admission.get("interactive_waiting") or priority_counts.get("interactive") or 0
            ),
            "background_waiting": int(
                admission.get("background_waiting") or priority_counts.get("background") or 0
            ),
            "priority_counts": priority_counts,
            "priority_lanes": data.get("priority_lanes"),
            "active": active,
            "active_priority_class": data.get("active_priority_class"),
            "avg_latency_sec": data.get("avg_latency_sec"),
            "stuck_warn": stuck,
            "total_heals": (data.get("stats") or {}).get("total_heals"),
            "comfy_yield": data.get("comfy_yield"),
            "pressure_tier": (data.get("admission") or {}).get("pressure_tier"),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _rp_comfy_embed(fifo: dict) -> dict:
    metrics = _load_json(COMFY_METRICS)
    bottleneck = _load_json(RP_BOTTLENECK)
    batch = (bottleneck.get("checks") or {}).get("batch_session") or {}
    variation = metrics.get("last_variation_loop") or {}
    comfy_yield = fifo.get("comfy_yield") or {}
    return {
        "rp_batch": {
            "active": bool(metrics.get("batch_active") or batch.get("active")),
            "series": metrics.get("batch_series") or batch.get("series"),
            "delivered": metrics.get("batch_delivered") or batch.get("delivered_count"),
            "total": metrics.get("batch_total") or batch.get("total"),
            "score": bottleneck.get("score"),
            "avg_sec_per_image": variation.get("avg_sec_per_image"),
        },
        "comfy_pipeline": {
            "up": metrics.get("comfy_up"),
            "queue_pending": metrics.get("queue_pending"),
            "bottleneck_score": metrics.get("bottleneck_score"),
        },
        "comfy_yield": comfy_yield,
        "pressure_tier": fifo.get("pressure_tier"),
    }


def build_report() -> dict:
    probes = {
        "llama": _probe("http://127.0.0.1:8090/health"),
        "proxy": _probe("http://127.0.0.1:8091/health"),
        "inference_fifo": _fifo_queue(),
        "gateway": _probe("http://127.0.0.1:8642/health"),
        "cli_dashboard": _probe("http://127.0.0.1:9119/health"),
        "workspace": _probe("http://127.0.0.1:3001/health/detailed"),
    }
    bridge = _bridge_health()
    probes["grok_direct_bridge"] = {"ok": bridge["ok"], "detail": bridge}

    core_ok = sum(
        1 for k, v in probes.items()
        if k not in ("grok_direct_bridge", "inference_fifo") and v.get("ok")
    )
    if probes.get("inference_fifo", {}).get("ok"):
        core_ok += 1
    travel_ok = bridge["ok"]
    score = core_ok * 15 + (15 if travel_ok else 0)
    score = min(100, score)

    if score >= 85 and travel_ok:
        status = "healthy"
    elif score >= 60:
        status = "degraded"
    else:
        status = "critical"

    hb = {}
    if HEARTBEAT_STATE.is_file():
        try:
            hb = json.loads(HEARTBEAT_STATE.read_text(encoding="utf-8-sig"))
        except Exception:
            hb = {}

    fifo_probe = probes.get("inference_fifo") or {}
    return {
        "timestamp": _utc_now(),
        "tile_version": "v1.2",
        "status": status,
        "score": score,
        "probes": probes,
        "rp_comfy": _rp_comfy_embed(fifo_probe if fifo_probe.get("ok") else {}),
        "travel_lane": {
            "bridge": bridge,
            "inbox_pending": _inbox_pending(),
            "last_heartbeat_at": hb.get("last_post_at"),
            "last_xai_ok": hb.get("last_xai_ok"),
        },
        "collab_bus": "docs/agent-coordination/GROK-HERMES-MASTER-PLAN.md",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phronesis full stack health")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    report = build_report()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    TILE_LIVE.parent.mkdir(parents=True, exist_ok=True)
    TILE_LIVE.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.json_only:
        print(json.dumps(report))
    else:
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "score": report["score"],
                    "bridge_ok": report["travel_lane"]["bridge"]["ok"],
                    "inbox_pending": report["travel_lane"]["inbox_pending"],
                    "report": str(REPORT),
                }
            )
        )
    return 0 if report["status"] != "critical" else 1


if __name__ == "__main__":
    raise SystemExit(main())