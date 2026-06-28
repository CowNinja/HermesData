#!/usr/bin/env python3
"""
model_benchmark_harness.py — Lightweight GGUF candidate vs incumbent benchmark.

Metrics per tier slot:
  - TTFT (time to first token, streaming)
  - tokens/sec throughput
  - prompt-compliance smoke score (task_type aligned)

Usage:
  python model_benchmark_harness.py --tier hot
  python model_benchmark_harness.py --tier warm --candidate Qwen2.5-7B-Instruct-Q5_K_M.gguf
  python model_benchmark_harness.py --tier warm --candidate FILE.gguf --promote-if-pass
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VAULT_SCRIPTS = Path(r"D:\PhronesisVault\scripts")
HERMES_SCRIPTS = Path(__file__).resolve().parent
if str(VAULT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(VAULT_SCRIPTS))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "vault_model_inventory",
    VAULT_SCRIPTS / "model_inventory.py",
)
_vault_mi = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_vault_mi)

CANDIDATES = _vault_mi.CANDIDATES
CURRENT = _vault_mi.CURRENT
LIFECYCLE_PATH = _vault_mi.LIFECYCLE_PATH
TIER_SLOTS = _vault_mi.TIER_SLOTS
load_lifecycle_manifest = _vault_mi.load_lifecycle_manifest
promote_gguf = _vault_mi.promote_gguf

BENCHMARK_LOG = Path(r"D:\PhronesisVault\Operations\logs\model-benchmark.jsonl")
LLAMA_SERVER = Path(r"D:\PhronesisModels\binaries\test-prebuilts\2026-06-19-b9731-cpu\llama-server.exe")
BENCH_PORT = 8098

# task_type-aligned smoke prompts (short for fast iteration)
SMOKE_PROMPTS: Dict[str, Dict[str, Any]] = {
    "hot": {
        "task_type": "code",
        "prompt": (
            "Write ONLY a Python function named hello_world that returns the string "
            "'hello'. No markdown fences, no explanation."
        ),
        "must_match": r"def\s+hello_world",
    },
    "warm": {
        "task_type": "synthesis",
        "prompt": (
            "Summarize in exactly 3 bullet points why local MoE routing saves cloud cost. "
            "Start each line with '- '."
        ),
        "must_match": r"(?m)^-\s+",
    },
    "classifier": {
        "task_type": "classify",
        "prompt": (
            "Classify this task as CODE or CHAT. Reply with exactly one word: CODE or CHAT.\n"
            "Task: refactor the authentication middleware."
        ),
        "must_match": r"\bCODE\b",
    },
    "cold": {
        "task_type": "deep_analysis",
        "prompt": (
            "In 2 sentences, explain tradeoffs between 7B warm tier and 35B cold tier "
            "for coding tasks. Mention latency."
        ),
        "must_match": r"latency",
    },
}

# Minimum bar vs incumbent (fractional improvement or absolute floor)
PASS_RULES = {
    "ttft_max_ratio": 1.15,  # candidate TTFT must be <= 115% of incumbent
    "tps_min_ratio": 0.85,  # candidate tok/s >= 85% of incumbent
    "compliance_min": 0.67,  # at least 2/3 smoke checks pass
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(event: Dict[str, Any]) -> None:
    try:
        BENCHMARK_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(BENCHMARK_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": _utc_now(), **event}) + "\n")
    except Exception:
        pass


def _http_json(url: str, payload: Optional[dict] = None, timeout: float = 120.0) -> Tuple[int, Any]:
    data = None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"error": body[:500]}
        return exc.code, parsed


def _stream_benchmark(base_url: str, prompt: str, *, max_tokens: int = 128) -> Dict[str, Any]:
    """Return ttft_sec, total_sec, output_tokens, tokens_per_sec."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": "bench",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "stream": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    started = time.time()
    ttft: Optional[float] = None
    chunks: List[str] = []
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    evt = json.loads(data_str)
                except Exception:
                    continue
                delta = (
                    evt.get("choices", [{}])[0]
                    .get("delta", {})
                    .get("content")
                )
                if delta:
                    if ttft is None:
                        ttft = time.time() - started
                    chunks.append(str(delta))
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "ttft_sec": ttft,
            "total_sec": time.time() - started,
            "output_tokens": 0,
            "tokens_per_sec": 0.0,
            "text": "",
        }

    total = time.time() - started
    text = "".join(chunks)
    out_tokens = max(1, len(text) // 4)
    tps = out_tokens / max(total - (ttft or 0), 0.01)
    return {
        "ok": True,
        "ttft_sec": round(ttft or total, 3),
        "total_sec": round(total, 3),
        "output_tokens": out_tokens,
        "tokens_per_sec": round(tps, 2),
        "text": text[:2000],
    }


def _compliance_score(text: str, pattern: str) -> float:
    import re

    if not text:
        return 0.0
    return 1.0 if re.search(pattern, text, re.IGNORECASE | re.MULTILINE) else 0.0


def _tier_port(tier_slot: str) -> int:
    return int(TIER_SLOTS[tier_slot]["port"])


def _incumbent_filename(tier_slot: str) -> Optional[str]:
    manifest = load_lifecycle_manifest()
    return (manifest.get("tier_pins") or {}).get(tier_slot)


def _probe_port(port: int) -> bool:
    try:
        status, _ = _http_json(f"http://127.0.0.1:{port}/health", timeout=3.0)
        return status == 200
    except Exception:
        return False


def _start_ephemeral_server(gguf_path: Path, port: int) -> Optional[subprocess.Popen]:
    if not LLAMA_SERVER.is_file():
        return None
    if not gguf_path.is_file():
        return None
    log_out = Path(r"D:\PhronesisVault\Operations\logs") / f"bench-llama-{port}.log"
    log_out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(LLAMA_SERVER),
        "--model",
        str(gguf_path),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--ctx-size",
        "12288",
        "--n-gpu-layers",
        "0",
        "--parallel",
        "2",
        "--cont-batching",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=open(log_out, "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        cwd=str(LLAMA_SERVER.parent),
    )
    for _ in range(40):
        if _probe_port(port):
            return proc
        time.sleep(0.5)
    proc.kill()
    return None


def _stop_proc(proc: Optional[subprocess.Popen]) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def benchmark_on_port(port: int, tier_slot: str) -> Dict[str, Any]:
    smoke = SMOKE_PROMPTS[tier_slot]
    base = f"http://127.0.0.1:{port}/v1"
    stream = _stream_benchmark(base, smoke["prompt"])
    compliance = _compliance_score(stream.get("text") or "", smoke["must_match"])
    return {
        "port": port,
        "tier_slot": tier_slot,
        "task_type": smoke["task_type"],
        **stream,
        "compliance_score": compliance,
        "composite_score": round(
            (compliance * 0.4)
            + (min(stream.get("tokens_per_sec", 0) / 50.0, 1.0) * 0.35)
            + (max(0.0, 1.0 - (stream.get("ttft_sec") or 99) / 10.0) * 0.25),
            3,
        ),
    }


def compare_results(incumbent: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    if not incumbent.get("ok") or not candidate.get("ok"):
        return {
            "recommendation": "hold",
            "reason": "benchmark_failed",
            "incumbent_ok": incumbent.get("ok"),
            "candidate_ok": candidate.get("ok"),
        }

    ttft_ratio = (candidate.get("ttft_sec") or 99) / max(incumbent.get("ttft_sec") or 1, 0.01)
    tps_ratio = (candidate.get("tokens_per_sec") or 0) / max(incumbent.get("tokens_per_sec") or 1, 0.01)
    comp_ok = (
        candidate.get("compliance_score", 0) >= PASS_RULES["compliance_min"]
        and incumbent.get("compliance_score", 0) >= PASS_RULES["compliance_min"]
    )
    perf_ok = (
        ttft_ratio <= PASS_RULES["ttft_max_ratio"]
        and tps_ratio >= PASS_RULES["tps_min_ratio"]
    )
    better = candidate.get("composite_score", 0) > incumbent.get("composite_score", 0)

    if comp_ok and perf_ok and better:
        return {
            "recommendation": "promote",
            "ttft_ratio": round(ttft_ratio, 3),
            "tps_ratio": round(tps_ratio, 3),
            "composite_delta": round(
                candidate.get("composite_score", 0) - incumbent.get("composite_score", 0),
                3,
            ),
        }
    return {
        "recommendation": "hold",
        "ttft_ratio": round(ttft_ratio, 3),
        "tps_ratio": round(tps_ratio, 3),
        "composite_delta": round(
            candidate.get("composite_score", 0) - incumbent.get("composite_score", 0),
            3,
        ),
        "comp_ok": comp_ok,
        "perf_ok": perf_ok,
        "better": better,
    }


def run_benchmark(
    tier_slot: str,
    candidate_filename: Optional[str] = None,
    *,
    promote_if_pass: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    tier_slot = tier_slot.lower().strip()
    if tier_slot not in TIER_SLOTS:
        return {"ok": False, "error": f"invalid_tier:{tier_slot}"}

    port = _tier_port(tier_slot)
    incumbent_name = _incumbent_filename(tier_slot)
    result: Dict[str, Any] = {
        "ok": True,
        "tier_slot": tier_slot,
        "tier": TIER_SLOTS[tier_slot],
        "incumbent": incumbent_name,
        "timestamp": _utc_now(),
    }

    if not _probe_port(port):
        result["ok"] = False
        result["error"] = f"tier_port_down:{port}"
        return result

    result["incumbent_metrics"] = benchmark_on_port(port, tier_slot)

    if not candidate_filename:
        result["recommendation"] = "incumbent_only"
        _log({"event": "benchmark", **result})
        return result

    cand_path = CANDIDATES / candidate_filename
    if not cand_path.is_file():
        cand_path = CURRENT / candidate_filename
    if not cand_path.is_file():
        result["ok"] = False
        result["error"] = f"candidate_not_found:{candidate_filename}"
        return result

    bench_proc = _start_ephemeral_server(cand_path, BENCH_PORT)
    if bench_proc is None:
        result["ok"] = False
        result["error"] = "ephemeral_server_failed"
        return result

    try:
        result["candidate"] = candidate_filename
        result["candidate_metrics"] = benchmark_on_port(BENCH_PORT, tier_slot)
        result["comparison"] = compare_results(
            result["incumbent_metrics"],
            result["candidate_metrics"],
        )
        result["recommendation"] = result["comparison"].get("recommendation", "hold")

        if promote_if_pass and result["recommendation"] == "promote" and not dry_run:
            promo = promote_gguf(candidate_filename, tier_slot)
            result["promote"] = promo
            result["promoted"] = promo.get("ok", False)
    finally:
        _stop_proc(bench_proc)

    _log({"event": "benchmark", **result})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Phronesis MoE GGUF benchmark harness")
    parser.add_argument("--tier", required=True, choices=sorted(TIER_SLOTS))
    parser.add_argument("--candidate", metavar="FILE.gguf", help="Candidate GGUF in candidates/")
    parser.add_argument("--promote-if-pass", action="store_true", help="Call model_inventory --promote on pass")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", default=True)
    args = parser.parse_args()

    report = run_benchmark(
        args.tier,
        args.candidate,
        promote_if_pass=args.promote_if_pass,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
