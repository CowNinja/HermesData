#!/usr/bin/env python3
"""Daily vault hygiene MEASURE-only cron wrapper (06:00).

ACT moves live in vault_gardener_tick.py (05:15). This job never mutates notes.

2026-07-18 residual seal:
- Child measure failures → warn + receipt + exit 0 (advisory).
- Capture stderr tails so cron MD is debuggable.
- Hard-fail only if vault root missing (true misconfig).
Research: structured soft-fail + receipt > exit-1 red noise for measure jobs
(cron monitoring best practice: distinguish infra death vs advisory lint).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from atomic_io import atomic_write_json
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore

VAULT = Path(r"D:\PhronesisVault")
RECEIPT = VAULT / "Operations" / "logs" / "daily-vault-hygiene-cron-latest.json"
CHILD_TIMEOUT_SEC = 900  # large vault walk; was unbounded under flaky cron envs


def _write_receipt(payload: dict) -> None:
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    if atomic_write_json is not None:
        atomic_write_json(RECEIPT, payload, indent=2, min_bytes=20)
    else:
        RECEIPT.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _run(label: str, argv: list[str], *, timeout: int = CHILD_TIMEOUT_SEC) -> dict:
    try:
        p = subprocess.run(
            argv,
            cwd=str(VAULT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "label": label,
            "ok": p.returncode == 0,
            "code": p.returncode,
            "stdout_tail": (p.stdout or "")[-2000:],
            "stderr_tail": (p.stderr or "")[-1500:],
        }
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else ""
        err = e.stderr if isinstance(e.stderr, str) else ""
        return {
            "label": label,
            "ok": False,
            "code": 124,
            "reason": "timeout",
            "timeout_sec": timeout,
            "stdout_tail": (out or "")[-2000:],
            "stderr_tail": (err or "")[-1500:],
        }
    except Exception as e:
        return {
            "label": label,
            "ok": False,
            "code": 1,
            "reason": type(e).__name__,
            "error": str(e)[:400],
        }


def main() -> int:
    if not VAULT.is_dir():
        print(f"FAIL: vault missing: {VAULT}")
        return 1

    print(f"VAULT_CONFIRMED={VAULT}")
    py = sys.executable
    steps = []

    # 1) Measure / propose only
    audit = _run(
        "daily_vault_hygiene_audit",
        [py, str(VAULT / "scripts" / "daily_vault_hygiene_audit.py")],
    )
    steps.append(audit)
    if audit["ok"]:
        print("OK: daily_vault_hygiene_audit.py")
        if audit.get("stdout_tail"):
            # keep cron output small but useful
            tail = audit["stdout_tail"].strip().splitlines()
            for line in tail[-12:]:
                print(line)
    else:
        print(
            f"WARN: daily_vault_hygiene_audit.py exited {audit.get('code')} "
            f"reason={audit.get('reason', 'nonzero')} (soft-fail; measure advisory)"
        )
        if audit.get("stderr_tail"):
            print("--- stderr_tail ---")
            print(audit["stderr_tail"][-800:])

    # 2) Living-set orphan signal (read-only count) — optional module
    living_orphan_count = None
    try:
        import importlib.util

        candidates = [
            VAULT / "scripts" / "vault_graph_living.py",
            Path(r"D:\HermesData\scripts") / "vault_graph_living.py",
        ]
        mod = None
        for cand in candidates:
            if cand.is_file():
                spec = importlib.util.spec_from_file_location("vault_graph_living", cand)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    break
        if mod is not None and hasattr(mod, "iter_living_markdown") and hasattr(mod, "is_orphan"):
            living_orphan_count = sum(1 for p in mod.iter_living_markdown() if mod.is_orphan(p))
            print(f"living_orphan_count={living_orphan_count}")
        else:
            print("living_orphan_count=skip (module not installed)")
    except Exception as e:
        print(f"living_orphan_count=skip ({type(e).__name__}: {e})")

    # 3) Link lint — advisory only (never fails the job)
    lint = _run(
        "vault_link_lint",
        [py, str(VAULT / "scripts" / "vault_link_lint.py")],
        timeout=300,
    )
    steps.append(lint)
    print(
        f"link_lint: code={lint.get('code')} ok={lint.get('ok')} "
        f"(advisory; gardener owns ACT)"
    )

    # 3b) Living unresolved scan — truth surface for CNS hygiene (advisory)
    living_scan = Path(r"D:\HermesData\scripts") / "vault_living_unresolved_scan.py"
    living_unresolved = None
    if living_scan.is_file():
        lr = _run("living_unresolved_scan", [py, str(living_scan)], timeout=600)
        steps.append(lr)
        try:
            import re as _re

            m = _re.search(r'"unresolved_link_count":\s*(\d+)', lr.get("stdout_tail") or "")
            if m:
                living_unresolved = int(m.group(1))
        except Exception:
            living_unresolved = None
        print(
            f"living_unresolved_scan: code={lr.get('code')} ok={lr.get('ok')} "
            f"count={living_unresolved} (truth surface; measure-only)"
        )
    else:
        print("living_unresolved_scan=skip (script missing)")

    # 4) Optional deeper link audit if present — advisory
    deep = VAULT / "scripts" / "vault_link_audit.py"
    if deep.is_file():
        deep_r = _run("vault_link_audit", [py, str(deep)], timeout=600)
        steps.append(deep_r)
        print(f"link_audit: code={deep_r.get('code')} ok={deep_r.get('ok')} (advisory)")

    measure_ok = bool(audit.get("ok"))
    payload = {
        "at": datetime.now(timezone.utc).isoformat(),
        "vault": str(VAULT),
        "mode": "measure_only",
        "measure_ok": measure_ok,
        "living_orphan_count": living_orphan_count,
        "living_unresolved_count": living_unresolved,
        "steps": [
            {
                "label": s.get("label"),
                "ok": s.get("ok"),
                "code": s.get("code"),
                "reason": s.get("reason"),
            }
            for s in steps
        ],
        "soft_fail": True,
        "seal": "2026-07-19-hygiene-living-unresolved",
        "note": "ACT path is vault_gardener_tick @05:15 — this job never moves notes. Living unresolved = CNS hygiene truth surface.",
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    _write_receipt(payload)
    print(f"receipt={RECEIPT}")
    print(
        f"DailyVaultHygiene measure_ok={measure_ok} soft_fail=1 exit=0 "
        f"(hard-fail only if vault missing)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
