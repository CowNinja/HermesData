#!/usr/bin/env python3
"""Fast ripgrep/FTS across Vault + Attic. JSON stdout only.

Banned silos (Navy/Medical/Patient-BLOOM/RP/secrets) are skipped.
Never searches D: models or Four Worlds operator secrets.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

ROOTS = {
    "vault": Path(r"D:\PhronesisVault"),
    "attic": Path(r"K:\Phronesis-Sovereign"),
}

BAN_NEEDLES = (
    "patient-bloom",
    "medical-records",
    "navy-service",
    "roleplay-sandbox",
    "nutaku",
    "secrets-quarantine",
    "dicom",
    "volbrain",
    "deers",
)

ENTITIES = ROOTS["vault"] / "Entities"

FTS_CANDIDATES = [
    Path(r"D:\HermesData\state\life_rag\ann_meta.jsonl"),
    Path(r"D:\HermesData\state\life_rag\kg.jsonl"),
]

DEFAULT_GLOBS = ["*.md", "*.txt", "*.json", "*.jsonl", "*.yaml", "*.yml"]


def _banned(path: str) -> bool:
    lower = path.lower().replace("/", "\\")
    if any(n in lower for n in BAN_NEEDLES):
        return True
    if "\\medical\\" in lower or "/medical/" in path.lower():
        return True
    return False


def _entity_hits(query: str, max_hits: int) -> List[dict]:
    if not ENTITIES.is_dir():
        return []
    q = query.lower().strip()
    qslug = q.replace(" ", "-")
    out: List[dict] = []
    for p in sorted(ENTITIES.glob("ENTITY-*.md")):
        stem = p.stem.lower()
        name = stem.replace("entity-", "")
        if not (q in name or qslug in name or name in q or q in stem):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out.append(
            {
                "path": str(p),
                "line": 1,
                "snippet": " ".join(text.split())[:180],
                "engine": "entity_dossier",
            }
        )
        if len(out) >= max_hits:
            break
    return out


def _parse_args(argv: List[str] | None = None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_blob", default="")
    ap.add_argument("--query", default="")
    ap.add_argument("--roots", default="both")
    ap.add_argument("--max-hits", type=int, default=24)
    ap.add_argument("--glob", default="")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--format", default="")
    args = ap.parse_args(argv)
    payload: Dict[str, Any] = {}
    if args.json_blob:
        raw = args.json_blob
        if raw.startswith("'") and raw.endswith("'"):
            raw = raw[1:-1]
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, str):
                loaded = json.loads(loaded)
            if isinstance(loaded, dict):
                payload = loaded
        except Exception:
            payload = {"query": args.json_blob}
    if args.query:
        payload.setdefault("query", args.query)
    if args.roots:
        payload.setdefault("roots", args.roots)
    if args.max_hits:
        payload.setdefault("max_hits", args.max_hits)
    if args.glob:
        payload.setdefault("glob", args.glob)
    if args.markdown:
        payload["format"] = "markdown"
    if args.format:
        payload["format"] = args.format
    return payload


def _roots(spec: str) -> List[Path]:
    key = (spec or "both").strip().lower()
    if key in ("vault", "phronesisvault", "d"):
        return [ROOTS["vault"]]
    if key in ("attic", "k", "silo", "sovereign"):
        return [ROOTS["attic"]]
    return [ROOTS["vault"], ROOTS["attic"]]


def _rg_hits(query: str, roots: List[Path], max_hits: int, glob: str) -> List[dict]:
    rg = shutil.which("rg") or shutil.which("rg.exe")
    if not rg:
        return []
    hits: List[dict] = []
    globs = [glob] if glob else DEFAULT_GLOBS
    for root in roots:
        if not root.exists():
            continue
        cmd = [
            rg,
            "--json",
            "-i",
            "-m",
            "8",
            "--max-filesize",
            "2M",
            "--max-columns",
            "240",
        ]
        for g in globs:
            cmd.extend(["-g", g])
        for ban in BAN_NEEDLES:
            cmd.extend(["-g", f"!{ban}"])
            cmd.extend(["-g", f"!**/*{ban}*/**"])
        cmd.extend(["--", query, str(root)])
        try:
            p = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=12,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception:
            continue
        for line in (p.stdout or "").splitlines():
            if len(hits) >= max_hits:
                return hits
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") != "match":
                continue
            data = obj.get("data") or {}
            path = str((data.get("path") or {}).get("text") or "")
            if not path or _banned(path):
                continue
            lines = data.get("lines") or {}
            text = str(lines.get("text") or "").strip()[:240]
            ln = (data.get("line_number") or 0)
            if _banned(path) or _banned(text):
                continue
            hits.append({"path": path, "line": ln, "snippet": text, "engine": "rg"})
    return hits


def _walk_hits(query: str, roots: List[Path], max_hits: int) -> List[dict]:
    needle = query.lower()
    hits: List[dict] = []
    exts = {".md", ".txt", ".json", ".jsonl", ".yaml", ".yml"}
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            if _banned(dirpath):
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if not _banned(os.path.join(dirpath, d))]
            for name in filenames:
                if len(hits) >= max_hits:
                    return hits
                fp = os.path.join(dirpath, name)
                if Path(name).suffix.lower() not in exts:
                    continue
                if _banned(fp):
                    continue
                try:
                    if os.path.getsize(fp) > 2 * 1024 * 1024:
                        continue
                    with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                        for i, line in enumerate(fh, 1):
                            if needle in line.lower():
                                hits.append(
                                    {
                                        "path": fp,
                                        "line": i,
                                        "snippet": line.strip()[:240],
                                        "engine": "walk",
                                    }
                                )
                                break
                except OSError:
                    continue
    return hits


def _fts_hits(query: str, max_hits: int) -> List[dict]:
    hits: List[dict] = []
    needle = query.lower()
    for path in FTS_CANDIDATES:
        if not path.is_file() or _banned(str(path)):
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    if needle in line.lower():
                        hits.append(
                            {
                                "path": str(path),
                                "line": i,
                                "snippet": line.strip()[:240],
                                "engine": "fts_jsonl",
                            }
                        )
                        if len(hits) >= max_hits:
                            return hits
                    if i > 200000:
                        break
        except OSError:
            continue
    # Optional sqlite FTS if a vault index appears later
    sqlite_idx = Path(r"D:\HermesData\state\vault_fts.sqlite")
    if sqlite_idx.is_file():
        try:
            con = sqlite3.connect(f"file:{sqlite_idx}?mode=ro", uri=True, timeout=2)
            try:
                rows = con.execute(
                    "SELECT path, snippet FROM vault_fts WHERE vault_fts MATCH ? LIMIT ?",
                    (query, max_hits),
                ).fetchall()
                for path, snippet in rows:
                    if _banned(str(path)):
                        continue
                    hits.append(
                        {
                            "path": path,
                            "line": 0,
                            "snippet": str(snippet or "")[:240],
                            "engine": "sqlite_fts",
                        }
                    )
            finally:
                con.close()
        except Exception:
            pass
    return hits[:max_hits]


def run(payload: Dict[str, Any]) -> Dict[str, Any]:
    started = time.time()
    query = str(payload.get("query") or "").strip()
    if len(query) < 2:
        return {"ok": False, "error": "query_too_short", "hits": []}
    max_hits = int(payload.get("max_hits") or 24)
    max_hits = max(1, min(max_hits, 80))
    roots = _roots(str(payload.get("roots") or "both"))
    glob = str(payload.get("glob") or "").strip()
    hits = _entity_hits(query, max_hits)
    engine = "entity_dossier" if hits else "rg"
    if not hits:
        rest_cap = max(1, max_hits)
        more = _rg_hits(query, roots, rest_cap + 16, glob)
        seen = {(h.get("path"), h.get("line")) for h in hits}
        for h in more:
            key = (h.get("path"), h.get("line"))
            if key in seen:
                continue
            hits.append(h)
            seen.add(key)
            if len(hits) >= max_hits + 16:
                break
    if not hits:
        engine = "rg_empty"
    if not hits and not shutil.which("rg") and not shutil.which("rg.exe"):
        hits = _walk_hits(query, roots, max_hits)
        engine = "walk"
    extra = _fts_hits(query, max(4, max_hits // 4))
    seen = {(h.get("path"), h.get("line")) for h in hits}
    for h in extra:
        key = (h.get("path"), h.get("line"))
        if key not in seen:
            hits.append(h)
            seen.add(key)
        if len(hits) >= max_hits:
            break
    clean = []
    banned_dropped = 0
    for h in hits:
        if _banned(str(h.get("path") or "")):
            banned_dropped += 1
            continue
        clean.append(h)
    qlow = query.lower().replace(" ", "-")
    def _boost(h: dict) -> tuple:
        path = str(h.get("path") or "")
        low = path.lower().replace("/", "\\")
        name = Path(path).name.lower()
        score = 0
        if "\\entities\\" in low:
            score += 100
        if name.startswith("entity-") and (qlow in name or query.lower() in name):
            score += 80
        elif name.startswith("entity-"):
            score += 40
        if name == "00-index.md":
            score -= 20
        return (-score, str(h.get("line") or 0))
    clean.sort(key=_boost)
    clean = clean[:max_hits]
    doc = {
        "ok": True,
        "query": query,
        "roots": [str(r) for r in roots],
        "engine": engine,
        "hit_count": len(clean),
        "hits": clean,
        "banned_dropped": banned_dropped,
        "ban_list": list(BAN_NEEDLES),
        "elapsed_ms": int((time.time() - started) * 1000),
    }
    doc["markdown"] = _render_markdown(doc)
    return doc


def _render_markdown(doc: Dict[str, Any]) -> str:
    if not doc.get("ok"):
        return f"Vault search failed: {doc.get('error') or 'unknown'}"
    q = doc.get("query") or ""
    n = int(doc.get("hit_count") or 0)
    engine = doc.get("engine") or "?"
    ms = doc.get("elapsed_ms") or 0
    dropped = int(doc.get("banned_dropped") or 0)
    lines = [
        f"**Vault search:** `{q}`",
        f"{n} hit(s) via {engine} in {ms} ms. Banned silos skipped ({dropped} dropped).",
        "",
    ]
    if not doc.get("hits"):
        lines.append("_No sourced hits. Navy / Medical / Patient-BLOOM / RP sandbox are excluded._")
        return "\n".join(lines)
    for i, h in enumerate(doc.get("hits") or [], 1):
        path = str(h.get("path") or "")
        name = Path(path).name
        ln = h.get("line") or 0
        snip = " ".join(str(h.get("snippet") or "").split())[:180]
        lines.append(f"{i}. **{name}**:{ln} — {snip}")
        lines.append(f"   `{path}`")
    return "\n".join(lines)


def main() -> int:
    payload = _parse_args()
    doc = run(payload)
    want_md = str(payload.get("format") or "").lower() in ("md", "markdown")
    if want_md:
        print(doc.get("markdown") or json.dumps(doc, ensure_ascii=False))
    else:
        print(json.dumps(doc, ensure_ascii=False))
    return 0 if doc.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
