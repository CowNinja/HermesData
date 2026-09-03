#!/usr/bin/env python3
"""Morning briefing for Jeff. Overnight wrap + 06:00-07:00 ET.

  python D:\\HermesData\\scripts\\ops\\morning_pulse.py
  python D:\\HermesData\\scripts\\ops\\morning_pulse.py --no-discord
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERMES = Path(r"D:\HermesData")
OPS = HERMES / "scripts" / "ops"
STATE = HERMES / "state"
SCRIPTS = HERMES / "scripts"
OUT_MD = Path(r"D:\PhronesisVault\Operations\MORNING_PULSE.md")
STAMP = STATE / "morning_pulse_latest.json"
PREV = STATE / "morning_pulse_prev.json"
KG = STATE / "life_rag" / "kg.jsonl"
ROSTER = STATE / "mma_free_roster.json"
SMOKE = STATE / "free_toolcall_smoke_latest.json"
INTAKE = STATE / "model_intake_queue.json"
SUP_LOG = HERMES / "logs" / "supervisor.log"
HERMES_CHAN = "1513273692778528990"  # #hermes
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def et_now() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=4)


def probe(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def kg_n() -> int:
    if not KG.is_file():
        return 0
    n = 0
    with KG.open(encoding="utf-8", errors="replace") as fh:
        for _ in fh:
            n += 1
    return n


def supervisor_restarts() -> int:
    if not SUP_LOG.is_file():
        return 0
    try:
        text = SUP_LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return text.count(" RESTART ") + text.count("BOOT_START ")


def compile_pulse() -> dict:
    prev = {}
    if PREV.is_file():
        try:
            prev = json.loads(PREV.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = {}
    kg = kg_n()
    kg0 = int(prev.get("kg_triples") or kg)
    cfree = shutil.disk_usage("C:\\").free / (1024**3)
    roster = {}
    if ROSTER.is_file():
        try:
            roster = json.loads(ROSTER.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            roster = {}
    smoke = {}
    if SMOKE.is_file():
        try:
            smoke = json.loads(SMOKE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            smoke = {}
    top_free = None
    if smoke.get("ranked_ids"):
        top_free = smoke["ranked_ids"][0]
    elif roster.get("healthy_provider_ids"):
        top_free = roster["healthy_provider_ids"][0]
    core = {"8642": probe(8642), "8091": probe(8091), "8090": probe(8090)}
    intake = {}
    if INTAKE.is_file():
        try:
            intake = json.loads(INTAKE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            intake = {}
    items = list(intake.get("items") or [])
    new_q = [
        it
        for it in items
        if str(it.get("status") or "") == "queued"
        and str(it.get("queued_ts") or "") >= str(prev.get("ts") or "")
    ]
    doc = {
        "ts": utc(),
        "et": et_now().strftime("%Y-%m-%d %H:%M ET"),
        "kg_triples": kg,
        "kg_delta": kg - kg0,
        "c_free_gb": round(cfree, 2),
        "c_watch": "C_FREE_LOW" if cfree < 40 else "ok",
        "top_free": top_free,
        "core": core,
        "core_green": all(core.values()),
        "supervisor_restarts": supervisor_restarts(),
        "new_candidates": [
            {
                "name": it.get("name"),
                "tier": it.get("tier"),
                "size_gb": it.get("size_gb"),
                "kind": it.get("kind"),
            }
            for it in new_q[:12]
        ],
        "new_candidate_n": len(new_q),
    }
    return doc


def render(doc: dict) -> str:
    core = doc.get("core") or {}
    bits = " ".join(f":{p}={'UP' if core.get(p) else 'DOWN'}" for p in ("8642", "8091", "8090"))
    lines = [
        "# Morning pulse",
        "",
        f"stamped={doc.get('ts')}  {doc.get('et')}",
        "",
        f"- CORE {bits}  green={doc.get('core_green')}",
        f"- Supervisor restarts (log): {doc.get('supervisor_restarts')}",
        f"- KG triples: {doc.get('kg_triples')}  overnight Δ {doc.get('kg_delta'):+d}",
        f"- C: free {doc.get('c_free_gb')} GB  ({doc.get('c_watch')})",
        f"- Tier-2 free top: `{doc.get('top_free') or 'n/a'}`",
        f"- New model candidates queued: {doc.get('new_candidate_n')}",
    ]
    for it in doc.get("new_candidates") or []:
        lines.append(
            f"  - {it.get('name')}  tier={it.get('tier') or '—'}  {it.get('size_gb') or ''}  {it.get('kind')}"
        )
    lines += [
        "",
        "Kitchen GREEN unless you name a heal. Never SAT --heal on this card.",
        "Weights only on D:\\PhronesisModels. Do not ollama pull.",
        "",
    ]
    return "\n".join(lines)


def discord_card(doc: dict) -> str:
    core = doc.get("core") or {}
    flag = "GREEN" if doc.get("core_green") else "CHECK PORTS"
    return (
        f"Morning pulse {flag}\n"
        f"CORE gw={'UP' if core.get('8642') else 'DOWN'} "
        f"proxy={'UP' if core.get('8091') else 'DOWN'} "
        f"brain={'UP' if core.get('8090') else 'DOWN'}\n"
        f"KG {doc.get('kg_triples')} (Δ{doc.get('kg_delta'):+d}) · "
        f"C: {doc.get('c_free_gb')} GB · "
        f"free `{doc.get('top_free') or 'n/a'}` · "
        f"queued {doc.get('new_candidate_n')} · "
        f"supervisor restarts {doc.get('supervisor_restarts')}"
    )


def post_discord(text: str) -> None:
    pending = HERMES / "pending_messages"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / f"morning-pulse-{int(datetime.now(timezone.utc).timestamp())}.txt").write_text(
        text, encoding="utf-8"
    )
    post = SCRIPTS / "ops_discord_post.py"
    py = sys.executable
    if not post.is_file():
        return
    try:
        subprocess.run(
            [py, str(post), "--channel", HERMES_CHAN, "--text", text[:1800]],
            capture_output=True,
            timeout=25,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def main() -> int:
    no_disc = "--no-discord" in sys.argv
    doc = compile_pulse()
    md = render(doc)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(md, encoding="utf-8")
    STAMP.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    PREV.write_text(json.dumps({"ts": doc["ts"], "kg_triples": doc["kg_triples"]}, indent=2), encoding="utf-8")
    if not no_disc:
        post_discord(discord_card(doc))
    print(md)
    print("WROTE", OUT_MD)
    return 0 if doc.get("core_green") else 1


if __name__ == "__main__":
    raise SystemExit(main())
