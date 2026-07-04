#!/usr/bin/env python3
"""Launch RP batch series scripts from OOC intent (bypasses per-image agent loop)."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SANDBOX = Path(r"D:\PhronesisVault\Roleplay-Sandbox\sandbox")
BATCH_SESSION = ROOT / "state" / "comfy-batch-session.json"
HAREM = SANDBOX / "batch-harem-series.py"
KITCHEN = SANDBOX / "batch-kitchen-crawl-series.py"
PY = ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe"
LOG = ROOT / "logs" / "rp-batch-orchestrator.log"


def _log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _active_batch() -> dict:
    if not BATCH_SESSION.is_file():
        return {}
    try:
        data = json.loads(BATCH_SESSION.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict) and data.get("active"):
            return data
    except Exception:
        pass
    return {}


def _pick_script(prompt: str, spec: dict) -> tuple[Path, list[str], str]:
    lower = (prompt or "").lower()
    if any(k in lower for k in ("harem girl", "harem girls", "per harem", "harem portrait")):
        return HAREM, [], "Harem portraits"
    chars = list(spec.get("characters") or [])
    if any(k in lower for k in ("crawl", "crawling", "hands and knees", "on all fours", "kitchen")):
        return KITCHEN, [], "Kitchen crawl"
    if len(chars) >= 2:
        return KITCHEN, [], "Kitchen crawl"
    if "portrait" in lower and any(
        name in lower for name in ("alice", "chloe", "becca", "emily", "sassy", "lyra", "zara")
    ):
        return HAREM, [], "Harem portraits"
    count = int(spec.get("batch_count") or 7)
    if count >= 5:
        return HAREM, [], "Harem portraits"
    return HAREM, [], "Harem portraits"


def _resume_args(script: Path) -> list[str]:
    if script != KITCHEN or not BATCH_SESSION.is_file():
        return []
    try:
        data = json.loads(BATCH_SESSION.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or data.get("series") != "Kitchen crawl":
            return []
        delivered = int(data.get("delivered_count") or 0)
        total = int(data.get("total") or 7)
        if delivered >= total:
            return []
        return ["--offset", str(delivered), "--limit", str(total - delivered)]
    except Exception:
        return []


def launch(prompt: str, spec: dict, *, dry_run: bool = False) -> dict:
    active = _active_batch()
    if active:
        return {
            "ok": True,
            "action": "already_running",
            "series": active.get("series"),
            "delivered_count": active.get("delivered_count"),
            "total": active.get("total"),
        }

    script, extra, label = _pick_script(prompt, spec)
    if not script.is_file():
        return {"ok": False, "error": "batch_script_missing", "script": str(script)}

    args = [str(PY), "-u", str(script)] + _resume_args(script) + extra
    if dry_run:
        return {"ok": True, "dry_run": True, "series": label, "cmd": args}

    _log(f"launch {label}: {' '.join(args)}")
    proc = subprocess.Popen(
        args,
        cwd=str(script.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return {
        "ok": True,
        "action": "launched",
        "series": label,
        "pid": proc.pid,
        "script": str(script),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", nargs="?", default="")
    parser.add_argument("--spec-json", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    spec: dict = {}
    if args.spec_json:
        try:
            spec = json.loads(args.spec_json)
        except json.JSONDecodeError:
            pass

    if not spec:
        sys.path.insert(0, str(SANDBOX / "lib"))
        from visual_registry import detect_image_intent  # noqa: WPS433

        spec = detect_image_intent(args.prompt, "", "") or {}

    count = int(spec.get("batch_count") or 0)
    if count < 2:
        m = re.search(r"\b(?:series|batch)\s+of\s+(\d+)", args.prompt or "", re.I)
        if m:
            count = int(m.group(1))
    if count < 2:
        print(json.dumps({"ok": False, "error": "batch_count_below_2", "spec": spec}))
        return 1

    result = launch(args.prompt, spec, dry_run=args.dry_run)
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())