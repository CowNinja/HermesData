#!/usr/bin/env python3
"""Phronesis Vault Gardener — full autonomy suite (periodic).

Captures the human+Hermes workflow as one repeatable pipeline:

  A. Integrity   — zero-newline scan (report)
  B. Proposals   — Phase B cluster report
  C. Safe auto-distill — only known noise classes (optional --execute-safe)
  D. Wikilinks   — repair after moves
  E. Indexes     — refresh + fill missing 00-INDEX maps
  F. Status      — thin orchestrator + receipt in vault

Design:
  - Daily: call with --mode daily (integrity + indexes light + status)
  - Weekly: --mode weekly (all of the above + proposals + safe execute)
  - VaultWalker stays SEPARATE (daily dry walk) — see automation system doc.

Usage:
  python vault_gardener_autonomy_suite.py --mode weekly --execute-safe
  python vault_gardener_autonomy_suite.py --mode daily
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(r"D:\HermesData")
SCRIPTS = HERMES / "scripts"
VAULT = Path(r"D:\PhronesisVault")
LOG_JSON = HERMES / "logs" / "vault-gardener-autonomy-suite-latest.json"
LOG_TXT = HERMES / "logs" / "vault-gardener-autonomy-suite-latest.txt"


def run_script(name: str, args: list[str] | None = None, timeout: int = 1800) -> dict:
    path = SCRIPTS / name
    if not path.is_file():
        return {"script": name, "exit": 0, "skip": True, "out": f"missing {name}"}
    cmd = [sys.executable, str(path)] + (args or [])
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(HERMES),
        )
        out = ((r.stdout or "") + "\n" + (r.stderr or ""))[-2500:]
        return {"script": name, "exit": r.returncode, "skip": False, "out": out}
    except subprocess.TimeoutExpired:
        return {"script": name, "exit": 124, "skip": False, "out": "TIMEOUT"}
    except Exception as e:
        return {"script": name, "exit": 1, "skip": False, "out": f"{type(e).__name__}: {e}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["daily", "weekly"], default="weekly")
    ap.add_argument(
        "--execute-safe",
        action="store_true",
        help="Run known-safe distill wave scripts (recoverable archive patterns)",
    )
    args = ap.parse_args()
    ts = datetime.now(timezone.utc).isoformat()
    results: list[dict] = []

    # Always
    r0 = run_script("hygiene_zero_newline_scan.py", timeout=300)
    # exit 1 = findings, not pipeline death
    if r0.get("exit") == 1:
        r0["exit"] = 0
        r0["out"] = (r0.get("out") or "") + chr(10) + "[soft] findings treated non-fatal"
    results.append(r0)
    results.append(run_script("thin_orchestrator_status.py", timeout=60))

    if args.mode == "weekly":
        results.append(run_script("k_domain_shelves_ensure.py", timeout=60))
        results.append(run_script("cloud_recovery_pack_sync.py", timeout=180))
        results.append(run_script("g_memorycard_inventory.py", timeout=120))
        results.append(run_script("silo_pipeline_smoke_test.py", timeout=300))
        results.append(run_script("g_to_k_drain_autonomous.py", timeout=900))
        results.append(run_script("backup_layers_status.py", timeout=60))
        results.append(run_script("k_test_ingest_domain_propose.py", timeout=180))
        results.append(run_script("orchestrator_quest_dispatch.py", timeout=120))
        results.append(run_script("gardener_phase_b_proposals.py", ["--stale-days", "30"], timeout=600))
        if args.execute_safe:
            # Only scripts that implement digest+archive recoverable patterns
            for s in [
                "phase_b_execute_wave3_background.py",
                "phase_b_execute_wave4_background.py",
                "phase_b_execute_wave5_ops_reports.py",
            ]:
                # Idempotent-ish: re-run is ok if no matching files left
                results.append(run_script(s, timeout=900))
        results.append(run_script("refresh_folder_indexes.py", timeout=300))
        results.append(run_script("fill_missing_indexes.py", timeout=300))
        results.append(
            run_script(
                "vault_hub_backlink_pass.py",
                ["--apply", "--limit", "400"],
                timeout=900,
            )
        )
        results.append(run_script("vault_wikilink_repair_after_distill.py", timeout=900))
    else:
        # daily light: indexes (wikilinked) → hub backlinks for living orphans → repair
        results.append(run_script("refresh_folder_indexes.py", timeout=300))
        results.append(
            run_script(
                "vault_hub_backlink_pass.py",
                ["--apply", "--limit", "150"],
                timeout=600,
            )
        )
        results.append(run_script("vault_wikilink_repair_after_distill.py", timeout=600))

    worst = max((r.get("exit") or 0) for r in results) if results else 0
    payload = {
        "ts": ts,
        "mode": args.mode,
        "execute_safe": bool(args.execute_safe),
        "worst_exit": worst,
        "steps": [{"script": r["script"], "exit": r["exit"], "skip": r.get("skip")} for r in results],
    }
    LOG_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    LOG_TXT.write_text(
        f"{ts} mode={args.mode} execute_safe={args.execute_safe} worst={worst}\n"
        + "\n".join(f"{r['script']}: {r['exit']}\n{r.get('out','')[:500]}" for r in results),
        encoding="utf-8",
    )

    # Vault receipt (thin)
    rec = VAULT / "Operations" / "logs" / f"autonomy-suite-{datetime.now().strftime('%Y-%m-%d')}.md"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(
        f"# Autonomy Suite Run — {datetime.now().strftime('%Y-%m-%d')}\n\n"
        f"- mode: `{args.mode}`\n"
        f"- execute_safe: `{args.execute_safe}`\n"
        f"- worst_exit: `{worst}`\n\n"
        "## Steps\n"
        + "\n".join(f"- `{r['script']}` → exit {r['exit']}" for r in results)
        + "\n\n## Vault links\n"
        "- [[Operations/Vault-Gardener-Automation-System-2026-07-10]]\n"
        "- [[Operations/Lesson-to-Automation-Protocol-2026-07-10]]\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2))
    return 0 if worst == 0 else worst


if __name__ == "__main__":
    raise SystemExit(main())
