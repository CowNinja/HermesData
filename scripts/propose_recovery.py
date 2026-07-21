#!/usr/bin/env python3
"""Propose recovery plays for Discord/Hermes issues (menu, not monologue).

Research (2026-07-18): SRE option menus / action-control; Draft→Approve→Execute;
silent-green + soft-fail; kill switch outside body. Never auto-executes.

Usage:
  python propose_recovery.py --symptom "gateway down"
  python propose_recovery.py --symptom "silo freeze" --json
  python propose_recovery.py --list-classes
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from atomic_io import atomic_write_json
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore

VAULT = Path(r"D:\PhronesisVault\Operations\logs")
RECEIPT = VAULT / "propose-recovery-latest.json"
SCRIPTS = Path(r"D:\HermesData\scripts")

# class_id -> patterns + ordered plays
PLAYBOOK: dict[str, dict] = {
    "gateway_down": {
        "patterns": [
            r"gateway.?down",
            r":?8642",
            r"hermes.?dead",
            r"no.?discord.?reply",
            r"health.?fail",
            r"connection.?refused.*8642",
        ],
        "title": "Gateway / Discord silence",
        "plays": [
            {
                "id": "A",
                "label": "Measure silent-green",
                "risk": "low",
                "cmd": r"python D:\HermesData\scripts\silent_green_pulse.py --json",
                "why": "Confirm single listener + 8091 before any restart",
            },
            {
                "id": "B",
                "label": "Single-instance soft check",
                "risk": "low",
                "cmd": r"python D:\HermesData\scripts\single_gateway_instance_check.py",
                "why": "Multi-listener advisory without kill",
            },
            {
                "id": "C",
                "label": "Restore via service VBS only",
                "risk": "medium",
                "cmd": r"wscript //B D:\HermesData\scripts\Start-Gateway-Service-Hidden.vbs & wscript //B D:\HermesData\scripts\Start-Gateway-MetaWatchdog-Hidden.vbs",
                "why": "Red-style sole starter; avoid dual Start-VenvGateway",
            },
        ],
        "do_not": [
            "taskkill gateway from Discord cook",
            "Start-VenvGateway + supervisor dual-start",
            "clear STOP files to force start",
        ],
        "recommend": "A",
    },
    "gateway_dual": {
        "patterns": [
            r"dual.?gateway",
            r"two.?gateway",
            r"multi.?listener",
            r"double.?boot",
            r"parent.?child",
            r"tree_ok",
            r"false.?positive.*gateway",
            r"gateway_run.?=.?2",
            r"two.?pythonw.*gateway",
        ],
        "title": "Dual gateway / multi-listener (tree-aware)",
        "plays": [
            {
                "id": "A",
                "label": "Tree-aware ensure (measure first)",
                "risk": "low",
                "cmd": r"python D:\HermesData\scripts\ensure_single_gateway.py",
                "why": "Parent+child re-exec = one instance; only true multi-LISTEN is dual",
            },
            {
                "id": "B",
                "label": "Soft single-instance receipt",
                "risk": "low",
                "cmd": r"python D:\HermesData\scripts\single_gateway_instance_check.py",
                "why": "LISTENING count on :8642 + health; advisory soft-fail",
            },
            {
                "id": "C",
                "label": "Stack snapshot board",
                "risk": "low",
                "cmd": r"python D:\HermesData\scripts\stack_snapshot.py",
                "why": "One board: ports, writers, green — no kill",
            },
        ],
        "do_not": [
            "blind taskkill all pythonw",
            "kill venv parent of healthy listener child",
            "start third supervisor",
            "gateway kill for silo stalls",
        ],
        "recommend": "A",
    },
    "silo_freeze": {
        "patterns": [
            r"silo.?freeze",
            r"land.?stuck",
            r"continuous.?dead",
            r"drain.?stale",
            r"k:?\s*drive",
            r"ingest.?stall",
        ],
        "title": "Silo land freeze / continuous",
        "plays": [
            {
                "id": "A",
                "label": "Six numbers only",
                "risk": "low",
                "cmd": r"python D:\HermesData\scripts\silo_discord_six_numbers.py",
                "why": "Truth metrics; never invent KPIs",
            },
            {
                "id": "B",
                "label": "Single-writer recovery",
                "risk": "medium",
                "cmd": r"python D:\HermesData\scripts\silo_recovery_single_writer.py",
                "why": "Kill dual continuous; restart one writer tree",
            },
            {
                "id": "C",
                "label": "Watch / wait",
                "risk": "low",
                "cmd": r"python D:\HermesData\scripts\silent_green_pulse.py --with-silo",
                "why": "If writers 1/1/1/1 and HB fresh, do not thrash",
            },
        ],
        "do_not": ["gateway kill for silo stall", "second continuous", "OCR thrash when ocr_open=0"],
        "recommend": "A",
    },
    "confabulation": {
        "patterns": [r"fake.?number", r"hallucin", r"confabul", r"invented.?kpi", r"wrong.?metric"],
        "title": "Confabulated metrics / facts",
        "plays": [
            {
                "id": "A",
                "label": "Re-run muscle script",
                "risk": "low",
                "cmd": r"python D:\HermesData\scripts\silo_discord_six_numbers.py",
                "why": "Replace fiction with tool output",
            },
            {
                "id": "B",
                "label": "Jan truth",
                "risk": "low",
                "cmd": r'python D:\HermesData\scripts\talk_to_jan.py "..."',
                "why": "Mom/writing facts only from RAG",
            },
            {
                "id": "C",
                "label": "Session /reset",
                "risk": "low",
                "cmd": "/reset in Discord",
                "why": "Clear poisoned session narrative",
            },
        ],
        "do_not": ["web_search for silo counts", "free-form scoreboard"],
        "recommend": "A",
    },
    "tts_fail": {
        "patterns": [r"tts", r"text.?to.?speech", r"no.?audio", r"voice.?fail", r"audio_not"],
        "title": "TTS / voice not working",
        "plays": [
            {
                "id": "A",
                "label": "Voice-truth after tools",
                "risk": "low",
                "cmd": r"python D:\HermesData\scripts\voice_truth_speak.py --from-tool six_numbers",
                "why": "Edge TTS only after tool evidence + MEDIA path",
            },
            {
                "id": "B",
                "label": "Jan TTS summary",
                "risk": "low",
                "cmd": r'python D:\HermesData\scripts\jan_tts_summary.py --question "..." --post-discord 1526594007092826316',
                "why": "talk_to_jan then Edge; no Grok TTS required",
            },
            {
                "id": "C",
                "label": "Dry-run text only",
                "risk": "low",
                "cmd": r"python D:\HermesData\scripts\voice_truth_speak.py --from-tool six_numbers --dry-run",
                "why": "Prove text path before audio claim",
            },
        ],
        "do_not": ["claim spoken without file", "enable paid TTS for routine"],
        "recommend": "A",
    },
    "context_model": {
        "patterns": [
            r"context.?window",
            r"65,?536",
            r"compact",
            r"wrong.?model",
            r"qwythos.*discord",
            r"compression",
        ],
        "title": "Context / model wrong",
        "plays": [
            {
                "id": "A",
                "label": "Discord /reset",
                "risk": "low",
                "cmd": "/reset",
                "why": "Drop session stuck at lowered 65K threshold",
            },
            {
                "id": "B",
                "label": "Confirm config",
                "risk": "low",
                "cmd": r"python -c \"import yaml;d=yaml.safe_load(open(r'D:\\HermesData\\config.yaml',encoding='utf-8'));print(d['model'], d['auxiliary']['compression'])\"",
                "why": "main+compression should be grok-4.5 / 500000",
            },
            {
                "id": "C",
                "label": "Soft reload gateway via service",
                "risk": "medium",
                "cmd": "service outer loop respawn only (meta/service VBS)",
                "why": "Pick up config; avoid dual-start",
            },
        ],
        "do_not": ["set compression to local 65K synthesis"],
        "recommend": "A",
    },
    "tool_thrash": {
        "patterns": [r"16/16", r"iteration.?budget", r"tool.?thrash", r"tool_slow", r"loop"],
        "title": "Tool thrash / iteration budget",
        "plays": [
            {
                "id": "A",
                "label": "Stop and summarize",
                "risk": "low",
                "cmd": "(no tools) 5-line status + next 3 turns only",
                "why": "Budget is a feature; don't burn more",
            },
            {
                "id": "B",
                "label": "Intent propose instead of freestyle",
                "risk": "low",
                "cmd": r'python D:\HermesData\scripts\conversation_intent_queue.py propose --text "..."',
                "why": "Park action as dry-run card",
            },
            {
                "id": "C",
                "label": "Stack snapshot once",
                "risk": "low",
                "cmd": r"python D:\HermesData\scripts\stack_snapshot.py",
                "why": "One measurement beat many tasklists",
            },
        ],
        "do_not": ["open-ended search_files storms", "raise max_turns on silo/Jan"],
        "recommend": "A",
    },
    "proxy_model": {
        "patterns": [r"8091", r"sovereign.?proxy", r"proxy.?health", r"model.?mgmt"],
        "title": "Sovereign proxy / local models",
        "plays": [
            {
                "id": "A",
                "label": "Silent green + 8091",
                "risk": "low",
                "cmd": r"python D:\HermesData\scripts\silent_green_pulse.py --json",
                "why": "Measure before restart",
            },
            {
                "id": "B",
                "label": "Proxy health",
                "risk": "low",
                "cmd": r"curl -s http://127.0.0.1:8091/health",
                "why": "GREEN/RED without process kill",
            },
            {
                "id": "C",
                "label": "Start proxy hidden (if down)",
                "risk": "medium",
                "cmd": r"powershell -File D:\HermesData\scripts\Start-Sovereign-Proxy-8091.ps1",
                "why": "Only if health down; one instance",
            },
        ],
        "do_not": ["fleet ON without arm", "dual proxy"],
        "recommend": "A",
    },
    "llama_8090_down": {
        "patterns": [
            r"8090",
            r"llama.?down",
            r"qwythos.?down",
            r"silent.?green.?yellow",
            r"requires_llama_8090",
        ],
        "title": "Qwythos llama-server :8090 down",
        "plays": [
            {
                "id": "A",
                "label": "Measure supervisor + silent-green",
                "risk": "low",
                "cmd": r"python D:\HermesData\scripts\stack_supervisor.py status --json && python D:\HermesData\scripts\silent_green_pulse.py --json",
                "why": "Confirm :8090 down + dual_tenant color before any start",
            },
            {
                "id": "B",
                "label": "Release image tenant then start Qwythos hidden",
                "risk": "medium",
                "cmd": r"python D:\HermesData\scripts\image_stack_single_tenant.py --active release && wscript //B D:\HermesData\scripts\start_qwythos_8090_hidden.vbs",
                "why": "12GB law: release Forge/Comfy weights before ngl=99 Qwythos",
            },
            {
                "id": "C",
                "label": "Router start (models-preset) if Jeff wants multi-model",
                "risk": "medium",
                "cmd": r"powershell -File D:\HermesData\scripts\Start-8090-Router.ps1",
                "why": "Alternate path via models-8090.ini; still needs free VRAM",
            },
        ],
        "do_not": [
            "start 8090 while Forge holds ~12GB without release",
            "taskkill gateway to free VRAM",
            "dual llama-server on 8090",
        ],
        "recommend": "A",
    },
    "dual_tenant": {
        "patterns": [
            r"dual.?tenant",
            r"forge.?and.?comfy",
            r"vram.?risk",
            r"co.?resident",
            r"single.?tenant",
            r"gpu.?tenant",
        ],
        "title": "Dual-tenant VRAM / single GPU guard",
        "plays": [
            {
                "id": "A",
                "label": "Supervisor dual_tenant_risk board",
                "risk": "low",
                "cmd": r"python D:\HermesData\scripts\stack_supervisor.py status --json",
                "why": "Emit dual_tenant_risk color + active tenant; no kill",
            },
            {
                "id": "B",
                "label": "Enforce Forge primary (free Comfy weights)",
                "risk": "low",
                "cmd": r"python D:\HermesData\scripts\image_stack_single_tenant.py --active forge --json",
                "why": "Daily default: Forge owns GPU; Comfy free_vram not stop unless asked",
            },
            {
                "id": "C",
                "label": "Hard stop idle Comfy (only if RED co-resident)",
                "risk": "medium",
                "cmd": r"python D:\HermesData\scripts\image_stack_single_tenant.py --active forge --stop-idle-comfy --json",
                "why": "Fail-closed when both LISTEN; Jeff-gated if a Comfy batch is live",
            },
        ],
        "do_not": [
            "silent Forge+Comfy co-resident drift",
            "start Comfy without explicit batch",
            "gateway kill for VRAM",
        ],
        "recommend": "A",
    },
    "generic": {
        "patterns": [r"."],
        "title": "Generic / unclear",
        "plays": [
            {
                "id": "A",
                "label": "Stack snapshot",
                "risk": "low",
                "cmd": r"python D:\HermesData\scripts\stack_snapshot.py",
                "why": "One board: ports, writers, green, intents",
            },
            {
                "id": "B",
                "label": "Propose intent (dry-run)",
                "risk": "low",
                "cmd": r'python D:\HermesData\scripts\conversation_intent_queue.py propose --text "..."',
                "why": "Capture desired action without free-form execute",
            },
            {
                "id": "C",
                "label": "Escalate judgment",
                "risk": "low",
                "cmd": r'python D:\HermesData\scripts\prepare_grok_escalation_brief.py --topic "..."',
                "why": "Hard architecture → Grok thread with facts",
            },
        ],
        "do_not": ["invent root cause", "gateway kill by default"],
        "recommend": "A",
    },
}


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def classify(symptom: str) -> str:
    s = symptom or ""
    for cid, meta in PLAYBOOK.items():
        if cid == "generic":
            continue
        for pat in meta["patterns"]:
            if re.search(pat, s, re.I):
                return cid
    return "generic"


def build_menu(symptom: str) -> dict:
    cid = classify(symptom)
    meta = PLAYBOOK[cid]
    rec = meta["recommend"]
    return {
        "ts": utc(),
        "symptom": symptom,
        "class": cid,
        "title": meta["title"],
        "options": meta["plays"],
        "recommend": rec,
        "recommend_reason": next(
            (p["why"] for p in meta["plays"] if p["id"] == rec), ""
        ),
        "do_not": meta["do_not"],
        "need_from_jeff": "only if HIGH risk or Admin schtask / purge / VW LIVE",
        "discord_format": (
            "Symptom (measured): …\n"
            "Options:\nA) …\nB) …\nC) …\n"
            f"Recommend: {rec} because …\n"
            "Need from Jeff: …"
        ),
        "seal": "propose-recovery-v1",
    }


def format_human(menu: dict) -> str:
    lines = [
        f"**Symptom class:** {menu['title']} (`{menu['class']}`)",
        f"**Input:** {menu['symptom'][:120]}",
        "",
        "Options:",
    ]
    for p in menu["options"]:
        lines.append(
            f"**{p['id']})** {p['label']}  · risk={p['risk']}\n"
            f"   cmd: `{p['cmd']}`\n"
            f"   why: {p['why']}"
        )
    lines.append(f"\n**Recommend:** {menu['recommend']} — {menu['recommend_reason']}")
    lines.append("**Do not:** " + "; ".join(menu["do_not"]))
    lines.append(f"**Need from Jeff:** {menu['need_from_jeff']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symptom", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list-classes", action="store_true")
    args = ap.parse_args()

    if args.list_classes:
        for k, v in PLAYBOOK.items():
            print(f"{k}: {v['title']}")
        return 0

    if not (args.symptom or "").strip():
        print("usage: propose_recovery.py --symptom \"...\"", file=sys.stderr)
        return 2

    menu = build_menu(args.symptom.strip())
    VAULT.mkdir(parents=True, exist_ok=True)
    if atomic_write_json is not None:
        atomic_write_json(RECEIPT, menu, min_bytes=20)
    else:
        RECEIPT.write_text(json.dumps(menu, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(menu, indent=2))
    else:
        print(format_human(menu))
        print(f"\nreceipt: {RECEIPT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
