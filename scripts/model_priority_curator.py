#!/usr/bin/env python3
"""
model_priority_curator.py -- Holistic model priority board for sovereign stack.

Unifies local GPU inventory, benchmark scores, free cloud fleet, and paid fallbacks
into one ranked priority state for the dashboard panel. Does NOT auto-promote while
model_rotation_locked is true -- ranks and recommends only.

Usage:
  python model_priority_curator.py --tick          # lightweight refresh (cron)
  python model_priority_curator.py --stdout        # print JSON
  python model_priority_curator.py --refresh-cloud # include fleet health cycle
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERMES_ROOT = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")
PHM = Path(r"D:\PhronesisModels")
CORE_PATH = HERMES_ROOT / "scripts" / "phronesis-core.json"
CONFIG_PATH = HERMES_ROOT / "config.yaml"
FLEET_REGISTRY = HERMES_ROOT / "config" / "fleet_registry.yaml"
INVENTORY_PATH = PHM / "model_inventory.json"
LIFECYCLE_PATH = PHM / "lifecycle_manifest.json"
BENCHMARK_DIR = VAULT / "Operations" / "benchmark-results"
CURATOR_REPORT = VAULT / "Operations" / "logs" / "fleet-curator-report.json"
HEALTH_STATE = VAULT / "Operations" / "logs" / "fleet-health-state.json"
PROCUREMENT_STATE = VAULT / "Operations" / "logs" / "fleet-procurement-state.json"
PROCUREMENT_REPORT = VAULT / "Operations" / "logs" / "fleet-procurement-report.json"
STATE_OUT = VAULT / "Operations" / "model-priority-state.json"
LOG_PATH = VAULT / "Operations" / "logs" / "model-priority-curator.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _log(event: Dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": _utc_now(), **event}) + "\n")


def _collect_benchmark_scores() -> Dict[str, Dict[str, Any]]:
    """Filename stem -> best known benchmark metrics."""
    scores: Dict[str, Dict[str, Any]] = {}
    if not BENCHMARK_DIR.is_dir():
        return scores
    for path in BENCHMARK_DIR.glob("*.json"):
        data = _load_json(path)
        if not data:
            continue
        model_key = str(data.get("model") or data.get("candidate") or path.stem).lower()
        tests = data.get("tests") or []
        composite = data.get("composite") or data.get("composite_score")
        tps = data.get("speed_tps") or data.get("tokens_per_sec") or data.get("tps")
        pass_rate = data.get("pass_rate") or data.get("pass_pct")
        if tests and pass_rate is None:
            passed = sum(1 for t in tests if t.get("pass"))
            pass_rate = round(100.0 * passed / len(tests), 1) if tests else None
        if composite is None and pass_rate is not None:
            composite = round(float(pass_rate) * 0.85 + min(15.0, float(tps or 0)), 1)
        scores[model_key] = {
            "composite": float(composite) if composite is not None else None,
            "tps": float(tps) if tps is not None else None,
            "pass_rate": float(pass_rate) if pass_rate is not None else None,
            "source": str(path.name),
            "tested_at": data.get("timestamp") or data.get("tested_at"),
            "test_count": len(tests) if tests else None,
        }
    def _norm(s: str) -> str:
        return s.lower().replace(".gguf", "").replace("_", "-").replace(" ", "-")

    by_file: Dict[str, Dict[str, Any]] = {}
    inv = _load_json(INVENTORY_PATH)
    for fname in (inv.get("gguf_truth") or {}):
        stem = _norm(fname)
        best: Optional[Tuple[float, Dict[str, Any]]] = None
        for key, meta in scores.items():
            nk = _norm(key)
            if stem == nk or stem in nk or nk in stem:
                conf = 1.0
            else:
                stem_tokens = {t for t in stem.split("-") if len(t) >= 4}
                key_tokens = {t for t in nk.split("-") if len(t) >= 4}
                overlap = len(stem_tokens & key_tokens)
                if overlap < 2:
                    continue
                conf = overlap / max(len(stem_tokens), 1)
            comp = float(meta.get("composite") or 0)
            rank = conf * 100 + comp
            if best is None or rank > best[0]:
                best = (rank, meta)
        if best and best[0] >= 50:
            by_file[fname] = best[1]
    return by_file


def _score_local_model(
    fname: str,
    meta: Dict[str, Any],
    *,
    active: bool,
    locked: bool,
    bench: Optional[Dict[str, Any]],
) -> float:
    base = 50.0
    if active:
        base += 40.0
    lifecycle = str(meta.get("lifecycle") or meta.get("state") or "candidate")
    if lifecycle == "current":
        base += 15.0
    if meta.get("permanently_disabled"):
        base -= 100.0
    size_gb = float(meta.get("size_gb") or meta.get("size_gib") or 0)
    if 0 < size_gb <= 8:
        base += 5.0
    elif size_gb > 11:
        base -= 5.0
    if bench:
        comp = bench.get("composite")
        if comp is not None:
            base += min(30.0, float(comp) / 3.0)
        tps = bench.get("tps")
        if tps is not None:
            base += min(10.0, float(tps) / 10.0)
    if locked and not active:
        base -= 25.0
    return round(base, 1)


def _rank_local_models(core: Dict[str, Any]) -> List[Dict[str, Any]]:
    inv = _load_json(INVENTORY_PATH)
    lifecycle = _load_json(LIFECYCLE_PATH)
    bench_map = _collect_benchmark_scores()
    active_path = str(core.get("model") or "")
    active_name = Path(active_path).name if active_path else ""
    locked = bool(core.get("model_rotation_locked", True))
    label = str(core.get("model_label") or "")

    rows: List[Dict[str, Any]] = []
    gguf = inv.get("gguf_truth") or {}
    if not gguf:
        # Fallback from core future_models + active
        for entry in core.get("future_models") or []:
            if not isinstance(entry, dict):
                continue
            path = str(entry.get("path") or "")
            fname = Path(path).name
            is_active = bool(entry.get("active"))
            rows.append(
                {
                    "id": fname,
                    "name": str(entry.get("label") or fname),
                    "tier": "gpu_local",
                    "provider": "local_gpu",
                    "status": "active" if is_active else ("disabled" if entry.get("permanently_disabled") else "standby"),
                    "score": _score_local_model(fname, entry, active=is_active, locked=locked, bench=bench_map.get(fname)),
                    "ctx_k": (int(entry.get("ctx_size") or 0) // 1000) or None,
                    "detail": entry.get("disabled_reason") or ("Loaded on :8090" if is_active else "On disk"),
                    "benchmark": bench_map.get(fname),
                    "promotable": not locked and not entry.get("permanently_disabled") and not is_active,
                }
            )
        return sorted(rows, key=lambda r: r["score"], reverse=True)

    for fname, meta in gguf.items():
        if not isinstance(meta, dict):
            continue
        path = str(meta.get("path") or "")
        is_active = fname == active_name or label.lower() in fname.lower()
        lc = (lifecycle.get("models") or {}).get(fname) or {}
        state = str(lc.get("state") or meta.get("lifecycle") or "candidate")
        disabled = bool(meta.get("permanently_disabled") or lc.get("permanently_disabled"))
        rows.append(
            {
                "id": fname,
                "name": meta.get("short_name") or fname.replace(".gguf", "")[:48],
                "tier": "gpu_local",
                "provider": "local_gpu",
                "status": "active" if is_active else ("disabled" if disabled else state),
                "score": _score_local_model(fname, {**meta, "lifecycle": state, "permanently_disabled": disabled}, active=is_active, locked=locked, bench=bench_map.get(fname)),
                "ctx_k": meta.get("ctx_k") or (int(meta.get("ctx_size") or 0) // 1000) or None,
                "size_gb": meta.get("size_gb"),
                "detail": "Loaded on :8090" if is_active else f"{state} on disk",
                "benchmark": bench_map.get(fname),
                "promotable": not locked and not disabled and not is_active,
            }
        )
    return sorted(rows, key=lambda r: r["score"], reverse=True)


def _provider_health(pid: str) -> Dict[str, Any]:
    health = _load_json(HEALTH_STATE)
    return (health.get("providers") or {}).get(pid) or {}


def _procurement_benchmarks() -> Dict[str, Dict[str, Any]]:
    """Provider id -> procurement benchmark (TTFT, compliance, pass) when available."""
    out: Dict[str, Dict[str, Any]] = {}
    for path in (PROCUREMENT_STATE, PROCUREMENT_REPORT):
        data = _load_json(path)
        for entry in (data.get("providers") or data.get("benchmarked") or []):
            if not isinstance(entry, dict):
                continue
            pid = str(entry.get("id") or entry.get("provider_id") or "")
            if not pid:
                continue
            bench = entry.get("benchmark") or entry.get("bench")
            if isinstance(bench, dict) and bench:
                out[pid] = bench
            elif entry.get("ttft_sec") is not None or entry.get("pass") is not None:
                out[pid] = {
                    "ttft_sec": entry.get("ttft_sec"),
                    "compliance": entry.get("compliance"),
                    "tokens_per_sec": entry.get("tokens_per_sec"),
                    "pass": entry.get("pass"),
                }
        for pid, meta in (data.get("provider_benchmarks") or {}).items():
            if isinstance(meta, dict) and pid:
                out[str(pid)] = meta
    return out


def _latency_ms_from_health(health: Dict[str, Any]) -> Optional[float]:
    if health.get("avg_latency_ms") is not None:
        return float(health["avg_latency_ms"])
    if health.get("last_latency_ms") is not None:
        return float(health["last_latency_ms"])
    if health.get("latency_sec") is not None:
        return round(float(health["latency_sec"]) * 1000.0, 1)
    detail = health.get("detail") if isinstance(health.get("detail"), dict) else {}
    if detail.get("latency_sec") is not None:
        return round(float(detail["latency_sec"]) * 1000.0, 1)
    return None


def _rank_cloud_providers(registry: Dict[str, Any], *, paid: bool) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    proc_bench = _procurement_benchmarks()
    section = "compute_providers"
    for entry in registry.get(section) or []:
        if not isinstance(entry, dict):
            continue
        is_free = ":free" in str(entry.get("model") or "").lower() or "free" in str(entry.get("id") or "").lower()
        if paid and is_free:
            continue
        if not paid and not is_free and "groq" not in str(entry.get("id") or "").lower():
            continue
        pid = str(entry.get("id") or "")
        enabled = bool(entry.get("enabled"))
        health = _provider_health(pid)
        h_status = str(health.get("status") or "unknown")
        priority = int(entry.get("priority") or 50)
        score = float(priority)
        if enabled:
            score += 20.0
        if h_status == "up":
            score += 15.0
        elif h_status == "down":
            score -= 30.0
        if health.get("blacklisted_until"):
            score -= 50.0
        latency = _latency_ms_from_health(health)
        if latency is not None:
            if latency < 800:
                score += 8.0
            elif latency > 5000:
                score -= 10.0
        bench = proc_bench.get(pid)
        if bench:
            if bench.get("pass") is True:
                score += 12.0
            elif bench.get("pass") is False:
                score -= 20.0
            ttft = bench.get("ttft_sec")
            if ttft is not None and float(ttft) < 8.0:
                score += 5.0
            compliance = bench.get("compliance")
            if compliance is not None:
                score += min(10.0, float(compliance) * 10.0)
        rows.append(
            {
                "id": pid,
                "name": str(entry.get("name") or pid),
                "tier": "paid_cloud" if paid else "free_cloud",
                "provider": str(entry.get("api_mode") or "openai_chat"),
                "model": str(entry.get("model") or ""),
                "status": "active" if enabled and h_status == "up" else ("configured" if enabled else "off"),
                "score": round(score, 1),
                "detail": f"health={h_status}" + (f" . {latency:.0f}ms" if latency is not None else ""),
                "benchmark": bench,
                "promotable": False,
            }
        )
    return sorted(rows, key=lambda r: r["score"], reverse=True)


def _rank_paid_config(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    moa = config.get("moa") or {}
    if moa.get("enabled"):
        agg = moa.get("aggregator") or {}
        rows.append(
            {
                "id": "moa_aggregator",
                "name": "MoA aggregator",
                "tier": "paid_cloud",
                "provider": str(agg.get("provider") or "openrouter"),
                "model": str(agg.get("model") or ""),
                "status": "standby",
                "score": 70.0,
                "detail": "Mixture-of-agents heavy reasoning",
                "benchmark": None,
                "promotable": False,
            }
        )
    if config.get("nous"):
        rows.append(
            {
                "id": "nous_portal",
                "name": "Nous Portal",
                "tier": "paid_cloud",
                "provider": "nous",
                "model": "portal multiplex",
                "status": "standby",
                "score": 65.0,
                "detail": "Paid portal fallback",
                "benchmark": None,
                "promotable": False,
            }
        )
    xs = config.get("x_search") or {}
    if xs.get("model"):
        rows.append(
            {
                "id": "xai_search",
                "name": "xAI",
                "tier": "paid_cloud",
                "provider": "xai",
                "model": str(xs["model"]),
                "status": "standby",
                "score": 60.0,
                "detail": "Search / reasoning escalation",
                "benchmark": None,
                "promotable": False,
            }
        )
    return sorted(rows, key=lambda r: r["score"], reverse=True)


def build_priority_state(*, refresh_cloud: bool = False) -> Dict[str, Any]:
    core = _load_json(CORE_PATH)
    config = _load_yaml(CONFIG_PATH)
    registry = _load_yaml(FLEET_REGISTRY)
    locked = bool(core.get("model_rotation_locked", True))
    fleet_on = bool((config.get("local_sovereign") or {}).get("opportunistic_fleet", {}).get("enabled"))

    cloud_refreshed = False
    if refresh_cloud:
        try:
            sys.path.insert(0, str(HERMES_ROOT / "scripts"))
            from opportunistic_fleet_agent import health_cycle  # type: ignore

            health_cycle()
            cloud_refreshed = True
        except Exception as exc:
            _log({"event": "cloud_refresh_failed", "error": str(exc)})

    local_ranked = _rank_local_models(core)
    free_ranked = _rank_cloud_providers(registry, paid=False) if fleet_on else []
    paid_registry = _rank_cloud_providers(registry, paid=True)
    paid_config = _rank_paid_config(config)
    paid_merged: Dict[str, Dict[str, Any]] = {}
    for row in paid_registry + paid_config:
        paid_merged[row["id"]] = row
    paid_ranked = sorted(paid_merged.values(), key=lambda r: r["score"], reverse=True)

    curator = _load_json(CURATOR_REPORT)
    last_tick = curator.get("timestamp") or curator.get("procurement", {}).get("timestamp")

    recommendation = None
    if not locked and local_ranked:
        top = next((r for r in local_ranked if r.get("promotable")), None)
        if top:
            recommendation = f"Consider promote: {top['name']} (score {top['score']})"
    elif locked:
        recommendation = "Rotation locked -- rankings inform only; active model unchanged"

    tiers = [
        {
            "id": "gpu_primary",
            "label": "GPU local",
            "subtitle": "VRAM-loaded + on-disk candidates",
            "models": local_ranked[:12],
            "active_id": next((r["id"] for r in local_ranked if r["status"] == "active"), None),
        },
        {
            "id": "gpu_standby",
            "label": "GPU standby",
            "subtitle": "Not loaded -- swap requires restart",
            "models": [r for r in local_ranked if r["status"] != "active"][:6],
            "active_id": None,
        },
        {
            "id": "internet_free",
            "label": "Internet free",
            "subtitle": "Tier 1.5 opportunistic fleet" + (" -- ON" if fleet_on else " -- OFF"),
            "models": free_ranked[:8],
            "active_id": free_ranked[0]["id"] if free_ranked else None,
        },
        {
            "id": "paid",
            "label": "Paid / MoA",
            "subtitle": "Heavy reasoning escalation",
            "models": paid_ranked[:6],
            "active_id": None,
        },
    ]

    fallback_chain = []
    if local_ranked:
        active = next((r for r in local_ranked if r["status"] == "active"), local_ranked[0])
        fallback_chain.append({"tier": "T0", "model": active["name"], "provider": "local_gpu"})
    fb = config.get("fallback_model") or []
    if isinstance(fb, list) and fb:
        entry = fb[0] if isinstance(fb[0], dict) else {}
        fallback_chain.append(
            {
                "tier": "T0-retry",
                "model": str(entry.get("model") or "phronesis-sovereign-auto"),
                "provider": str(entry.get("provider") or "local"),
            }
        )
    for i, row in enumerate(free_ranked[:3], start=1):
        fallback_chain.append({"tier": f"T2-{i}", "model": row["model"], "provider": row["name"]})
    for i, row in enumerate(paid_ranked[:2], start=1):
        fallback_chain.append({"tier": f"T3-{i}", "model": row["model"], "provider": row["name"]})

    state = {
        "panel_type": "model_priority",
        "version": "1.0",
        "updated_at": _utc_now(),
        "rotation_locked": locked,
        "fleet_enabled": fleet_on,
        "cloud_refreshed": cloud_refreshed,
        "agent": {
            "name": "model_priority_curator",
            "last_curator_tick": last_tick,
            "recommendation": recommendation,
            "next_actions": [
                "Run --tick on cron (6h) for ranking refresh",
                "Run --refresh-cloud when fleet enabled",
                "fleetctl promote when lock off + top candidate passes harness",
            ],
        },
        "tiers": tiers,
        "fallback_chain": fallback_chain,
    }
    return state


def write_state(state: Dict[str, Any]) -> Path:
    STATE_OUT.parent.mkdir(parents=True, exist_ok=True)
    STATE_OUT.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return STATE_OUT


def tick(*, refresh_cloud: bool = False) -> Dict[str, Any]:
    state = build_priority_state(refresh_cloud=refresh_cloud)
    write_state(state)
    _log({"event": "tick_complete", "models_ranked": sum(len(t["models"]) for t in state["tiers"])})
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Holistic model priority curator")
    parser.add_argument("--tick", action="store_true", help="Refresh rankings and write state file")
    parser.add_argument("--refresh-cloud", action="store_true", help="Run fleet health cycle before rank")
    parser.add_argument("--stdout", action="store_true", help="Print JSON to stdout")
    args = parser.parse_args()

    refresh = bool(args.refresh_cloud or args.tick)
    if args.tick:
        state = tick(refresh_cloud=refresh)
    else:
        state = build_priority_state(refresh_cloud=refresh)
        if args.stdout or args.refresh_cloud or not STATE_OUT.is_file():
            write_state(state)

    print(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())