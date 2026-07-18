#!/usr/bin/env python3
"""Convert WordPerfect .wpd → UTF-8 text via local libwpd wpd2text (no LibreOffice, no cloud).

Tooling lives under D:/HermesData/tools/libwpd/mingw64/bin (msys2 packages).
Deps: libwpd + librevenge DLLs; mingw runtime often from Git mingw64 PATH.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BIN_DIR = Path(r"D:\HermesData\tools\libwpd\mingw64\bin")
WPD2TEXT = BIN_DIR / "wpd2text.exe"
DEFAULT_ROOTS = [
    Path(
        r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\Projects\from-g-drive\Booksbloom\2025-01-03_Booksbloom3-HDD\Users\Admin\Documents"
    ),
]
OUT = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\Family\Jan-Bloom-Author\text_wpd"
)
GOLD = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\Projects\from-g-drive\Booksbloom\_gold_extracts"
)
LOG = Path(r"D:\HermesData\state\wpd2text_batch_results.json")
MINGW_FALLBACK = Path(r"C:\Program Files\Git\mingw64\bin")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_path() -> None:
    parts = [str(BIN_DIR)]
    if MINGW_FALLBACK.is_dir():
        parts.append(str(MINGW_FALLBACK))
    os.environ["PATH"] = os.pathsep.join(parts + [os.environ.get("PATH", "")])


def convert_one(src: Path) -> dict:
    ensure_path()
    if not WPD2TEXT.is_file():
        return {"src": str(src), "ok": False, "error": f"missing {WPD2TEXT}"}
    try:
        r = subprocess.run(
            [str(WPD2TEXT), str(src)],
            capture_output=True,
            timeout=max(120, int(60 + src.stat().st_size / 50_000)),
        )
    except subprocess.TimeoutExpired:
        return {"src": str(src), "ok": False, "error": "timeout"}
    text = (r.stdout or b"").decode("utf-8", errors="replace")
    if len(text.strip()) < 40:
        text = (r.stdout or b"").decode("latin-1", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    ok = r.returncode == 0 and len(text) > 40
    return {
        "src": str(src),
        "ok": ok,
        "chars": len(text),
        "rc": r.returncode,
        "stderr": (r.stderr or b"").decode("utf-8", errors="replace")[-300:],
        "text": text if ok else "",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Local wpd2text batch for Jan/BooksBloom")
    ap.add_argument("--root", action="append", default=[], help="Root to scan for .wpd")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-gold", action="store_true")
    args = ap.parse_args()

    if not WPD2TEXT.is_file():
        print(json.dumps({"ok": False, "error": f"install libwpd tools at {BIN_DIR}"}))
        return 2

    roots = [Path(r) for r in args.root] if args.root else DEFAULT_ROOTS
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        files.extend(
            p
            for p in root.rglob("*.wpd")
            if p.is_file() and not p.name.startswith("~$")
        )
    files = sorted(set(files), key=lambda p: p.stat().st_size, reverse=True)
    if args.limit:
        files = files[: args.limit]

    OUT.mkdir(parents=True, exist_ok=True)
    if not args.no_gold:
        GOLD.mkdir(parents=True, exist_ok=True)

    results = []
    total = 0
    ok_n = 0
    for i, src in enumerate(files, 1):
        rec = convert_one(src)
        safe = re.sub(r"[^\w.\-]+", "_", src.stem)[:90]
        dest = OUT / f"{safe}.txt"
        if rec.get("ok"):
            body = rec.pop("text")
            header = (
                f"SOURCE: {src}\nMETHOD: wpd2text_libwpd\nCHARS: {rec['chars']}\n"
                f"AT: {utc()}\n\n"
            )
            dest.write_text(header + body, encoding="utf-8", errors="replace")
            rec["dest"] = str(dest)
            if not args.no_gold and (
                rec["chars"] > 500 or "wswtr" in src.name.lower() or "keepers" in src.name.lower()
            ):
                gpath = GOLD / f"{safe}.wpd.md"
                gpath.write_text(
                    f"---\nsource: {src}\nmethod: wpd2text_libwpd\nchars: {rec['chars']}\n"
                    f"lane: booksbloom_gold\n---\n\n# {src.name}\n\nSOURCE: {src.name}\n\n"
                    + body[:500_000],
                    encoding="utf-8",
                    errors="replace",
                )
                rec["gold"] = str(gpath)
            ok_n += 1
            total += rec["chars"]
            print(f"[{i}/{len(files)}] OK {rec['chars']} {src.name}", flush=True)
        else:
            rec.pop("text", None)
            print(f"[{i}/{len(files)}] FAIL {src.name} {rec}", flush=True)
        results.append(rec)

    summary = {
        "at": utc(),
        "files": len(files),
        "ok": ok_n,
        "total_chars": total,
        "out": str(OUT),
        "tool": str(WPD2TEXT),
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(
        json.dumps({"summary": summary, "results": results}, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0 if ok_n else 1


if __name__ == "__main__":
    raise SystemExit(main())
