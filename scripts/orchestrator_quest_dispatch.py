#!/usr/bin/env python3
"""Master-orchestrator quest runner — read-only muscle.

Parent (Hermes) or cron runs this; no deletes, no gateway restarts, no K moves.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")
K_SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
OUT = VAULT / "Operations" / "logs" / "orchestrator-quest-receipt-latest.md"
OUT_JSON = HERMES / "logs" / "orchestrator-quest-receipt-latest.json"


def quest_hybrid_health() -> tuple[bool, str]:
    ok_all = True
    bits = []
    for port, name in [(8090, "qwythos"), (8091, "proxy")]:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
                body = r.read()[:80].decode("utf-8", "replace")
                bits.append(f"{name}:{r.status}:{body}")
        except Exception as e:
            ok_all = False
            bits.append(f"{name}:FAIL:{e}")
    return ok_all, "; ".join(bits)


def quest_four_worlds_config() -> tuple[bool, str]:
    p = HERMES / "config" / "data_silos.yaml"
    if not p.exists():
        return False, "missing data_silos.yaml"
    t = p.read_text(encoding="utf-8", errors="ignore")
    need = ["HermesData", "PhronesisVault", "K_PhronesisSovereign", "RoleplaySandbox"]
    missing = [n for n in need if n not in t]
    return (not missing), f"missing={missing or 'none'}"


def quest_k_indexes() -> tuple[bool, str]:
    if not K_SILO.exists():
        return False, "K silo missing"
    folders = ["Core-Personal", "Life-Archive", "Navy-Service", "Medical", "Digital-Footprint"]
    present, absent = [], []
    for f in folders:
        idx = K_SILO / f / "00-INDEX.md"
        (present if idx.exists() else absent).append(f)
    # pilot wave presence
    pilot = K_SILO / "Medical-Records" / "pilot-2026-07-10"
    pilot_ok = pilot.exists()
    return len(absent) == 0, f"indexed={present} missing={absent} pilot_wave={pilot_ok}"


def quest_vault_maps() -> tuple[bool, str]:
    keys = [
        VAULT / "00-INDEX.md",
        VAULT / "Operations" / "Four-Worlds-Silo-Architecture-CANONICAL-2026-07-10.md",
        VAULT / "Operations" / "Master-Orchestrator-Path-2026-07-10.md",
        VAULT / "Operations" / "Five-Primary-Tracks-Active-2026-07-10.md",
        VAULT / "Operations" / "Next-Five-Primary-Action-Items-2026-07-10.md",
    ]
    miss = [str(p.name) for p in keys if not p.exists()]
    return not miss, f"missing={miss or 'none'}"


def quest_scripts_muscle() -> tuple[bool, str]:
    scripts = [
        "vault_gardener_autonomy_suite.py",
        "grunt_local.py",
        "refresh_folder_indexes.py",
        "k_pilot_wave_copy.py",
        "orchestrator_quest_dispatch.py",
    ]
    miss = [s for s in scripts if not (HERMES / "scripts" / s).exists()]
    return not miss, f"missing={miss or 'none'}"


def quest_sandbox_wall() -> tuple[bool, str]:
    rp = VAULT / "Roleplay-Sandbox"
    need = [
        rp / "profile" / "SOUL.md",
        rp / "profile" / "SANDBOX-CONTENT-SSOT.md",
        rp / "docs" / "DEDICATED-RP-SESSION.md",
        rp / "registry" / "CAST-LOCK-RULE.md",
    ]
    miss = [p.name for p in need if not p.exists()]
    return not miss, f"missing={miss or 'none'}"


QUESTS = [
    ("hybrid_health", quest_hybrid_health),
    ("four_worlds_config", quest_four_worlds_config),
    ("k_indexes", quest_k_indexes),
    ("vault_maps", quest_vault_maps),
    ("scripts_muscle", quest_scripts_muscle),
    ("sandbox_wall", quest_sandbox_wall),
]


def main() -> int:
    ts = datetime.now(timezone.utc).isoformat()
    results = []
    for name, fn in QUESTS:
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append({"quest": name, "ok": ok, "detail": detail})
    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    score = int(100 * passed / total) if total else 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Orchestrator quest receipt — {ts}",
        "",
        f"**Score:** {passed}/{total} = **{score}%**",
        "",
        "| Quest | OK | Detail |",
        "|-------|----|--------|",
    ]
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        lines.append(f"| `{r['quest']}` | {mark} | {r['detail'][:140]} |")
    lines += [
        "",
        "## Rule",
        "Travel-safe. No restarts/deletes in this script.",
        "",
        "## Links",
        "- [[Operations/Master-Orchestrator-Path-2026-07-10]]",
        "- [[Operations/logs/k-pilot-wave-receipt-latest]]",
        "",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    OUT_JSON.write_text(json.dumps({"ts": ts, "score": score, "results": results}, indent=2), encoding="utf-8")
    print(json.dumps({"score": score, "passed": passed, "total": total}, indent=2))
    return 0 if score >= 80 else 1


if __name__ == "__main__":
    raise SystemExit(main())
