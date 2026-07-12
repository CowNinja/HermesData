#!/usr/bin/env python3
"""Priority re-OCR wave: Navy/Medical PDFs first; skip portrait-like images.

Feeds silo_robust_ocr_ladder logic by calling process on selected files.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SILO = Path(r"K:/Phronesis-Sovereign/Personal-Digital-Silo")
LADDER = Path(r"D:/HermesData/scripts/silo_robust_ocr_ladder.py")
LOG = Path(r"D:/PhronesisVault/Operations/logs/silo-ocr-priority-wave-latest.md")

KEYWORDS = ("order", "orders", "eval", "les", "certificate", "dd214", "report", "ncdoc",
            "elrod", "enterprise", "sta-21", "boost", "nrotc", "accident", "cortisol",
            "oshanick", "nmcp", "vamc", "tricare", "reenlist", "separation")


def score(p: Path) -> int:
    s = 0
    low = str(p).lower()
    name = p.name.lower()
    if p.suffix.lower() == ".pdf":
        s += 50
    if "navy" in low or "medical" in low:
        s += 30
    if any(k in name for k in KEYWORDS):
        s += 40
    if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        s -= 20  # deprioritize photos unless keyword
        if any(k in name for k in KEYWORDS):
            s += 25
    # skip if good ocr already
    ocr = Path(str(p) + ".ocr.md")
    if ocr.is_file() and ocr.stat().st_size > 400:
        s -= 100
    if Path(str(p) + ".needs_ocr").is_file():
        s += 15  # retry flagged
    return s


def main() -> int:
    limit = 20
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            pass
    cands = []
    for root_name in ("Navy-Service", "Medical-Records", "Core-Personal"):
        root = SILO / root_name
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
                continue
            if p.name.endswith((".ocr.md", ".train.md")):
                continue
            sc = score(p)
            if sc >= 50:
                cands.append((sc, p))
    cands.sort(key=lambda x: -x[0])
    picked = [p for sc, p in cands[:limit]]
    # call ladder with explicit paths if supported; else run module process
    # Use subprocess per batch via ladder -- no path args: temporarily copy list into env file
    list_path = Path(r"D:/HermesData/state/ocr_priority_list.txt")
    list_path.write_text("\n".join(str(p) for p in picked), encoding="utf-8")

    # Inline process using import
    sys.path.insert(0, str(LADDER.parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location("ladder", LADDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    results = []
    for p in picked:
        try:
            results.append(mod.process_file(p, max_pages=8))
        except Exception as e:
            results.append({"path": str(p), "error": str(e)[:200], "status": "error"})

    ok = sum(1 for r in results if r.get("status") == "ok_text" or r.get("twin_useful"))
    need = sum(1 for r in results if r.get("status") == "needs_ocr" or r.get("needs_ocr"))
    twin = sum(1 for r in results if r.get("twin_useful"))
    lines = [
        f"# OCR priority wave",
        f"picked {len(picked)} · ok/twinish {ok} · needs_ocr {need} · twin_useful {twin}",
        "",
    ]
    for r in results:
        lines.append(f"- {r.get('status') or r.get('engine')} chars={r.get('chars')} `{Path(r.get('path','')).name}` {r.get('error','')}")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"picked": len(picked), "ok": ok, "needs_ocr": need, "twin_useful": twin, "top": [p.name for p in picked[:8]]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
