#!/usr/bin/env python3
"""Lightweight Comfy pipeline monitor — queue depth, delivery latency, JSON metrics."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
if str(OPS) not in sys.path:
    sys.path.insert(0, str(OPS))

from comfy_queue_client import comfy_up, queue_status, write_metrics  # noqa: E402

STATE = ROOT / "state"
LOGS = ROOT / "logs"
METRICS_FILE = STATE / "comfy-pipeline-metrics.json"
REPORT = LOGS / "comfy-pipeline-watch.log"
BOTTLENECK = LOGS / "rp-bottleneck-report.json"
DAEMON_STATE = STATE / "comfy-delivery-daemon.json"
BATCH_SESSION = STATE / "comfy-batch-session.json"
COMFY_OUTPUT = Path(r"D:\ComfyUI\output")


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _latest_png() -> dict:
    best = None
    best_mtime = 0.0
    for path in COMFY_OUTPUT.glob("standard__*.png"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > best_mtime:
            best_mtime = mtime
            best = path
    if not best:
        return {}
    return {
        "name": best.name,
        "mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(best_mtime)),
        "age_sec": round(time.time() - best_mtime, 1),
        "bytes": best.stat().st_size,
    }


def _delivery_latency() -> dict:
    daemon = _read_json(DAEMON_STATE)
    posted = _read_json(STATE / "comfy-discord-posted.json")
    last = str(daemon.get("last_name") or "")
    entry = (posted.get("names") or {}).get(last) if last else None
    return {
        "last_delivered_png": last,
        "last_discord_id": (entry or {}).get("discord_id") if entry else None,
        "last_post_at": (entry or {}).get("at") if entry else None,
    }


def snapshot() -> dict:
    q = queue_status()
    running = len((q.get("queue_running") or [])) if isinstance(q, dict) else 0
    pending = len((q.get("queue_pending") or [])) if isinstance(q, dict) else 0
    bottleneck = _read_json(BOTTLENECK)
    batch = _read_json(BATCH_SESSION)
    prior = _read_json(METRICS_FILE)
    payload = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "comfy_up": comfy_up(),
        "queue_running": running,
        "queue_pending": pending,
        "bottleneck_score": bottleneck.get("score"),
        "batch_active": bool(batch.get("active")),
        "batch_series": batch.get("series"),
        "batch_delivered": batch.get("delivered_count"),
        "batch_total": batch.get("total"),
        "latest_png": _latest_png(),
        "delivery": _delivery_latency(),
        "last_variation_loop": (prior.get("last_variation_loop") or {}),
    }
    write_metrics(payload)
    return payload


def _log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    if args.once:
        payload = snapshot()
        if args.json_only:
            print(json.dumps(payload))
        else:
            _log(
                f"score={payload.get('bottleneck_score')} queue={payload.get('queue_running')}/{payload.get('queue_pending')} "
                f"batch={payload.get('batch_delivered')}/{payload.get('batch_total')} latest={payload.get('latest_png', {}).get('name')}"
            )
        return 0

    while True:
        try:
            payload = snapshot()
            _log(
                f"queue={payload.get('queue_running')}/{payload.get('queue_pending')} "
                f"latest={payload.get('latest_png', {}).get('name')}"
            )
        except Exception as exc:
            _log(f"error: {exc}")
        time.sleep(max(10, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())