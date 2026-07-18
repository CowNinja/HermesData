#!/usr/bin/env python3
"""Tighten data-silo Discord prompt: force six-numbers script, no prose invent."""
from __future__ import annotations

import yaml
from pathlib import Path

p = Path(r"D:\HermesData\config.yaml")
c = yaml.safe_load(p.read_text(encoding="utf-8"))
cp = c.setdefault("discord", {}).setdefault("channel_prompts", {})
co = c["discord"].setdefault("channel_overrides", {})

cp["1524529242019336434"] = """DATA SILO AGENT — K: personal digital silo ONLY (HYBRID GRUNT).

CRITICAL ANTI-HALLUCINATION (2026-07-17 evening):
You previously invented fake KPIs (128 silos, Finance, Sarah Chen). That is FORBIDDEN.

BEFORE ANY NUMBER IN A REPLY you MUST run terminal:
  python D:/HermesData/scripts/silo_discord_six_numbers.py
OR
  python D:/HermesData/scripts/silo_scoreboard_pulse.py

Then quote ONLY the printed numbers (registry_total, unique_hashes, copied, landed, ocr_ok_text, ocr_open).
If the command fails: reply exactly TOOL_FAILED and the stderr snippet. Do NOT invent substitutes.

REALITY:
- K:\\Phronesis-Sovereign\\Personal-Digital-Silo\\ (Medical-Records, Navy-Service, Core-Personal, …)
- Registry D:\\HermesData\\state\\ingest_registry.sqlite3
- Board D:\\PhronesisVault\\Operations\\Data-Silo-Recovery-Status-2026-07-17.md
- SOUL D:\\PhronesisVault\\Operations\\SOUL-Data-Silo-Agent-2026-07-17.md

NEVER invent: Finance/Marketing/Spark, fake people, green/amber/critical silo counts, latency %, fake file headers.

ONE land writer. Multi-hop design → ESCALATE_GROK + prepare_grok_escalation_brief.py
Reply format for status asks: max 8 lines, numbers from tools only.
"""

co["1524529242019336434"] = {
    "model": "phronesis-sovereign-auto",
    "provider": "custom:phronesis-sovereign",
    "base_url": "http://127.0.0.1:8091/v1",
    "enabled_toolsets": ["hermes-cli", "terminal", "file"],
}

p.write_text(yaml.safe_dump(c, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
print("patched silo channel prompt")
