#!/usr/bin/env python3
"""OCR priority wave — gold PDFs first via robust ladder process_one API.

Picks highest-gold Medical/Navy PDFs missing useful .ocr.md/.train.md and
runs silo_robust_ocr_ladder.process_one (NOT a fictional process_file).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
LADDER = Path(r"D:\HermesData\scripts\silo_robust_ocr_ladder.py")
LOG = Path(r"D:\PhronesisVault\Operations\logs\silo-ocr-priority-wave-latest.md")
SCRIPTS = Path(r"D:\HermesData\scripts")

try:
    sys.path.insert(0, str(SCRIPTS))
    from silo_relevance_heuristics import gold_score
except Exception:

    def gold_score(path):  # type: ignore
        low = str(path).lower()
        return 80 if any(k in low for k in ("medical", "navy", "nmcp", "vamc")) else 20


def pick_gold_pdfs(limit: int) -> list[Path]:
    roots = [
        SILO / "Medical-Records",
        SILO / "Navy-Service",
        SILO / "Core-Personal",
    ]
    scored: list[tuple[int, Path]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*.pdf"):
            if not p.is_file():
                continue
            ocr = Path(str(p) + ".ocr.md")
            train = Path(str(p) + ".train.md")
            if train.is_file() and train.stat().st_size >= 200:
                continue
            if ocr.is_file() and ocr.stat().st_size >= 800:
                continue
            g = int(gold_score(p) or 0)
            low = str(p).lower()
            if any(k in low for k in ("medical", "navy", "nmcp", "vamc", "cnsva", "tricare")):
                g += 25
            if g >= 40:
                scored.append((g, p))
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:limit]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=8)
    args = ap.parse_args()

    picked = pick_gold_pdfs(args.limit)
    if not picked:
        print(json.dumps({"picked": 0, "ok": 0, "msg": "no_gold_pdfs"}))
        return 0

    list_path = Path(r"D:/HermesData/state/ocr_priority_list.txt")
    list_path.parent.mkdir(parents=True, exist_ok=True)
    list_path.write_text("\n".join(str(p) for p in picked), encoding="utf-8")

    spec = importlib.util.spec_from_file_location("ladder", LADDER)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    tess = mod.tesseract_bin()
    results = []
    for p in picked:
        try:
            rec = mod.process_one(p, tess, True, 8)
            q = rec.get("quality") or {}
            if isinstance(q, str):
                try:
                    q = json.loads(q.replace("'", '"'))
                except Exception:
                    q = {}
            status = q.get("status") or rec.get("status") or "unknown"
            chars = q.get("chars") or rec.get("chars") or 0
            twin_u = bool(
                q.get("twin_useful")
                or rec.get("twin_useful")
                or (int(chars or 0) >= 80)
            )
            results.append(
                {
                    "path": str(p),
                    "status": status,
                    "chars": chars,
                    "engine": rec.get("engine"),
                    "twin_useful": twin_u,
                }
            )
        except Exception as e:
            results.append({"path": str(p), "error": str(e)[:200], "status": "error"})

    ok = sum(1 for r in results if r.get("status") == "ok_text" or r.get("twin_useful"))
    need = sum(1 for r in results if r.get("status") == "needs_ocr" or r.get("needs_ocr"))
    twin = sum(1 for r in results if r.get("twin_useful"))
    lines = [
        "# OCR priority wave",
        f"picked {len(picked)} · ok/twinish {ok} · needs_ocr {need} · twin_useful {twin}",
        "",
    ]
    for r in results:
        lines.append(
            f"- {r.get('status') or r.get('engine')} chars={r.get('chars')} "
            f"`{Path(r.get('path','')).name}` {r.get('error','')}"
        )
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "picked": len(picked),
                "ok": ok,
                "needs_ocr": need,
                "twin_useful": twin,
                "top": [p.name for p in picked[:8]],
                "results": [
                    {
                        "name": Path(r.get("path", "")).name,
                        "status": r.get("status"),
                        "chars": r.get("chars"),
                        "error": r.get("error"),
                    }
                    for r in results[:12]
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
