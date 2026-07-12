#!/usr/bin/env python3
"""K: light index cron — domain shelf 00-INDEX only (no relocate, no RP, no vault thrash).

World 3 housekeep: keep Personal-Digital-Silo shelves agent-navigable.
Full multi-silo VaultWalker on K: is intentionally NOT daily (timeout risk).

Usage:
  python k_light_index_cron.py

Cron: daily or every 12h, no_agent, workdir D:\\HermesData, deliver local.
Empty-ish stdout when green is OK; one-liner always printed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(r"D:\HermesData")
SCRIPTS = HERMES / "scripts"
VAULT = Path(r"D:\PhronesisVault")
K_ROOT = Path(r"K:\Phronesis-Sovereign")
LOG_JSON = HERMES / "logs" / "k-light-index-latest.json"
RECEIPT = VAULT / "Operations" / "logs" / "k-light-index-latest.md"


def main() -> int:
    ts = datetime.now(timezone.utc).isoformat()
    if not K_ROOT.exists():
        payload = {
            "ts": ts,
            "ok": True,
            "skipped": True,
            "reason": "K: not mounted",
            "score": 100,
        }
        LOG_JSON.parent.mkdir(parents=True, exist_ok=True)
        LOG_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print("KLightIndex skipped=K_unmounted score=100")
        return 0

    script = SCRIPTS / "silo_domain_indexes.py"
    if not script.is_file():
        print("KLightIndex error=missing_silo_domain_indexes")
        return 1

    try:
        r = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            cwd=str(HERMES),
        )
        out = ((r.stdout or "") + "\n" + (r.stderr or ""))[-2500:]
        ok = r.returncode == 0
        score = 100 if ok else 60
        payload = {
            "ts": ts,
            "ok": ok,
            "skipped": False,
            "exit": r.returncode,
            "score": score,
            "out_tail": out[-800:],
            "world": 3,
            "path": str(K_ROOT),
        }
    except subprocess.TimeoutExpired:
        payload = {
            "ts": ts,
            "ok": False,
            "skipped": False,
            "exit": 124,
            "score": 40,
            "reason": "timeout",
        }
        ok = False
    except Exception as e:
        payload = {
            "ts": ts,
            "ok": False,
            "exit": 1,
            "score": 30,
            "reason": f"{type(e).__name__}: {e}",
        }
        ok = False

    LOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    LOG_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(
        f"""# K Light Index — {ts}

**ok:** {payload.get('ok')} · score={payload.get('score')} · skipped={payload.get('skipped', False)}

World 3 only. No RP, no vault graph thrash.

## Vault links
- [[Operations/Vault-Hygiene-Cadence-CANONICAL-2026-07-12]]
- [[Operations/Four-Worlds-Silo-Architecture-CANONICAL-2026-07-10]]
""",
        encoding="utf-8",
    )
    print(
        f"KLightIndex score={payload.get('score')} ok={payload.get('ok')} "
        f"skipped={payload.get('skipped', False)}"
    )
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
