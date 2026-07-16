#!/usr/bin/env python3
"""Convert WordPerfect (.wpd) → UTF-8 text via Microsoft Word COM.

LibreOffice MSI install was blocked (stuck msiexec / elevation). Word 16
successfully opens our WSWTR .wpd files — use that path instead.

Each file runs in a fresh Python subprocess with timeout so one hang
cannot freeze the whole batch.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WSWTR = Path(
    r"G:\Booksbloom\2025-01-03_Booksbloom3-HDD\Users\Admin\Documents\WSWTR"
)
OUT = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\Family\Jan-Bloom-Author\text_wpd"
)
LOG = Path(r"D:\PhronesisVault\Operations\logs\wpd-word-convert-latest.json")
WORKER = Path(__file__).resolve().parent / "_wpd_word_worker.py"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_worker() -> None:
    WORKER.write_text(
        r'''#!/usr/bin/env python3
"""One-shot Word COM convert: argv[1]=src.wpd argv[2]=dest.txt"""
import sys
from pathlib import Path

def main() -> int:
    src, dest = Path(sys.argv[1]), Path(sys.argv[2])
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(src), False, True, False)
        # Prefer SaveAs txt for cleaner newlines; also grab Content.Text
        text = doc.Content.Text or ""
        # Word uses \r for paragraph marks
        text = text.replace("\r\x07", "\n").replace("\r", "\n")
        dest.parent.mkdir(parents=True, exist_ok=True)
        header = f"SOURCE: {src}\nMETHOD: word_com_wpd\nCHARS: {len(text)}\n\n"
        dest.write_text(header + text, encoding="utf-8", errors="ignore")
        doc.Close(False)
        print(json_ok(len(text)))
        return 0
    except Exception as e:
        print(f"ERR {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass

def json_ok(n):
    import json
    return json.dumps({"ok": True, "chars": n})

if __name__ == "__main__":
    raise SystemExit(main())
''',
        encoding="utf-8",
    )


def kill_word() -> None:
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-Process WINWORD -ErrorAction SilentlyContinue | Stop-Process -Force",
        ],
        capture_output=True,
        timeout=30,
    )


def convert_one(src: Path, dest: Path, timeout: int) -> dict:
    ensure_worker()
    kill_word()
    t0 = time.time()
    try:
        r = subprocess.run(
            [sys.executable, str(WORKER), str(src), str(dest)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        ok = r.returncode == 0 and dest.exists() and dest.stat().st_size > 100
        chars = dest.stat().st_size if dest.exists() else 0
        if dest.exists():
            try:
                body = dest.read_text(encoding="utf-8", errors="ignore")
                # strip header
                if "\n\n" in body:
                    chars = len(body.split("\n\n", 1)[1])
            except Exception:
                pass
        return {
            "src": str(src),
            "dest": str(dest),
            "ok": ok,
            "chars": chars,
            "seconds": round(time.time() - t0, 1),
            "stderr": (r.stderr or "")[-300:],
            "stdout": (r.stdout or "")[-200:],
        }
    except subprocess.TimeoutExpired:
        kill_word()
        return {
            "src": str(src),
            "ok": False,
            "chars": 0,
            "seconds": timeout,
            "error": "timeout",
        }
    finally:
        kill_word()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=180, help="seconds per file")
    ap.add_argument("--limit", type=int, default=0, help="max files (0=all)")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(WSWTR.glob("*.wpd")) if WSWTR.exists() else []
    if args.limit:
        files = files[: args.limit]

    results = []
    total_chars = 0
    ok_n = 0
    for i, src in enumerate(files, 1):
        safe = re.sub(r"[^\w.\-]+", "_", src.stem)[:90]
        dest = OUT / f"{safe}.txt"
        # scale timeout by size
        size_mb = src.stat().st_size / 1_000_000
        to = max(args.timeout, int(60 + size_mb * 40))
        print(f"[{i}/{len(files)}] {src.name} ({size_mb:.1f}MB) timeout={to}s", flush=True)
        rec = convert_one(src, dest, timeout=to)
        results.append(rec)
        if rec.get("ok"):
            ok_n += 1
            total_chars += rec.get("chars") or 0
            print(f"  OK chars={rec.get('chars')} in {rec.get('seconds')}s", flush=True)
        else:
            print(f"  FAIL {rec}", flush=True)

    summary = {
        "at": utc(),
        "files": len(files),
        "ok": ok_n,
        "total_chars": total_chars,
        "out": str(OUT),
        "results": results,
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("files", "ok", "total_chars", "out")}, indent=2))
    return 0 if ok_n else 1


if __name__ == "__main__":
    raise SystemExit(main())
