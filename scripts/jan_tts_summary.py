#!/usr/bin/env python3
"""Jan library TTS summary — local muscle path, zero Grok tokens.

Pipeline:
  1) talk_to_jan.py  → retrieve + local Qwythos (8091) answer  [no Grok]
  2) local_edge_tts.py → Edge neural MP3                     [no Grok]
  3) optional Discord file attach via bot token              [no Grok]

Usage:
  python jan_tts_summary.py --question "Walk me through living books insights"
  python jan_tts_summary.py --question "..." --post-discord 1526594007092826316
  python jan_tts_summary.py --text-file notes.md --slug custom --post-discord CHANNEL
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\HermesData")
SCRIPTS = ROOT / "scripts"
ENV_FILE = ROOT / ".env"
CACHE = ROOT / "audio_cache"
LOG = Path(r"D:\PhronesisVault\Operations\logs\jan-tts-last.json")
API = "https://discord.com/api/v10"
JAN_THREAD_DEFAULT = "1526594007092826316"


def _token() -> str:
    if os.getenv("DISCORD_BOT_TOKEN"):
        return os.getenv("DISCORD_BOT_TOKEN", "").strip()
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("DISCORD_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no DISCORD_BOT_TOKEN")


def _run_talk_to_jan(question: str) -> str:
    cmd = [sys.executable, str(SCRIPTS / "talk_to_jan.py"), question]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "").strip()
    if p.returncode != 0 and not out:
        raise SystemExit(f"talk_to_jan failed rc={p.returncode}: {(p.stderr or '')[:500]}")
    return out


def _extract_spoken(answer: str, max_chars: int = 3200) -> str:
    """Prefer the narrative body; drop huge path dumps for speech."""
    lines = []
    for line in answer.splitlines():
        if re.search(r"[A-Za-z]:\\", line) and len(line) > 80:
            continue
        if line.strip().startswith("SOURCE:") or line.strip().startswith("LANE:"):
            continue
        lines.append(line)
    body = "\n".join(lines).strip()
    # Soft cap for a ~3–4 min listen
    if len(body) > max_chars:
        cut = body[:max_chars]
        # end on sentence if possible
        m = re.search(r"[\.!?]\s+[^\.]*$", cut)
        if m:
            cut = cut[: m.start() + 1]
        body = cut.strip() + "\n\nEnd of spoken pass. Full text stays in the Jan thread."
    intro = (
        "Hermes librarian voice. A short walk through Jan Bloom's real writing "
        "on living books, home libraries, and BooksBloom.\n\n"
    )
    return intro + body


def _tts(text: str, slug: str, voice: str) -> dict:
    sys.path.insert(0, str(SCRIPTS))
    from local_edge_tts import synthesize  # noqa: WPS433

    return synthesize(text, voice=voice, slug=slug)


def _post_discord(channel_id: str, content: str, mp3: Path) -> dict:
    """Multipart message + file (no external deps)."""
    boundary = f"----HermesTTS{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    filename = mp3.name
    file_bytes = mp3.read_bytes()
    payload = {
        "content": content[:1800],
    }
    body = bytearray()

    def add_field(name: str, value: str) -> None:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    add_field("payload_json", json.dumps(payload))
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        f'Content-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'.encode()
    )
    ctype = mimetypes.guess_type(filename)[0] or "audio/mpeg"
    body.extend(f"Content-Type: {ctype}\r\n\r\n".encode())
    body.extend(file_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        f"{API}/channels/{channel_id}/messages",
        data=bytes(body),
        method="POST",
        headers={
            "Authorization": f"Bot {_token()}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "PhronesisLocalTTS/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"discord_post_failed {e.code}: {err[:800]}") from e
    return {"ok": True, "id": data.get("id"), "channel_id": channel_id}


def main() -> int:
    ap = argparse.ArgumentParser(description="Jan TTS summary — no Grok")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--question", type=str, help="Ask talk_to_jan then speak")
    g.add_argument("--text-file", type=Path, help="Speak an existing markdown/text file")
    g.add_argument("--text", type=str, help="Speak raw text")
    ap.add_argument("--voice", default="en-US-AriaNeural")
    ap.add_argument("--slug", default="jan-tts")
    ap.add_argument(
        "--post-discord",
        nargs="?",
        const=JAN_THREAD_DEFAULT,
        default=None,
        help=f"Post MP3 to Discord channel/thread (default {JAN_THREAD_DEFAULT})",
    )
    ap.add_argument("--no-intro", action="store_true")
    args = ap.parse_args()

    if args.question:
        raw = _run_talk_to_jan(args.question)
        spoken = _extract_spoken(raw)
        if args.no_intro:
            spoken = raw
        source = "talk_to_jan"
    elif args.text_file:
        spoken = args.text_file.read_text(encoding="utf-8", errors="ignore")
        source = str(args.text_file)
    else:
        spoken = args.text or ""
        source = "raw"

    tts = _tts(spoken, args.slug, args.voice)
    if not tts.get("ok"):
        print(json.dumps(tts, indent=2))
        return 1

    result = {
        "ok": True,
        "source": source,
        "tts": tts,
        "spoken_chars": len(spoken),
        "grok_tokens": 0,
        "pipeline": ["talk_to_jan|text", "edge-tts", "optional_discord"],
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    if args.post_discord:
        caption = (
            "**Local TTS** (edge · no Grok) — Jan / BooksBloom spoken pass.\n"
            f"File: `{Path(tts['path']).name}` · {tts.get('bytes', 0)} bytes · voice `{args.voice}`"
        )
        post = _post_discord(str(args.post_discord), caption, Path(tts["path"]))
        result["discord"] = post

    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(result, indent=2), encoding="utf-8")
    # also keep a text sidecar next to mp3 for replay
    side = Path(tts["path"]).with_suffix(".txt")
    side.write_text(spoken, encoding="utf-8")
    result["text_sidecar"] = str(side)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
