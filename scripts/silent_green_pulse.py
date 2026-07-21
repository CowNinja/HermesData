#!/usr/bin/env python3
"""Option C v1.2 silent-green pulse -- Discord only on YELLOW/RED.

Aggregates: orchestrator scoreboard + silo board + thrash levels.
Silent when all GREEN (exit 0). Alerts when not (exit 1) + optional Discord.

Usage:
  python silent_green_pulse.py
  python silent_green_pulse.py --discord
  python silent_green_pulse.py --force-post   # even when green
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

SCRIPTS = Path(r"D:\HermesData\scripts")
STATE = Path(r"D:\HermesData\state\silent_green_pulse.json")
MD = Path(r"D:\PhronesisVault\Operations\logs\silent-green-pulse-latest.md")
PY = sys.executable
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_json(script: str, extra: list[str] | None = None) -> dict:
    cmd = [PY, str(SCRIPTS / script)] + (extra or [])
    try:
        r = subprocess.run(
            cmd,
            cwd=str(SCRIPTS),
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        out = (r.stdout or "").strip()
        # find last JSON object
        i = out.find("{")
        if i < 0:
            return {"ok": False, "raw": out[:500], "rc": r.returncode}
        return json.loads(out[i:])
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def post_discord(content: str, channel: str) -> str:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    env = Path(r"D:\HermesData\.env")
    if not token and env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DISCORD_BOT_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"')
                break
    data = json.dumps({"content": content[:1900]}).encode()
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel}/messages",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "SilentGreen/1.2",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode()).get("id", "?")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discord", action="store_true")
    ap.add_argument("--force-post", action="store_true")
    ap.add_argument("--channel", default="1524846849360531456")
    args = ap.parse_args()

    sys.path.insert(0, str(SCRIPTS))
    from image_job_lock import status as ls
    import image_thrash_guard as tg
    import orchestrator_scoreboard as osc

    orch = osc.build()
    thr_h = tg.analyze("1524821864956956793")
    thr_g = tg.analyze("1525174401740312707")
    lock = ls()
    board = {}
    bp = Path(r"D:\HermesData\state\silo_rock_solid_board.json")
    if bp.is_file():
        try:
            board = json.loads(bp.read_text(encoding="utf-8"))
        except Exception:
            board = {}

    levels = [
        orch.get("health") or "YELLOW",
        thr_h.get("level") or "YELLOW",
        thr_g.get("level") or "YELLOW",
    ]
    if board.get("dual_bad"):
        levels.append("RED")
    if board.get("freeze"):
        levels.append("RED")
    if not (orch.get("sensors") or {}).get("continuous_live"):
        levels.append("YELLOW")

    rank = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    overall = "GREEN"
    for lv in levels:
        if rank.get(lv, 1) > rank[overall]:
            overall = lv

    silent = overall == "GREEN" and not args.force_post
    rep = {
        "at": utc(),
        "version": "1.2",
        "overall": overall,
        "silent": silent,
        "orch_health": orch.get("health"),
        "orch_score": orch.get("option_c_score_pct"),
        "continuous_live": (orch.get("sensors") or {}).get("continuous_live"),
        "dual_bad": board.get("dual_bad"),
        "ocr_open": (board.get("six") or {}).get("6_ocr_open"),
        "lock_held": bool(lock.get("held")),
        "thrash_harem": thr_h.get("level"),
        "thrash_group": thr_g.get("level"),
        "posted": False,
        "discord_id": None,
    }

    if args.discord and (not silent or args.force_post):
        msg = (
            f"**Silent-green pulse v1.2** overall=**{overall}**\n"
            f"orch={rep['orch_health']} score~{rep['orch_score']} "
            f"cont={rep['continuous_live']} dual_bad={rep['dual_bad']} "
            f"ocr_open={rep['ocr_open']} lock={rep['lock_held']}\n"
            f"thrash harem={rep['thrash_harem']} group={rep['thrash_group']}\n"
            f"{'SILENT skip (all green)' if silent else 'ALERT -- see orch-score / thrash_guard'}"
        )
        if not silent or args.force_post:
            try:
                rep["discord_id"] = post_discord(msg, args.channel)
                rep["posted"] = True
            except Exception as exc:
                rep["discord_error"] = str(exc)[:160]

    STATE.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    MD.parent.mkdir(parents=True, exist_ok=True)
    MD.write_text(
        f"# Silent green pulse - {rep['at']}\n\n"
        f"overall=**{overall}** silent={silent} posted={rep['posted']}\n\n"
        f"```json\n{json.dumps(rep, indent=2)[:2000]}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(rep, indent=2))
    return 0 if overall == "GREEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
