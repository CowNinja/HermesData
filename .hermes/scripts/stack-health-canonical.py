"""Hermes no_agent cron: canonical stack health -> operator-console.jsonl."""
import json
import subprocess
import sys

PS1 = r"D:\PhronesisVault\Operations\Invoke-StackHealthCanonical.ps1"

proc = subprocess.run(
    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", PS1],
    capture_output=True,
    text=True,
    timeout=120,
)

line = (proc.stdout or "").strip()

HEADROOM_PROBE = r"D:\PhronesisVault\scripts\stack_health_headroom_probe.py"
try:
    subprocess.run(
        [sys.executable, HEADROOM_PROBE],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
except Exception:
    pass

if proc.returncode == 0:
    print('{"wakeAgent": false}')
    sys.exit(0)

if line:
    try:
        entry = json.loads(line)
        summary = entry.get("detail", {}).get("summary", line)
        print(f"Stack health: {summary}")
    except json.JSONDecodeError:
        print(f"Stack health check failed:\n{line}")
else:
    err = (proc.stderr or "unknown error").strip()
    print(f"Stack health script failed:\n{err}")

sys.exit(proc.returncode or 1)