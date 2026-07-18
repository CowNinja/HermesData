#!/usr/bin/env python3
"""Local-first Edge TTS (no Grok, no paid TTS keys).

Uses Microsoft Edge neural voices via the free edge-tts client.
Writes MP3 under D:/HermesData/audio_cache and prints MEDIA path JSON.

Usage:
  python local_edge_tts.py --text "Hello from the vault."
  python local_edge_tts.py --file summary.md --out D:/HermesData/audio_cache/foo.mp3
  type summary.md | python local_edge_tts.py --stdin --slug jan-walk
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CACHE = Path(r"D:\HermesData\audio_cache")
DEFAULT_VOICE = "en-US-AriaNeural"
# Calm librarian-ish alternate: en-US-JennyNeural
MAX_CHARS = 4500  # edge chunk comfort; we split longer


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", (s or "tts").strip())[:48].strip("-")
    return s or "tts"


def _strip_md(text: str) -> str:
    """Light markdown strip for spoken delivery."""
    t = text.replace("\r\n", "\n")
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"[*_~]{1,3}", "", t)
    t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.M)
    t = re.sub(r"^\s*\d+\.\s+", "", t, flags=re.M)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _chunks(text: str, n: int = MAX_CHARS) -> list[str]:
    text = text.strip()
    if len(text) <= n:
        return [text]
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for para in re.split(r"\n\s*\n", text):
        p = para.strip()
        if not p:
            continue
        if size + len(p) + 2 > n and buf:
            parts.append("\n\n".join(buf))
            buf, size = [p], len(p)
        else:
            buf.append(p)
            size += len(p) + 2
    if buf:
        parts.append("\n\n".join(buf))
    # hard split any remaining giants
    out: list[str] = []
    for p in parts:
        if len(p) <= n:
            out.append(p)
            continue
        for i in range(0, len(p), n):
            out.append(p[i : i + n])
    return out or [text[:n]]


async def _synth(text: str, voice: str, out: Path) -> None:
    import edge_tts

    chunks = _chunks(text)
    if len(chunks) == 1:
        await edge_tts.Communicate(chunks[0], voice).save(str(out))
        return
    # concatenate mp3 frames (edge mp3s concat cleanly enough for speech)
    raw = bytearray()
    for i, ch in enumerate(chunks):
        tmp = out.with_suffix(f".part{i}.mp3")
        await edge_tts.Communicate(ch, voice).save(str(tmp))
        raw.extend(tmp.read_bytes())
        tmp.unlink(missing_ok=True)
    out.write_bytes(raw)


def synthesize(
    text: str,
    *,
    voice: str = DEFAULT_VOICE,
    out: Path | None = None,
    slug: str = "tts",
) -> dict:
    spoken = _strip_md(text)
    if not spoken:
        return {"ok": False, "error": "empty_text"}
    CACHE.mkdir(parents=True, exist_ok=True)
    if out is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = CACHE / f"{_slug(slug)}_{ts}.mp3"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(_synth(spoken, voice, out))
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if not out.exists() or out.stat().st_size < 200:
        return {"ok": False, "error": "empty_or_tiny_mp3", "path": str(out)}
    return {
        "ok": True,
        "path": str(out.resolve()),
        "media_tag": f"MEDIA:{out.resolve()}",
        "bytes": out.stat().st_size,
        "voice": voice,
        "chars": len(spoken),
        "provider": "edge-tts",
        "grok_tokens": 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Local Edge TTS (no Grok)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--text", type=str)
    g.add_argument("--file", type=Path)
    g.add_argument("--stdin", action="store_true")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--slug", default="tts")
    args = ap.parse_args()
    if args.text is not None:
        text = args.text
    elif args.file is not None:
        text = args.file.read_text(encoding="utf-8", errors="ignore")
    else:
        text = sys.stdin.read()
    res = synthesize(text, voice=args.voice, out=args.out, slug=args.slug)
    print(json.dumps(res, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
