#!/usr/bin/env python3
"""Infinite expand smoke -- YAML fleet_registry add -> curator -> panel chain."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

HERMES = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")
REGISTRY = HERMES / "config" / "fleet_registry.yaml"
PRIORITY = VAULT / "Operations" / "model-priority-state.json"
MARKER = "smoke-expand-registry-proof"
VENV_PY = HERMES / "hermes-agent" / "venv" / "Scripts" / "python.exe"
CURATOR = HERMES / "scripts" / "model_priority_curator.py"
PANEL_SCRIPT = VAULT / "scripts" / "sovereign_router_panel.py"

ERRORS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS {name}")
    else:
        ERRORS.append(f"{name}: {detail}")
        print(f"  FAIL {name} -- {detail}")


def main() -> int:
    print("=== Infinite Expand Smoke ===\n")
    reg = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    ids = [str(e.get("id")) for e in reg.get("compute_providers") or [] if isinstance(e, dict)]
    check("yaml_marker_present", MARKER in ids, str(ids[-3:]))

    py = str(VENV_PY) if VENV_PY.is_file() else sys.executable
    proc = subprocess.run(
        [py, str(CURATOR), "--tick"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(HERMES),
    )
    check("curator_tick_ok", proc.returncode == 0, (proc.stderr or proc.stdout)[-200:])

    pri = json.loads(PRIORITY.read_text(encoding="utf-8-sig")) if PRIORITY.is_file() else {}
    free_tier = next((t for t in pri.get("tiers") or [] if t.get("id") == "internet_free"), {})
    free_ids = [str(m.get("id")) for m in free_tier.get("models") or []]
    check("priority_state_lists_marker", MARKER in free_ids, str(free_ids[:6]))

    sys.path.insert(0, str(PANEL_SCRIPT.parent))
    from sovereign_router_panel import build_sovereign_router_panel  # type: ignore

    panel = build_sovereign_router_panel(force_refresh=True)
    flow = panel.get("flow") or {}
    moe = flow.get("moe_constellation") or {}
    ranked_ids = [str(r.get("id")) for r in moe.get("ranked_providers") or []]
    # Constellation shows top-N only; full tier SSOT is model-priority-state.json
    check(
        "panel_constellation_active",
        bool(moe.get("ranked_providers")),
        f"top4={ranked_ids}; marker_in_full_tier={MARKER in free_ids}",
    )
    check("expand_chain_complete", MARKER in free_ids and MARKER in ids, str(ranked_ids))

    print(f"\n=== Results: {len(ERRORS)} failures ===")
    for e in ERRORS:
        print(f"  - {e}")
    return 1 if ERRORS else 0


if __name__ == "__main__":
    raise SystemExit(main())