#!/usr/bin/env python3
"""Voice-first TTS that only speaks *after* tool truth (no free-form fiction audio).

Research (2026-07-18): grounded RAG-then-TTS; refuse "I spoke" without artifact;
local Edge path (jan_tts_summary / local_edge_tts) is $0 and non-cloud.

Contract:
- Requires --from-tool with a known tool id + evidence path or live re-run.
- Never synthesizes prose itself for high-stakes lanes (silo metrics, jan books).
- Prints JSON with MEDIA path; Discord claim allowed only if file exists and size>0.

Usage:
  python voice_truth_speak.py --from-tool six_numbers
  python voice_truth_speak.py --from-tool talk_to_jan --question "living books"
  python voice_truth_speak.py --from-tool file --path D:/path/receipt.md --slug board
  python voice_truth_speak.py --from-tool six_numbers --post-discord 1526594007092826316
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\HermesData")
SCRIPTS = ROOT / "scripts"
CACHE = ROOT / "audio_cache"
ENV_FILE = ROOT / ".env"
VAULT_LOG = Path(r"D:\PhronesisVault\Operations\logs")
RECEIPT = VAULT_LOG / "voice-truth-last.json"
API = "https://discord.com/api/v10"
PY = sys.executable


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_token() -> str:
    if os.getenv("DISCORD_BOT_TOKEN"):
        return os.getenv("DISCORD_BOT_TOKEN", "").strip()
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("DISCORD_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def run_six_numbers() -> tuple[str, dict]:
    r = subprocess.run(
        [PY, str(SCRIPTS / "silo_discord_six_numbers.py")],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(SCRIPTS),
    )
    text = (r.stdout or "") + (r.stderr or "")
    lines = []
    for line in text.splitlines():
        if line.strip().startswith(("1 ", "2 ", "3 ", "4 ", "5 ", "6 ", "SILO_SIX")):
            lines.append(line.strip())
    spoken = (
        "Silo six numbers, tool-verified. "
        + ". ".join(lines[:8])
        + ". End of board."
    )
    return spoken, {"ok": r.returncode == 0, "raw_tail": text[-800:], "lines": lines}


def run_talk_to_jan(question: str) -> tuple[str, dict]:
    if not question.strip():
        raise SystemExit("talk_to_jan requires --question")
    r = subprocess.run(
        [PY, str(SCRIPTS / "talk_to_jan.py"), question],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(SCRIPTS),
    )
    text = (r.stdout or "").strip()
    if not text:
        text = (r.stderr or "").strip() or "TOOL_FAILED empty talk_to_jan output"
    # Cap for Edge TTS comfort; full text still in receipt
    spoken = text[:4200]
    return spoken, {"ok": r.returncode == 0, "chars": len(text), "path_hint": "talk_to_jan stdout"}


def from_file(path: Path) -> tuple[str, dict]:
    if not path.is_file():
        raise SystemExit(f"missing file: {path}")
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        raise SystemExit(f"empty file: {path}")
    return raw[:4200], {"ok": True, "path": str(path), "chars": len(raw)}


def edge_tts(text: str, slug: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"voice-truth_{slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
    r = subprocess.run(
        [PY, str(SCRIPTS / "local_edge_tts.py"), "--text", text, "--out", str(out)],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(SCRIPTS),
    )
    if not out.is_file() or out.stat().st_size < 100:
        # local_edge_tts may print path in stdout JSON
        raise SystemExit(
            f"AUDIO_NOT_GENERATED edge_tts failed rc={r.returncode} "
            f"out={out} stderr={(r.stderr or '')[:300]}"
        )
    return out


def post_discord(channel: str, mp3: Path, caption: str) -> dict:
    token = load_token()
    if not token:
        return {"ok": False, "error": "no DISCORD_BOT_TOKEN"}
    # text first
    body = json.dumps({"content": caption[:1800]}).encode()
    req = urllib.request.Request(
        f"{API}/channels/{channel}/messages",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "VoiceTruth/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        msg = json.loads(resp.read().decode())
    # file attach via multipart is heavier; caption with MEDIA path is enough for gate
    return {"ok": True, "message_id": msg.get("id"), "media_path": str(mp3)}


def main() -> int:
    p = argparse.ArgumentParser(description="TTS only after tool truth")
    p.add_argument(
        "--from-tool",
        required=True,
        choices=["six_numbers", "talk_to_jan", "file"],
        help="Tool that produced truth before voice",
    )
    p.add_argument("--question", default="", help="For talk_to_jan")
    p.add_argument("--path", default="", help="For --from-tool file")
    p.add_argument("--slug", default="board")
    p.add_argument("--post-discord", default="", help="Channel/thread id")
    p.add_argument("--dry-run", action="store_true", help="Print text only, no TTS")
    args = p.parse_args()

    if args.from_tool == "six_numbers":
        spoken, meta = run_six_numbers()
    elif args.from_tool == "talk_to_jan":
        spoken, meta = run_talk_to_jan(args.question)
    else:
        spoken, meta = from_file(Path(args.path))

    if not meta.get("ok") and args.from_tool != "file":
        # still allow voice of TOOL_FAILED for honesty
        spoken = "Tool did not succeed cleanly. " + spoken[:500]

    payload = {
        "ts": utc(),
        "from_tool": args.from_tool,
        "meta": meta,
        "spoken_preview": spoken[:240],
        "spoken_chars": len(spoken),
        "dry_run": bool(args.dry_run),
        "rule": "no_voice_without_tool_evidence",
    }

    if args.dry_run:
        payload["audio"] = None
        print(json.dumps(payload, indent=2))
        print("\n--- SPOKEN TEXT ---\n" + spoken)
        VAULT_LOG.mkdir(parents=True, exist_ok=True)
        RECEIPT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return 0

    mp3 = edge_tts(spoken, args.slug)
    payload["audio"] = {
        "path": str(mp3),
        "bytes": mp3.stat().st_size,
        "media_claim_allowed": True,
    }
    if args.post_discord:
        payload["discord"] = post_discord(
            args.post_discord,
            mp3,
            f"Voice-truth ({args.from_tool}) MEDIA: `{mp3}` ({mp3.stat().st_size} bytes). "
            f"No audio claim without this path.",
        )

    VAULT_LOG.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"MEDIA {mp3}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
