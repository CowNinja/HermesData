#!/usr/bin/env python3
"""Scout HF GGUF + Ollama library tags. Metadata only. Never download.

Tier A: 7B-9B, 5.5-9.0 GB (3060 12GB native)
Tier B: 14B-32B, 9.5-24 GB (128GB RAM offload)

Writes D:\\HermesData\\state\\model_intake_queue.json only.
Dest always D:\\PhronesisModels\\models\\candidates. Never C:. Never ollama pull.

  python D:\\HermesData\\scripts\\ops\\model_feed_scanner.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERMES = Path(r"D:\HermesData")
OPS = HERMES / "scripts" / "ops"
STATE = HERMES / "state"
INTAKE = STATE / "model_intake_queue.json"
WEIGHT = Path(r"D:\PhronesisModels")
DEST = WEIGHT / "models" / "candidates"
SCAN_OUT = STATE / "model_feed_scan_latest.json"
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

TRUSTED = ("bartowski", "unsloth", "MaziyarPanahi")
FORBID = ("uncensored", "nsfw", "erotic", "grok", "abliterated-nsfw", "x-ai")
TIER_A = (5.5, 9.0)
TIER_B = (9.5, 24.0)


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def assert_dest() -> Path:
    d = DEST.resolve()
    if d.drive.upper() == "C:":
        raise RuntimeError("STORAGE_LAW: refuse C:")
    d.relative_to(WEIGHT.resolve())
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get(url: str, timeout: int = 18) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "HermesMMA/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _params_b(name: str) -> Optional[float]:
    m = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*b(?:illion)?\b", name.lower())
    if not m:
        return None
    return float(m.group(1))


def _tier(size_gb: float, params_b: Optional[float], name: str) -> Optional[str]:
    low = name.lower()
    if any(n in low for n in FORBID):
        return None
    if TIER_A[0] <= size_gb <= TIER_A[1]:
        if params_b is None or 7 <= params_b <= 9.5:
            return "A"
    if TIER_B[0] <= size_gb <= TIER_B[1]:
        if params_b is None or 14 <= params_b <= 32:
            return "B"
    return None


def _download_cmd(repo: str, filename: str) -> str:
    dest = str(assert_dest())
    return (
        f'huggingface-cli download {repo} {filename} '
        f'--local-dir "{dest}" --local-dir-use-symlinks False'
    )


def scan_hf(limit_models: int = 12) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    queries = [
        "https://huggingface.co/api/models?author=bartowski&search=Qwen2.5-7B-Instruct-GGUF&sort=downloads&limit=8&full=true",
        "https://huggingface.co/api/models?author=bartowski&search=Qwen2.5-14B-Instruct-GGUF&sort=downloads&limit=8&full=true",
        "https://huggingface.co/api/models?author=bartowski&search=Llama-3.1-8B-Instruct-GGUF&sort=downloads&limit=8&full=true",
        "https://huggingface.co/api/models?author=unsloth&search=Qwen2.5-GGUF&sort=downloads&limit=8&full=true",
    ]
    seed = [
        {"id": "bartowski/Qwen2.5-7B-Instruct-GGUF"},
        {"id": "bartowski/Qwen2.5-14B-Instruct-GGUF"},
        {"id": "bartowski/Qwen2.5-32B-Instruct-GGUF"},
        {"id": "bartowski/Llama-3.1-8B-Instruct-GGUF"},
        {"id": "bartowski/Qwen2.5-Coder-7B-Instruct-GGUF"},
    ]
    seen_repo = set()
    for url in queries:
        try:
            rows = _get(url)
        except Exception:
            continue
        if not isinstance(rows, list):
            continue
        if url == queries[0]:
            rows = seed + rows
        for m in rows:
            if not isinstance(m, dict):
                continue
            repo = str(m.get("id") or "")
            if not repo or repo in seen_repo:
                continue
            author = repo.split("/")[0] if "/" in repo else ""
            if author not in TRUSTED and "bartowski" not in repo.lower() and "unsloth" not in repo.lower():
                continue
            blob = (repo + " " + str(m.get("id") or "")).lower()
            if any(n in blob for n in FORBID):
                continue
            seen_repo.add(repo)
            try:
                tree = _get("https://huggingface.co/api/models/" + repo + "/tree/main", timeout=12)
            except Exception:
                tree = []
            if not isinstance(tree, list):
                tree = []
            params = _params_b(repo)
            for sib in tree:
                if not isinstance(sib, dict):
                    continue
                fn = str(sib.get("path") or sib.get("rfilename") or "")
                if not fn.lower().endswith(".gguf"):
                    continue
                fl = fn.lower()
                if any(x in fl for x in ("mmproj", "imatrix", "-f32", "-f16", "iq2_", "iq3_")):
                    continue
                size = sib.get("size") or (sib.get("lfs") or {}).get("size")
                if not size:
                    continue
                gb = float(size) / (1024**3)
                pb = _params_b(fn) or params
                tier = _tier(gb, pb, repo + " " + fn)
                if not tier:
                    continue
                found.append(
                    {
                        "repo": repo,
                        "file": fn,
                        "size_gb": round(gb, 2),
                        "params_b": pb,
                        "tier": tier,
                        "source": "huggingface",
                    }
                )
            if len(found) >= limit_models * 2:
                break
        if len(found) >= limit_models * 2:
            break
    # one file per repo: prefer Q6_K then Q5_K_M then Q4_K_M in-band
    by_repo: Dict[str, Dict[str, Any]] = {}
    rank = lambda f: (("q6_k" in f["file"].lower(), "q5_k" in f["file"].lower(), "q4_k" in f["file"].lower()),)
    for row in found:
        cur = by_repo.get(row["repo"])
        if cur is None or rank(row) > rank(cur):
            by_repo[row["repo"]] = row
    return list(by_repo.values())[:limit_models]


def scan_ollama_tags() -> List[Dict[str, Any]]:
    """Library names only. NEVER ollama pull (writes C:). Enqueue as GGUF-wanted."""
    tags = (
        ("qwen2.5:7b", "A", 7.0, 7.0),
        ("qwen2.5:14b", "B", 14.0, 9.0),
        ("qwen2.5-coder:7b", "A", 7.0, 7.0),
        ("qwen2.5-coder:14b", "B", 14.0, 9.0),
        ("llama3.1:8b", "A", 8.0, 6.5),
        ("gemma2:9b", "A", 9.0, 6.5),
        ("gemma2:27b", "B", 27.0, 16.0),
        ("qwen2.5:32b", "B", 32.0, 20.0),
    )
    out = []
    for name, tier, params, est_gb in tags:
        if (tier == "A" and TIER_A[0] <= est_gb <= TIER_A[1]) or (
            tier == "B" and TIER_B[0] <= est_gb <= TIER_B[1]
        ):
            out.append(
                {
                    "repo": "ollama-library",
                    "file": name,
                    "size_gb": est_gb,
                    "params_b": params,
                    "tier": tier,
                    "source": "ollama_library",
                    "note": "Do not ollama pull. Fetch matching GGUF to D:\\PhronesisModels\\models\\candidates.",
                }
            )
    return out


def enqueue(row: Dict[str, Any]) -> Dict[str, Any]:
    if str(OPS) not in sys.path:
        sys.path.insert(0, str(OPS))
    import mma_harvester as mma  # type: ignore

    name = (row.get("file") or row.get("repo") or "unknown")[:120]
    kind = "hf_gguf_candidate" if row.get("source") == "huggingface" else "ollama_tag_wanted_gguf"
    extra = {
        "tier": row.get("tier"),
        "size_gb": row.get("size_gb"),
        "params_b": row.get("params_b"),
        "repo": row.get("repo"),
        "file": row.get("file"),
        "source": row.get("source"),
        "never_auto_download": True,
        "download_cmd": (
            _download_cmd(str(row["repo"]), str(row["file"]))
            if row.get("source") == "huggingface"
            else "Do not ollama pull. huggingface-cli download matching GGUF into D:\\PhronesisModels\\models\\candidates"
        ),
    }
    if row.get("note"):
        extra["note"] = row["note"]
    return mma.enqueue_intake(kind, name, "feed_scanner_" + str(row.get("tier")), extra=extra)


def scan_and_enqueue() -> List[Dict[str, Any]]:
    assert_dest()
    hf = scan_hf()
    ol = scan_ollama_tags()
    queued = []
    for row in hf + ol:
        try:
            queued.append(enqueue(row))
        except Exception as exc:
            queued.append({"error": str(exc)[:160], "row": row.get("file")})
    doc = {
        "ts": utc(),
        "hf_n": len(hf),
        "ollama_n": len(ol),
        "queued": len(queued),
        "items": [
            {
                "name": q.get("name"),
                "tier": q.get("tier"),
                "size_gb": q.get("size_gb"),
                "source": q.get("source"),
            }
            for q in queued
            if isinstance(q, dict)
        ],
        "law": "metadata_only_never_auto_download_never_C",
    }
    SCAN_OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return queued


def main() -> int:
    rows = scan_and_enqueue()
    print(json.dumps({"queued": len(rows), "out": str(SCAN_OUT), "intake": str(INTAKE)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
