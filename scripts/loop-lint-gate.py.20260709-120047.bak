#!/usr/bin/env python3
"""Loop v2 lint gate — active coordination files only. Exit 0 + empty stdout = silent cron."""

from __future__ import annotations

import sys
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
ACTIVE = (
    "docs/agent-coordination/Hermes-Response-to-Composer-2026-06-23-round7.md",
    "docs/agent-coordination/Hermes-Composer-Rock-Solid-Loop-Spec.md",
    "docs/agent-coordination/loop-state.json",
)


def main() -> int:
    issues: list[str] = []
    for rel in ACTIVE:
        path = VAULT / rel.replace("/", "\\")
        if not path.exists():
            issues.append(f"missing:{rel}")
            continue
        if path.suffix == ".md":
            text = path.read_text(encoding="utf-8", errors="replace")
            if "## Vault links" not in text:
                issues.append(f"no_l4_footer:{rel}")
            if "round7" in rel and "VAULT_CONFIRMED" not in text:
                issues.append(f"no_vault_confirmed:{rel}")

    if issues:
        print("LOOP_LINT_ISSUES:")
        for item in issues:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
