#!/usr/bin/env python3
"""Capped audio STT ladder for medical/navy recordings → twin text.

Order:
  1) faster-whisper / whisper if installed
  2) speech_recognition + local free engine if present
  3) flag needs_stt + metadata only

Never blocks drain. Default roots Medical-Records + Navy-Service.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
LOG = Path(r"D:\PhronesisVault\Operations\logs\silo-audio-stt-latest.md")

STT_PYTHON = Path("D:/HermesData/venvs/stt/Scripts/python.exe")
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".wma"}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def stt_whisper(path: Path) -> tuple[str, str]:
    """Prefer isolated STT venv (numpy pin) — research: Numba/whisper vs numpy 2.5 clash."""
    py = STT_PYTHON if STT_PYTHON.is_file() else Path(sys.executable)
    helper = r"""
import sys
from pathlib import Path
path = Path(sys.argv[1])
try:
    from faster_whisper import WhisperModel
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(path), beam_size=1)
    text = " ".join(s.text.strip() for s in segments)
    print(text)
    print("ENGINE:faster-whisper-base", file=sys.stderr)
except Exception as e:
    print("", end="")
    print("ENGINE:fail:"+str(e)[:200], file=sys.stderr)
    sys.exit(2)
"""
    try:
        r = subprocess.run(
            [str(py), "-c", helper, str(path)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        text = (r.stdout or "").strip()
        eng = "faster-whisper-venv"
        for line in (r.stderr or "").splitlines():
            if line.startswith("ENGINE:"):
                eng = line.split("ENGINE:", 1)[1]
        return text, eng
    except Exception as e:
        return "", f"whisper_fail:{e}"


def stt_speech_recognition(path: Path) -> tuple[str, str]:
    try:
        import speech_recognition as sr  # type: ignore

        r = sr.Recognizer()
        # convert via wav only for simplicity
        with sr.AudioFile(str(path)) as source:
            audio = r.record(source, duration=120)
        try:
            text = r.recognize_sphinx(audio)
            return text, "pocketsphinx"
        except Exception:
            return "", "sphinx_fail"
    except Exception as e:
        return "", f"sr_fail:{e}"


def process(path: Path) -> dict:
    text, engine = stt_whisper(path)
    if len(text.strip()) < 40:
        t2, e2 = stt_speech_recognition(path)
        if len(t2.strip()) > len(text.strip()):
            text, engine = t2, e2
    rec = {
        "path": str(path),
        "engine": engine,
        "chars": len(text.strip()),
        "twin_useful": len(text.strip()) >= 80,
        "at": utc(),
    }
    out = Path(str(path) + ".stt.md")
    out.write_text(
        f"# STT — {path.name}\n\n- engine: {engine}\n- chars: {rec['chars']}\n- at: {rec['at']}\n\n"
        f"```\n{text[:12000]}\n```\n",
        encoding="utf-8",
    )
    if rec["twin_useful"]:
        train = Path(str(path) + ".train.md")
        if not train.is_file() or train.stat().st_size < 50:
            train.write_text(
                f"# Train audio — {path.name}\n\n{text[:8000]}\n", encoding="utf-8"
            )
    if not rec["twin_useful"]:
        Path(str(path) + ".needs_stt").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    rec["text_preview"] = text[:200]
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument(
        "--roots",
        nargs="*",
        default=[str(SILO / "Medical-Records"), str(SILO / "Navy-Service")],
    )
    args = ap.parse_args()

    files = []
    for root in args.roots:
        r = Path(root)
        if not r.is_dir():
            continue
        for p in r.rglob("*"):
            if p.is_file() and p.suffix.lower() in AUDIO_EXT:
                if Path(str(p) + ".stt.md").is_file():
                    continue
                files.append(p)
                if len(files) >= args.limit * 2:
                    break
    files = files[: args.limit]

    results = []
    for p in files:
        try:
            results.append(process(p))
        except Exception as e:
            results.append({"path": str(p), "error": str(e)[:200]})

    useful = sum(1 for r in results if r.get("twin_useful"))
    LOG.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Audio STT — {utc()}",
        "",
        f"processed **{len(results)}** · twin_useful **{useful}**",
        "",
    ]
    for r in results:
        lines.append(
            f"- `{Path(r.get('path','')).name}` eng={r.get('engine')} chars={r.get('chars')} {r.get('error','')}"
        )
    LOG.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {"processed": len(results), "twin_useful": useful, "results": results},
            indent=2,
        )[:2000]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
