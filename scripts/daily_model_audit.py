#!/usr/bin/env python3
"""Daily model audit + auto-reconcile wrapper. Exits silently if clean."""
import subprocess, sys, json
from pathlib import Path

SCRIPTS = r"D:\PhronesisVault\scripts"
VENV_PY = r"D:\HermesData\hermes-agent\venv\Scripts\python.exe"

def run_script(*args: str) -> dict:
    py = VENV_PY if Path(VENV_PY).is_file() else sys.executable
    result = subprocess.run(
        [py, *args],
        cwd=SCRIPTS, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )
    return {"rc": result.returncode, "stdout": result.stdout, "stderr": result.stderr}

def main() -> int:
    audit = run_script("model_inventory.py", "--audit")
    if audit["rc"] != 0:
        print(f"AUDIT FAILED (rc={audit['rc']})")
        print(audit["stderr"][:500])
        return 1

    # Parse output for drift count
    output = audit["stdout"]
    drift = 0
    try:
        data = json.loads(output)
        drift = data.get("drift_count", 0) if isinstance(data, dict) else 0
    except (json.JSONDecodeError, AttributeError):
        import re
        m = re.search(r'drift[_\s]*(?:count)?[:\s]*(\d+)', output, re.IGNORECASE)
        if m:
            drift = int(m.group(1))

    if drift > 0:
        print(f"Drift detected: {drift} items. Running reconcile...")
        reconcile = run_script("model_inventory.py", "--reconcile")
        if reconcile["rc"] != 0:
            print(f"RECONCILE FAILED (rc={reconcile['rc']})")
            print(reconcile["stderr"][:500])
            return 2
        print(f"Reconcile complete. {reconcile['stdout'][:300]}")
    else:
        print("OK - no drift detected.")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
