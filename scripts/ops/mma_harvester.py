#!/usr/bin/env python3
"""MMA harvester — free OpenRouter roster + local GGUF/Ollama inventory.

Storage law: model weights may land only under D:\\PhronesisModels\\. Never C:.

  python D:\\HermesData\\scripts\\ops\\mma_harvester.py --check-free
  python D:\\HermesData\\scripts\\ops\\mma_harvester.py --bench
  python D:\\HermesData\\scripts\\ops\\mma_harvester.py --status
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
from typing import Any, Dict, List, Optional

HERMES = Path(r"D:\HermesData")
OPS = HERMES / "scripts" / "ops"
STATE = HERMES / "state"
ROSTER = STATE / "mma_free_roster.json"
STATUS = STATE / "mma_harvester_latest.json"
INTAKE = STATE / "model_intake_queue.json"
LEADERBOARD = Path(r"D:\PhronesisVault\Operations\MODEL_BENCHMARK_LEADERBOARD.md")
WEIGHT_ROOT = Path(r"D:\PhronesisModels")
MODELS_DIR = WEIGHT_ROOT / "models"
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
PY = sys.executable

# OpenRouter :free slugs we already treat as named fleet slots.
SLOT_MAP = {
    "openrouter/free": "openrouter-free-router",
    "google/gemma-4-26b-a4b-it:free": "openrouter-free-gemma",
    "nvidia/nemotron-3-nano-30b-a3b:free": "openrouter-free-nemotron-nano",
    "nvidia/nemotron-3-super-120b-a12b:free": "openrouter-free-nemotron-super",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": "openrouter-free-nemotron-omni",
    "poolside/laguna-s-2.1:free": "openrouter-free-laguna-s",
}

FORBID_NEEDLES = ("uncensored", "nsfw", "erotic", "grok", "x-ai/", "xai/")


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def assert_weight_path(path: Path) -> None:
    resolved = path.resolve()
    root = WEIGHT_ROOT.resolve()
    if resolved.drive.upper() == "C:":
        raise RuntimeError("STORAGE_LAW: refuse C: weight path " + str(resolved))
    try:
        resolved.relative_to(root)
    except ValueError:
        if resolved.drive.upper() != "D:":
            raise RuntimeError("STORAGE_LAW: weights only on D:\\PhronesisModels " + str(resolved))


def _openrouter_key() -> str:
    k = (os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_KEY") or "").strip()
    if k:
        return k
    envp = HERMES / ".env"
    if envp.is_file():
        for line in envp.read_text(encoding="utf-8", errors="replace").splitlines():
            t = line.strip()
            if t.startswith("OPENROUTER_API_KEY=") or t.startswith("OPENROUTER_KEY="):
                val = t.split("=", 1)[1].split("#", 1)[0].strip().strip("'").strip('"')
                if val:
                    return val
    return ""


def harvest_free_cloud(limit: int = 40) -> Dict[str, Any]:
    key = _openrouter_key()
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request("https://openrouter.ai/api/v1/models", headers=headers, method="GET")
    listed: List[Dict[str, Any]] = []
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        rows = data.get("data") or data.get("models") or []
        for m in rows:
            if not isinstance(m, dict):
                continue
            mid = str(m.get("id") or "")
            if ":free" not in mid.lower() and not mid.endswith("/free"):
                continue
            blob = (mid + " " + str(m.get("name") or "")).lower()
            if any(n in blob for n in FORBID_NEEDLES):
                continue
            listed.append(
                {
                    "id": mid,
                    "name": m.get("name"),
                    "context": (m.get("context_length") or m.get("top_provider", {}).get("context_length")),
                    "slot": SLOT_MAP.get(mid),
                }
            )
            if len(listed) >= limit:
                break
        err = None
    except Exception as exc:
        err = type(exc).__name__ + ":" + str(exc)[:160]
        listed = []
    listed_ids = {str(row.get("id") or "") for row in listed}
    healthy_ids: List[str] = []
    for slug, slot in SLOT_MAP.items():
        if slug == "openrouter/free" or slug in listed_ids:
            if slot not in healthy_ids:
                healthy_ids.append(slot)
    for row in listed:
        slot = row.get("slot")
        if slot:
            if slot not in healthy_ids:
                healthy_ids.append(slot)
            continue
        slug = str(row["id"]).replace("/", "-").replace(":", "-")
        pid = "openrouter-free-" + slug[:48]
        if pid not in healthy_ids:
            healthy_ids.append(pid)
    if "openrouter-free-router" not in healthy_ids:
        healthy_ids.insert(0, "openrouter-free-router")
    roster = {
        "ts": utc(),
        "source": "openrouter_models",
        "error": err,
        "n_listed": len(listed),
        "models": listed[:limit],
        "healthy_provider_ids": healthy_ids[:12],
        "law": "tier2_free_only_never_grok_never_rp",
    }
    ROSTER.parent.mkdir(parents=True, exist_ok=True)
    ROSTER.write_text(json.dumps(roster, indent=2), encoding="utf-8")
    return roster


def scan_ollama() -> Dict[str, Any]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        models = []
        for m in data.get("models") or []:
            models.append(
                {
                    "name": m.get("name"),
                    "size_gb": round(int(m.get("size") or 0) / (1024**3), 2),
                    "digest": str(m.get("digest") or "")[:16],
                }
            )
        return {"ok": True, "n": len(models), "models": models}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:160], "models": []}


def scan_gguf(max_files: int = 80) -> Dict[str, Any]:
    assert_weight_path(MODELS_DIR)
    found: List[Dict[str, Any]] = []
    if not MODELS_DIR.exists():
        return {"ok": False, "error": "models_dir_missing", "models": []}
    n_walk = 0
    for p in MODELS_DIR.rglob("*.gguf"):
        n_walk += 1
        if n_walk > 4000:
            break
        try:
            assert_weight_path(p)
            st = p.stat()
        except (OSError, RuntimeError):
            continue
        rel = str(p.relative_to(MODELS_DIR))
        found.append(
            {
                "path": rel,
                "gb": round(st.st_size / (1024**3), 2),
                "name": p.name,
            }
        )
        if len(found) >= max_files:
            break
    found.sort(key=lambda r: r.get("gb") or 0, reverse=True)
    return {"ok": True, "n": len(found), "root": str(MODELS_DIR), "models": found}


WANTED_TAGS = (
    "qwen2.5-coder:7b",
    "qwen2.5-coder:14b",
    "llama3.2:3b",
    "llama3.2:1b",
    "qwen2.5:3b",
)


def _load_intake() -> list:
    if not INTAKE.is_file():
        return []
    try:
        data = json.loads(INTAKE.read_text(encoding="utf-8"))
        return list(data.get("items") or [])
    except Exception:
        return []


def _save_intake(items: list) -> None:
    INTAKE.parent.mkdir(parents=True, exist_ok=True)
    INTAKE.write_text(
        json.dumps({"ts": utc(), "dest_root": str(MODELS_DIR), "items": items}, indent=2),
        encoding="utf-8",
    )


def enqueue_intake(kind: str, name: str, reason: str, extra: Optional[Dict[str, Any]] = None) -> dict:
    assert_weight_path(MODELS_DIR)
    dest = MODELS_DIR / "candidates"
    dest.mkdir(parents=True, exist_ok=True)
    assert_weight_path(dest)
    items = _load_intake()
    key = kind + ":" + name
    for it in items:
        if it.get("key") == key and it.get("status") in ("queued", "bench"):
            return it
    rec = {
        "key": key,
        "kind": kind,
        "name": name,
        "reason": reason,
        "status": "queued",
        "dest": str(dest),
        "never_c": True,
        "never_auto_download": True,
        "queued_ts": utc(),
        "note": "Do not ollama pull (writes C:\\Users\\...\\.ollama). GGUF to D:\\PhronesisModels only.",
    }
    if extra:
        rec.update({k: v for k, v in extra.items() if k not in rec or k in ("note", "tier", "size_gb", "download_cmd", "repo", "file", "source", "params_b")})
    items.append(rec)
    _save_intake(items[-80:])
    return rec


def discover_candidates(ollama: Dict[str, Any], roster: Dict[str, Any], gguf: Dict[str, Any]) -> list:
    have_tags = {str(m.get("name") or "").split(":")[0] for m in (ollama.get("models") or [])}
    have_tags |= {str(m.get("name") or "") for m in (ollama.get("models") or [])}
    queued = []
    for tag in WANTED_TAGS:
        base = tag.split(":")[0]
        if tag in have_tags or base in have_tags:
            continue
        queued.append(enqueue_intake("ollama_tag_wanted", tag, "popular_tag_not_local_do_not_pull_to_C"))
    gguf_blob = " ".join(g.get("name") or "" for g in (gguf.get("models") or [])).lower()
    for needle, label in (
        ("qwen2.5-coder-7b", "Qwen2.5-Coder-7B GGUF"),
        ("llama-3.2-3b", "Llama-3.2-3B GGUF"),
    ):
        if needle not in gguf_blob:
            queued.append(enqueue_intake("gguf_wanted", label, "not_in_D_PhronesisModels_scan"))
    for row in roster.get("models") or []:
        mid = str(row.get("id") or "")
        if ":free" in mid.lower() and not row.get("slot"):
            queued.append(enqueue_intake("openrouter_free_new", mid, "new_free_slug"))
    return queued[-20:]


def last_mma_bench() -> Dict[str, Any]:
    bdir = STATE / "benchmarks"
    if not bdir.is_dir():
        return {}
    files = sorted(bdir.glob("mma_tool_*.json"), reverse=True)
    md = sorted(bdir.glob("mma_tool_*.md"), reverse=True)
    rec: Dict[str, Any] = {}
    if files:
        try:
            rec = json.loads(files[0].read_text(encoding="utf-8"))
            rec["_file"] = str(files[0])
            rec.setdefault("schema", rec.get("schema_validity"))
            rec.setdefault("leak", rec.get("narration_leak_rate"))
            rec.setdefault("tok_s", rec.get("tok_s_mean"))
        except Exception:
            rec = {}
    if not rec and md:
        rec = {"_file": str(md[0]), "note": "markdown_only"}
        text = md[0].read_text(encoding="utf-8", errors="replace")
        rec["excerpt"] = text[:800]
    return rec


def run_local_bench() -> Dict[str, Any]:
    script = OPS / "mma_tool_benchmark.py"
    if not script.is_file():
        return {"ok": False, "error": "mma_tool_benchmark.py missing"}
    try:
        p = subprocess.run(
            [PY, str(script), "--n", "15"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
            cwd=str(OPS),
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        return {
            "ok": p.returncode == 0,
            "rc": p.returncode,
            "stdout_tail": (p.stdout or "")[-600:],
            "latest": last_mma_bench(),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def write_leaderboard(roster: Dict[str, Any], ollama: Dict[str, Any], gguf: Dict[str, Any], bench: Dict[str, Any]) -> str:
    schema = bench.get("schema") or bench.get("schema_ok") or bench.get("schema_pct")
    leak = bench.get("leak") or bench.get("leak_pct")
    tok = bench.get("tok_s") or bench.get("tok_per_s")
    n = bench.get("n")
    # flatten nested latest
    latest = bench.get("latest") or {}
    if isinstance(latest, dict) and latest:
        schema = schema or latest.get("schema") or latest.get("schema_pct")
        leak = leak if leak is not None else latest.get("leak")
        tok = tok or latest.get("tok_s")
        n = n or latest.get("n")

    lines = [
        "# MODEL BENCHMARK LEADERBOARD",
        "",
        f"stamped={utc()}",
        "Law: local Qwythos 9B is Tier 1. OpenRouter `:free` is Tier 2. Never Grok. Never C: weights.",
        "",
        "## Local (12 GB VRAM / 128 GB RAM)",
        "",
        "| Rank | Model | Plane | Schema | Leak | Tok/s | Footprint |",
        "|---|---|---|---|---|---|---|",
        f"| 1 | Qwythos 9B Q6_K (`:8090`) | local llama-server | {schema if schema is not None else 'see MMA'} | {leak if leak is not None else '0 target'} | {tok if tok is not None else '~10'} | 12 GB VRAM ngl 99 |",
        "| — | Hybrid 14B (`:8092`) | RAM reserve | parked | — | — | ngl 24 + RAM; default OFF |",
        "",
        f"Ollama tags @ :11434: **{ollama.get('n') or 0}** (embeddings/aux, not the Discord mouth).",
        "",
    ]
    for m in (ollama.get("models") or [])[:8]:
        lines.append(f"- `{m.get('name')}` {m.get('size_gb')} GB")
    lines += [
        "",
        f"GGUF under `{MODELS_DIR}`: **{gguf.get('n') or 0}** files (scan cap).",
        "",
    ]
    for g in (gguf.get("models") or [])[:12]:
        lines.append(f"- `{g.get('name')}` {g.get('gb')} GB — `{g.get('path')}`")
    lines += [
        "",
        "## Free cloud (Tier 2, OpenRouter)",
        "",
        f"Listed `:free` this harvest: **{roster.get('n_listed') or 0}**. Router slot ids:",
        "",
    ]
    for i, pid in enumerate(roster.get("healthy_provider_ids") or [], 1):
        lines.append(f"{i}. `{pid}`")
    if roster.get("error"):
        lines.append("")
        lines.append(f"_Harvest note: {roster.get('error')}_")
    lines += [
        "",
        "## Guards",
        "",
        "- Downloads (if ever) → `D:\\PhronesisModels\\` only. C: refused.",
        "- RP / medical / secrets stay local 9B. Free cloud never those lanes.",
        "- Overnight `--check-free` does not steal 9B VRAM. `--bench` is explicit.",
        "",
        f"Receipt: `{STATUS}`",
        f"Roster overlay: `{ROSTER}`",
        "",
    ]
    LEADERBOARD.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines)
    LEADERBOARD.write_text(text, encoding="utf-8")
    return text


def summary_for_macro() -> str:
    roster: Dict[str, Any] = {}
    if ROSTER.is_file():
        try:
            roster = json.loads(ROSTER.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            roster = {}
    bench = last_mma_bench()
    ids = roster.get("healthy_provider_ids") or []
    lines = [
        "**Models** (no LLM)",
        "- Local mouth: **Qwythos 9B Q6_K** `:8090` via `:8091` (12 GB VRAM, 128k ctx)",
        "- Hybrid 14B `:8092`: parked (RAM reserve, default off)",
    ]
    if bench:
        lines.append(
            f"- Last MMA: schema={bench.get('schema') or bench.get('schema_pct')} "
            f"leak={bench.get('leak')} tok/s={bench.get('tok_s')} file={Path(str(bench.get('_file') or '')).name}"
        )
    lines.append("- Free Tier-2 (OpenRouter):")
    if ids:
        for pid in ids[:6]:
            lines.append(f"  - `{pid}`")
    else:
        lines.append("  - (roster empty — run mma_harvester --check-free)")
    lines.append(f"- Board: `D:\\PhronesisVault\\Operations\\MODEL_BENCHMARK_LEADERBOARD.md`")
    return "\n".join(lines)


def run(*, check_free: bool, bench: bool) -> Dict[str, Any]:
    roster = harvest_free_cloud() if check_free or bench else (
        json.loads(ROSTER.read_text(encoding="utf-8")) if ROSTER.is_file() else {}
    )
    ollama = scan_ollama()
    gguf = scan_gguf()
    intake = discover_candidates(roster if isinstance(roster, dict) else {}, ollama, gguf)
    feed: list = []
    try:
        import model_feed_scanner as _feed

        feed = _feed.scan_and_enqueue()
        intake = list(intake) + list(feed or [])
    except Exception:
        feed = []
    bench_rec: Dict[str, Any] = last_mma_bench()
    if bench:
        bench_rec = run_local_bench()
    write_leaderboard(roster, ollama, gguf, bench_rec if isinstance(bench_rec, dict) else {})
    doc = {
        "ts": utc(),
        "check_free": check_free,
        "bench": bench,
        "roster_n": roster.get("n_listed"),
        "healthy_ids": roster.get("healthy_provider_ids"),
        "ollama": {"ok": ollama.get("ok"), "n": ollama.get("n")},
        "gguf": {"ok": gguf.get("ok"), "n": gguf.get("n")},
        "leaderboard": str(LEADERBOARD),
        "weight_root": str(WEIGHT_ROOT),
        "c_drive_weights": False,
        "intake_queued": len(intake),
        "feed_queued": len(feed) if isinstance(feed, list) else 0,
        "intake": str(INTAKE),
    }
    STATUS.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-free", action="store_true")
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.status and not args.check_free and not args.bench:
        print(summary_for_macro())
        return 0
    doc = run(check_free=args.check_free or not args.bench, bench=args.bench)
    print(
        f"MMA_HARVEST listed={doc.get('roster_n')} ollama={doc.get('ollama')} "
        f"gguf={doc.get('gguf')} board={doc.get('leaderboard')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
