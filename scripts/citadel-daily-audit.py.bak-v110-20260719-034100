#!/usr/bin/env python3
"""Citadel daily channel audit wrapper — partial OK, soft-fail cron.

2026-07-18 residual seal:
- Never red-fail whole job on partial Discord/API errors.
- Always write receipt JSON; exit 0 unless vault scripts root missing.
- Propagate longer timeout + capture stderr for diagnosis.
Child citadel_channel_audit.py also rate-limits and continues on per-channel errors.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
# Stack/orch pointers — best-effort; paths moved over time. Never fail job if absent.
STACK_CANDIDATES = [
    VAULT / "Operations" / "STACK-HEALTH.md",
    VAULT / "docs" / "agent-coordination" / "STACK-HEALTH.md",
    VAULT / "Operations" / "logs" / "STACK-HEALTH.md",
]
ORCH_CANDIDATES = [
    VAULT / "Operations" / "ORCHESTRATOR-STATUS.md",
    VAULT / "docs" / "agent-coordination" / "ORCHESTRATOR-STATUS.md",
]
SCRIPT = VAULT / "scripts" / "citadel_channel_audit.py"
RECEIPT = VAULT / "Operations" / "logs" / "citadel-daily-audit-cron-latest.json"
CHILD_TIMEOUT_SEC = 900


def main() -> int:
    at = datetime.now(timezone.utc).isoformat()
    payload: dict = {
        "at": at,
        "ok": False,
        "partial": False,
        "soft_fail": True,
        "seal": "2026-07-18-citadel-softfail",
        "child": None,
        "stack_appended": False,
    }

    if not SCRIPT.is_file():
        payload["error"] = f"missing_script:{SCRIPT}"
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"FAIL: missing {SCRIPT}")
        return 1

    try:
        p = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=str(VAULT),
            capture_output=True,
            text=True,
            timeout=CHILD_TIMEOUT_SEC,
        )
        child = {
            "code": p.returncode,
            "ok": p.returncode == 0,
            "stdout_tail": (p.stdout or "")[-2500:],
            "stderr_tail": (p.stderr or "")[-1500:],
            "timeout_sec": CHILD_TIMEOUT_SEC,
        }
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else ""
        err = e.stderr if isinstance(e.stderr, str) else ""
        child = {
            "code": 124,
            "ok": False,
            "reason": "timeout",
            "stdout_tail": (out or "")[-2500:],
            "stderr_tail": (err or "")[-1500:],
            "timeout_sec": CHILD_TIMEOUT_SEC,
        }
    except Exception as e:
        child = {
            "code": 1,
            "ok": False,
            "reason": type(e).__name__,
            "error": str(e)[:400],
        }

    payload["child"] = {
        k: child.get(k)
        for k in ("code", "ok", "reason", "error", "timeout_sec")
        if k in child and child.get(k) is not None
    }
    # Detect partial success via latest audit artifact if child printed summary.
    latest = VAULT / "Operations" / "logs" / "citadel-channel-audit-latest.json"
    channels = 0
    errors = 0
    if latest.is_file():
        try:
            data = json.loads(latest.read_text(encoding="utf-8"))
            chans = data.get("channels") or []
            channels = len(chans)
            errors = sum(1 for c in chans if (c or {}).get("status") == "ERROR")
            payload["audit_summary"] = data.get("summary")
        except Exception as e:
            payload["audit_parse_error"] = str(e)[:200]

    payload["channel_count"] = channels
    payload["channel_errors"] = errors
    if child.get("ok") and channels > 0 and errors == 0:
        payload["ok"] = True
        payload["partial"] = False
    elif channels > 0:
        # Got some data — partial success, not a red day.
        payload["ok"] = False
        payload["partial"] = True
    else:
        payload["ok"] = False
        payload["partial"] = False

    if child.get("stdout_tail"):
        print(child["stdout_tail"].strip()[-1500:])
    if not child.get("ok"):
        print(
            f"WARN: citadel_channel_audit code={child.get('code')} "
            f"reason={child.get('reason', 'nonzero')} (soft-fail)"
        )
        if child.get("stderr_tail"):
            print("--- stderr_tail ---")
            print(child["stderr_tail"][-800:])

    # Append one-line pointer into stack health (best-effort; never fail job)
    try:
        stack = next((p for p in STACK_CANDIDATES if p.is_file()), None)
        if stack is not None:
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            line = (
                f"\n- {stamp}: citadel audit ok={payload['ok']} partial={payload['partial']} "
                f"channels={channels} errors={errors} "
                f"(see Operations/logs/citadel-channel-audit-latest.md)\n"
            )
            with stack.open("a", encoding="utf-8") as f:
                f.write(line)
            payload["stack_appended"] = True
            payload["stack_path"] = str(stack)
        orch = next((p for p in ORCH_CANDIDATES if p.is_file()), None)
        if orch is not None:
            payload["orch_present"] = True
            payload["orch_path"] = str(orch)
    except Exception as e:
        payload["stack_error"] = str(e)[:200]

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"CitadelDaily ok={payload['ok']} partial={payload['partial']} "
        f"channels={channels} errors={errors} soft_fail=1 receipt={RECEIPT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
