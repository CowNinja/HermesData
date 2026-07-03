#!/usr/bin/env python3
"""
nanodb.py -- Lightweight JSON-file-backed persistence for Sovereign Model Router.

Stores:
 - Model stats: latency history, VRAM usage, quant type, selection count
 - Model aliases: logical name - GGUF filename mapping
 - Auto-pick heuristics: which model won for which task_type
 - Benchmark snapshots: before/after comparison data

Single-file storage under D:/PhronesisVault/Operations/nanodb/
No external dependencies beyond stdlib.

Usage:
  python nanodb.py --init
  python nanodb.py --record-model MODEL KEY=VALUE
  python nanodb.py --get-model MODEL
  python nanodb.py --list-models
  python nanodb.py --record-dispatch TASK_TYPE MODEL LATENCY_MS TPS
  python nanodb.py --auto-pick TASK_TYPE
  python nanodb.py --benchmark-snapshot LABEL
  python nanodb.py --export
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_DIR = Path(r"D:\PhronesisVault\Operations\nanodb")
MODELS_FILE = DB_DIR / "models.json"
DISPATCHES_FILE = DB_DIR / "dispatches.jsonl"
BENCHMARKS_FILE = DB_DIR / "benchmarks.json"
ALIASES_FILE = DB_DIR / "aliases.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    for f, default in [
        (MODELS_FILE, {}),
        (BENCHMARKS_FILE, {"snapshots": []}),
        (ALIASES_FILE, {}),
    ]:
        if not f.exists():
            f.write_text(json.dumps(default, indent=2), encoding="utf-8")
    if not DISPATCHES_FILE.exists():
        DISPATCHES_FILE.write_text("", encoding="utf-8")
    print(f"nanoDB initialized at {DB_DIR}")
    return 0


def load_models() -> Dict[str, Any]:
    if MODELS_FILE.exists():
        try:
            return json.loads(MODELS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_models(data: Dict[str, Any]):
    DB_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record_model(name: str, **kwargs):
    models = load_models()
    entry = models.setdefault(name, {"name": name, "first_seen": _utc_now()})
    entry["last_updated"] = _utc_now()
    for k, v in kwargs.items():
        if k.startswith("stat_"):
            # Time-series stat: stat_tps, stat_latency_ms, etc.
            stats = entry.setdefault("stats", {})
            stat_history = stats.setdefault(k, [])
            stat_history.append({"ts": _utc_now(), "value": v})
            # Keep last 100 entries per stat
            if len(stat_history) > 100:
                stats[k] = stat_history[-100:]
        elif k == "aliases":
            # List of aliases for this model
            existing = set(entry.get("aliases", []))
            if isinstance(v, list):
                existing.update(v)
            else:
                existing.add(v)
            entry["aliases"] = sorted(existing)
        else:
            entry[k] = v
    models[name] = entry
    save_models(models)
    print(json.dumps(entry, indent=2))
    return 0


def get_model(name: str) -> int:
    models = load_models()
    # Try exact match first, then partial
    if name in models:
        print(json.dumps(models[name], indent=2))
        return 0
    for k, v in models.items():
        if name.lower() in k.lower():
            print(json.dumps(v, indent=2))
            return 0
    print(json.dumps({"error": "not_found", "name": name}))
    return 1


def list_models():
    models = load_models()
    summary = []
    for name, entry in sorted(models.items()):
        summary.append({
            "name": name,
            "quant": entry.get("quantization", "?"),
            "vram_gb": entry.get("vram_estimate_gb", "?"),
            "dispatches": entry.get("dispatch_count", 0),
            "avg_tps": _avg_stat(entry, "stat_tps"),
            "avg_latency_ms": _avg_stat(entry, "stat_latency_ms"),
        })
    print(json.dumps(summary, indent=2))
    return 0


def _avg_stat(entry: dict, stat_key: str) -> Optional[float]:
    stats = entry.get("stats", {})
    history = stats.get(stat_key, [])
    if not history:
        return None
    values = [h["value"] for h in history if isinstance(h.get("value"), (int, float))]
    return round(sum(values) / len(values), 2) if values else None


def record_dispatch(task_type: str, model: str, latency_ms: float, tps: float):
    DB_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": _utc_now(),
        "task_type": task_type,
        "model": model,
        "latency_ms": latency_ms,
        "tps": tps,
    }
    with open(DISPATCHES_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    # Update model stats
    models = load_models()
    entry = models.setdefault(model, {"name": model, "first_seen": _utc_now()})
    entry["dispatch_count"] = entry.get("dispatch_count", 0) + 1
    entry["last_dispatch"] = _utc_now()
    stats = entry.setdefault("stats", {})
    for stat_key, val in [("stat_tps", tps), ("stat_latency_ms", latency_ms)]:
        h = stats.setdefault(stat_key, [])
        h.append({"ts": _utc_now(), "value": val})
        if len(h) > 100:
            stats[stat_key] = h[-100:]
    # Track task_type wins
    task_wins = entry.setdefault("task_wins", {})
    task_wins[task_type] = task_wins.get(task_type, 0) + 1
    entry["last_updated"] = _utc_now()
    models[model] = entry
    save_models(models)
    print(json.dumps(record, indent=2))
    return 0


def auto_pick(task_type: str) -> int:
    """Recommend best model for a task_type based on historical performance."""
    models = load_models()
    if not models:
        print(json.dumps({"error": "no_data", "recommendation": "qwen2-5-7b"}))
        return 1

    scored = []
    for name, entry in models.items():
        task_wins = entry.get("task_wins", {})
        wins = task_wins.get(task_type, 0)
        avg_tps = _avg_stat(entry, "stat_tps") or 0
        avg_lat = _avg_stat(entry, "stat_latency_ms") or 999999
        dispatches = entry.get("dispatch_count", 0)
        # Score: weighted combination of wins, TPS, and latency
        score = wins * 10 + avg_tps * 2 - avg_lat / 100
        scored.append((score, name, {"wins": wins, "avg_tps": avg_tps, "avg_latency_ms": avg_lat}))

    scored.sort(reverse=True)
    if scored:
        best = scored[0]
        result = {
            "task_type": task_type,
            "recommendation": best[1],
            "score": round(best[0], 2),
            "details": best[2],
            "all_scored": [(s[1], round(s[0], 2)) for s in scored[:5]],
        }
    else:
        result = {"error": "no_scored_models", "recommendation": "qwen2-5-7b"}
    print(json.dumps(result, indent=2))
    return 0


def benchmark_snapshot(label: str) -> int:
    """Capture current benchmark results as a labeled snapshot."""
    # Read latest benchmark-results.json
    bench_file = Path(r"D:\PhronesisVault\Operations\logs\benchmark-results.json")
    if not bench_file.exists():
        print(json.dumps({"error": "no_benchmark_results"}))
        return 1

    try:
        bench_data = json.loads(bench_file.read_text(encoding="utf-8"))
    except Exception:
        print(json.dumps({"error": "benchmark_parse_failed"}))
        return 1

    snapshots = load_benchmarks()
    snapshot = {
        "label": label,
        "captured_at": _utc_now(),
        "data": bench_data,
    }
    snapshots.setdefault("snapshots", []).append(snapshot)
    DB_DIR.mkdir(parents=True, exist_ok=True)
    BENCHMARKS_FILE.write_text(json.dumps(snapshots, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "label": label, "snapshots_count": len(snapshots["snapshots"])}, indent=2))
    return 0


def load_benchmarks() -> dict:
    if BENCHMARKS_FILE.exists():
        try:
            return json.loads(BENCHMARKS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"snapshots": []}


def export_all():
    """Export entire nanoDB as a single JSON dump."""
    output = {
        "exported_at": _utc_now(),
        "models": load_models(),
        "benchmarks": load_benchmarks(),
        "aliases": load_aliases(),
        "dispatch_count": 0,
    }
    if DISPATCHES_FILE.exists():
        count = 0
        for line in DISPATCHES_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                count += 1
        output["dispatch_count"] = count
    print(json.dumps(output, indent=2))
    return 0


def load_aliases() -> dict:
    if ALIASES_FILE.exists():
        try:
            return json.loads(ALIASES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def set_alias(alias: str, model: str):
    aliases = load_aliases()
    aliases[alias] = model
    DB_DIR.mkdir(parents=True, exist_ok=True)
    ALIASES_FILE.write_text(json.dumps(aliases, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "alias": alias, "model": model}))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Sovereign nanoDB — model stat persistence")
    parser.add_argument("--init", action="store_true", help="Initialize database files")
    parser.add_argument("--record-model", metavar="MODEL", help="Record/update model metadata")
    parser.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), action="append", help="Key=value pairs with --record-model")
    parser.add_argument("--get-model", metavar="MODEL", help="Get model record")
    parser.add_argument("--list-models", action="store_true", help="List all models with summary stats")
    parser.add_argument("--record-dispatch", nargs=4, metavar=("TASK_TYPE", "MODEL", "LATENCY_MS", "TPS"), help="Record a dispatch event")
    parser.add_argument("--auto-pick", metavar="TASK_TYPE", help="Recommend best model for task_type")
    parser.add_argument("--benchmark-snapshot", metavar="LABEL", help="Save current benchmark results as labeled snapshot")
    parser.add_argument("--set-alias", nargs=2, metavar=("ALIAS", "MODEL"), help="Set model alias")
    parser.add_argument("--export", action="store_true", help="Export entire database")
    args = parser.parse_args()

    if args.init:
        return init_db()
    if args.record_model:
        kwargs = {}
        if args.set:
            for k, v in args.set:
                # Auto-convert numeric values
                try:
                    v = float(v)
                    if v == int(v):
                        v = int(v)
                except ValueError:
                    pass
                kwargs[k] = v
        return record_model(args.record_model, **kwargs)
    if args.get_model:
        return get_model(args.get_model)
    if args.list_models:
        return list_models()
    if args.record_dispatch:
        task, model, lat, tps = args.record_dispatch
        return record_dispatch(task, model, float(lat), float(tps))
    if args.auto_pick:
        return auto_pick(args.auto_pick)
    if args.benchmark_snapshot:
        return benchmark_snapshot(args.benchmark_snapshot)
    if args.set_alias:
        return set_alias(args.set_alias[0], args.set_alias[1])
    if args.export:
        return export_all()

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
