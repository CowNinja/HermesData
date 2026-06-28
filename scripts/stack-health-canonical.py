"""Hermes no_agent cron: canonical stack health -> operator-console.jsonl."""
import json
import subprocess
import sys

PS1 = r"D:\\PhronesisVault\\Operations\\Invoke-StackHealthCanonical.ps1"

try:
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", PS1],
        capture_output=True,
        text=True,
        timeout=180,
    )
except subprocess.TimeoutExpired as e:
    out = e.stdout or ""
    if isinstance(out, bytes):
        out = out.decode(errors="ignore")
    print(f"Stack health script TIMEOUT (>{e.timeout}s): {out.strip()}")
    sys.exit(124)
except Exception as e:
    print(f"Stack health wrapper error: {type(e).__name__}: {e}")
    sys.exit(1)

line = (proc.stdout or "").strip()

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
