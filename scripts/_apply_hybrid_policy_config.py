#!/usr/bin/env python3
"""Apply hybrid Local-Grok token policy into Hermes config.yaml (2026-07-17)."""
from __future__ import annotations

import yaml
from pathlib import Path

p = Path(r"D:\HermesData\config.yaml")
bak = Path(r"D:\HermesData\config.yaml.bak-hybrid-policy-2026-07-17")
if not bak.exists():
    bak.write_bytes(p.read_bytes())

c = yaml.safe_load(p.read_text(encoding="utf-8"))

c.setdefault("agent", {})
c["agent"]["tool_use_enforcement"] = "strict"
c["agent"]["reasoning_effort"] = "low"
c["agent"]["environment_hint"] = (
    "Phronesis HYBRID 2026-07-17 (RouteLLM-style cost mix): "
    "MUSCLE=scripts ($0 land/OCR/watchdogs). "
    "GRUNT=Qwythos-9B @8090 via proxy :8091 (tool-backed status, classify, summarize). "
    "DRIVER=Grok 4.5 only for hard reasoning/architecture/anti-hallucination audit "
    "(thread 1524846849360531456 or Grok Build). "
    "DEFAULT Hermes chat stays LOCAL to avoid token burn. "
    "ALWAYS file/terminal tools before facts — never invent registry metrics, "
    "corporate silos, or people. If task needs multi-hop judgment, say ESCALATE_GROK "
    "and write a vault brief instead of free-form research roleplay. "
    "Model rotation LOCKED 9B local for grunt. Stack: 8090/8091/8642."
)

cp = c.setdefault("discord", {}).setdefault("channel_prompts", {})
co = c["discord"].setdefault("channel_overrides", {})

cp["1524529242019336434"] = """DATA SILO AGENT (K: personal silo) — HYBRID GRUNT LANE

PLANE: MUSCLE=scripts · GRUNT=you (local Qwythos) · DRIVER=Grok (not you)

REAL PATHS (only these are real):
- K:\\Phronesis-Sovereign\\Personal-Digital-Silo\\
- D:\\HermesData\\state\\ingest_registry.sqlite3
- D:\\HermesData\\scripts\\silo_*.py
- D:\\PhronesisVault\\Operations\\Data-Silo-Recovery-Status-2026-07-17.md
- SOUL: D:\\PhronesisVault\\Operations\\SOUL-Data-Silo-Agent-2026-07-17.md

MUST DO BEFORE ANY STATUS/METRICS:
1) terminal: python D:/HermesData/scripts/silo_scoreboard_pulse.py
2) and/or read_file the Recovery Status md
Quote ONLY tool output numbers. If tool fails, say TOOL_FAILED.

NEVER invent: Finance/Marketing/Spark lakehouses, fake execs, fake GitHub orgs, fake file headers.

ONE land writer. Recovery: python D:/HermesData/scripts/silo_recovery_single_writer.py

ESCALATE (do not invent architecture answers): If Jeff asks multi-hop design/judgment/policy,
reply short ESCALATE_GROK + point him to Grok 4.5 thread or run:
python D:/HermesData/scripts/prepare_grok_escalation_brief.py --topic "..."
Discord <=12 lines / short table. No full research SOP roleplay on 9B.
"""

co["1524529242019336434"] = {
    "model": "phronesis-sovereign-auto",
    "provider": "custom:phronesis-sovereign",
    "base_url": "http://127.0.0.1:8091/v1",
    "enabled_toolsets": ["hermes-cli", "terminal", "file"],
}

cp["1524846849360531456"] = """GROK DRIVER LANE (Hermes↔Grok coordination).

You are the judgment plane. Prefer short vault-linked answers.
Local silo facts come from scripts/scoreboard — do not re-walk K: blindly.
For bulk land/OCR: defer to scripts / data-silo agent (local).
Token thrift: measure first with tools, then reason; no fluff.
Master plan: D:\\PhronesisVault\\docs\\agent-coordination\\GROK-HERMES-MASTER-PLAN.md
Hybrid policy: D:\\PhronesisVault\\Operations\\Hybrid-Local-Grok-Token-Policy-CANONICAL-2026-07-17.md
"""

co["1524846849360531456"] = {
    "model": "grok-4.3",
    "provider": "xai-oauth",
    "enabled_toolsets": ["hermes-cli", "terminal", "file", "web_search"],
}

star = cp.get("*", "") or ""
if "HYBRID 2026-07-17" not in star:
    cp["*"] = (
        "HYBRID 2026-07-17: local tools+Qwythos for facts; Grok only for hard judgment "
        "(or thread 1524846849360531456). Never invent metrics. " + star
    )

c["model"] = {
    "default": "phronesis-sovereign-auto",
    "provider": "custom:phronesis-sovereign",
    "context_length": 65536,
}
c["fallback_providers"] = [
    {"provider": "xai-oauth", "model": "grok-4.3", "api_mode": "chat_completions"},
    {"provider": "xai-oauth", "model": "grok-build-0.1", "api_mode": "chat_completions"},
    {"provider": "openrouter", "model": "openrouter/free", "api_mode": "chat_completions"},
]

if "delegation" in c and isinstance(c["delegation"], dict):
    c["delegation"]["model"] = "phronesis-sovereign-auto"
    c["delegation"]["provider"] = "custom:phronesis-sovereign"
    c["delegation"]["base_url"] = "http://127.0.0.1:8091/v1"
    c["delegation"]["comment"] = (
        "2026-07-17 HYBRID: children ALWAYS local :8091. Parent default local; "
        "Grok only on driver thread or true provider fallback."
    )

p.write_text(
    yaml.safe_dump(c, sort_keys=False, allow_unicode=True, width=100),
    encoding="utf-8",
)
print("OK hybrid config written")
print("primary", c["model"])
print("silo", co["1524529242019336434"])
print("grok_thread", co["1524846849360531456"])
print("backup", bak)
