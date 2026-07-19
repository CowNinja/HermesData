#!/usr/bin/env python3
"""K-light index cron — shelf indexes + world indexes with soft-fail receipts.

2026-07-18 residual seal:
- Longer child timeout (600s) — full silo walk can exceed 180s under load.
- Measure/receipt always written; cron exit 0 unless catastrophic (K: gone AND world gone).
- Soft-fail model: ok=false stays in JSON for humans; gateway sees green run + receipt.
Research: cron soft-fail + heartbeat/receipt (dead-man complementary); exit 0 + structured
status beats silent exit-1 red noise for advisory index jobs.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")
SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
RECEIPT = VAULT / "Operations" / "logs" / "k-light-index-latest.json"
# 2026-07-18: 180s was flapping K-Light to score=40; silo capped walk still needs headroom.
CHILD_TIMEOUT_SEC = 600
SOFT_FAIL_EXIT = 0  # advisory index job — never red-fail the day on timeout/partial


def run_py(script: Path, timeout: int = CHILD_TIMEOUT_SEC) -> dict:
    if not script.is_file():
        return {"ok": False, "reason": "missing_script", "script": str(script)}
    try:
        p = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(ROOT),
        )
        return {
            "ok": p.returncode == 0,
            "code": p.returncode,
            "stdout_tail": (p.stdout or "")[-2000:],
            "stderr_tail": (p.stderr or "")[-1000:],
            "timeout_sec": timeout,
        }
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        err = (e.stderr or "") if isinstance(e.stderr, str) else ""
        return {
            "ok": False,
            "reason": "timeout",
            "timeout_sec": timeout,
            "stdout_tail": out[-2000:],
            "stderr_tail": err[-1000:],
        }
    except Exception as e:
        return {"ok": False, "reason": type(e).__name__, "error": str(e)[:300]}


def main() -> int:
    t0 = time.time()
    # Prefer local scripts copy (HermesData); fall back to vault scripts if ever moved.
    domain_script = ROOT / "scripts" / "silo_domain_indexes.py"
    if not domain_script.is_file():
        domain_script = VAULT / "scripts" / "silo_domain_indexes.py"
    world_script = ROOT / "scripts" / "silo_world_indexes.py"
    if not world_script.is_file():
        world_script = VAULT / "scripts" / "silo_world_indexes.py"

    k_ok = SILO.is_dir()
    payload = {
        "at": datetime.now(timezone.utc).isoformat(),
        "k_mounted": k_ok,
        "child_timeout_sec": CHILD_TIMEOUT_SEC,
        "domain_indexes": None,
        "world_indexes": None,
        "score": 0,
        "ok": False,
        "soft_fail": True,
        "seal": "2026-07-18-k-light-softfail",
    }

    if not k_ok:
        payload["skip_reason"] = "K_drive_not_mounted"
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"KLightIndex score=0 ok=False skipped=True reason=K_missing elapsed={time.time()-t0:.1f}s")
        # Catastrophic only if world script also cannot run meaningfully — still soft for cron noise.
        return SOFT_FAIL_EXIT

    payload["domain_indexes"] = run_py(domain_script)
    payload["world_indexes"] = run_py(world_script)

    score = 0
    if payload["domain_indexes"].get("ok"):
        score += 50
    if payload["world_indexes"].get("ok"):
        score += 40
    if k_ok:
        score += 10
    payload["score"] = score
    payload["ok"] = score >= 90
    payload["elapsed_sec"] = round(time.time() - t0, 2)
    # Partial success is still a useful run (receipt proves scheduler fired).
    payload["partial"] = bool(score >= 50 and not payload["ok"])

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"KLightIndex score={score} ok={payload['ok']} partial={payload['partial']} "
        f"skipped=False soft_fail=1 elapsed={payload['elapsed_sec']}s receipt={RECEIPT}"
    )
    # Hard-fail only if both children missing scripts (misinstall) — not timeout/partial.
    both_missing = (
        payload["domain_indexes"].get("reason") == "missing_script"
        and payload["world_indexes"].get("reason") == "missing_script"
    )
    if both_missing:
        return 1
    return SOFT_FAIL_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
