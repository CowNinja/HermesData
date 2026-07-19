#!/usr/bin/env python3
"""Hermes cron entry: daily vault hygiene **measure** (not act).

Pipeline split (2026-07-12 streamline):
  05:15 Vault-Gardener-Autonomy-Daily  → ACT
        (indexes + hub backlinks + wikilink repair)
  06:00 Daily-Vault-Hygiene-Audit      → MEASURE (this script)
        (distillation proposals + link audit + L4 lint)

Avoids double refresh/hub-pass every morning. If living orphans
crept in overnight after 05:15, a **bounded catch-up** hub pass
runs only when living_orphan_count > 0 after a quick pre-scan.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
VAULT_SCRIPT = VAULT / "scripts" / "daily_vault_hygiene_audit.py"
LINK_AUDIT = VAULT / "scripts" / "vault_link_audit.py"
LINK_LINT = VAULT / "scripts" / "vault_link_lint.py"
HUB_PASS = Path(r"D:\HermesData\scripts\vault_hub_backlink_pass.py")
AUDIT_JSON = VAULT / "Operations" / "logs" / "vault-link-audit-latest.json"


def run(script: Path, extra: list[str] | None = None) -> int:
    if not script.exists():
        print(f"MISSING {script}")
        return 1
    return subprocess.call([sys.executable, str(script), *(extra or [])])


def living_orphan_count() -> int | None:
    if not AUDIT_JSON.is_file():
        return None
    try:
        data = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
        return int(data.get("living_orphan_count", 0))
    except Exception:
        return None


def main() -> int:
    if not VAULT.is_dir():
        print("VAULT_CONFIRMED FAIL")
        return 1
    print(f"VAULT_CONFIRMED={VAULT}")

    # 1) Distillation proposals + hotspots (measure)
    code = run(VAULT_SCRIPT)
    if code != 0:
        print(f"FAIL: {VAULT_SCRIPT.name} exited {code}")
        return code

    # 2) Link audit (measure) — updates living vs noise metrics
    code = run(LINK_AUDIT)
    if code != 0:
        print(f"FAIL: {LINK_AUDIT.name} exited {code}")
        return code

    # 3) Catch-up ACT only if living orphans remain after morning gardener
    loc = living_orphan_count()
    if loc is not None and loc > 0:
        print(f"CATCHUP hub-backlink living_orphans={loc}")
        run(HUB_PASS, ["--apply", "--limit", str(min(loc + 20, 150))])
        # re-measure
        run(LINK_AUDIT)
        loc2 = living_orphan_count()
        print(f"CATCHUP after living_orphans={loc2}")
    else:
        print(f"living_orphans={loc} — no catch-up needed")

    # 4) L4 lint advisory
    code = run(LINK_LINT)
    if code != 0:
        print(
            f"ADVISORY: {LINK_LINT.name} found issues (exit {code}) — "
            "see Operations/Vault-Link-Lint-latest.json"
        )
    print("daily-vault-hygiene OK (measure-only + optional catch-up)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
