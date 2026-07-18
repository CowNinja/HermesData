#!/usr/bin/env python3
"""Build a short, fact-preloaded brief for Grok (token thrift).

Runs local scoreboard/status, writes vault receipt. Paste the receipt path
(or --print body) into Grok 4.5 / Grok Discord driver thread — not the raw K: walk.

Usage:
  python D:\\HermesData\\scripts\\prepare_grok_escalation_brief.py --topic "watchdog dual-writer"
  python D:\\HermesData\\scripts\\prepare_grok_escalation_brief.py --topic "next sources" --print
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
OUT_DIR = Path(r"D:\PhronesisVault\Operations\logs")
PY = sys.executable


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str], timeout: int = 120) -> str:
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            cwd=str(SCRIPTS),
        )
        return ((r.stdout or "") + (r.stderr or ""))[-4000:]
    except Exception as e:
        return f"ERR {type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True, help="One-line judgment question for Grok")
    ap.add_argument("--print", action="store_true", help="Also print body to stdout")
    args = ap.parse_args()

    pulse = run([PY, str(SCRIPTS / "silo_scoreboard_pulse.py")], 90)
    status = run([PY, str(SCRIPTS / "silo_autonomous_status.py")], 60)
    # process counts via short python
    counts = run(
        [
            PY,
            "-c",
            (
                "import subprocess; "
                "r=subprocess.run(['powershell','-NoProfile','-Command',"
                "\"(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*silo_continuous_loop*' }).Count\"],"
                "capture_output=True,text=True); print('continuous', (r.stdout or '').strip()); "
                "r2=subprocess.run(['powershell','-NoProfile','-Command',"
                "\"(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*silo_focus_land*' }).Count\"],"
                "capture_output=True,text=True); print('focus_land', (r2.stdout or '').strip())"
            ),
        ],
        45,
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"grok-escalation-brief-{stamp}.md"
    body = f"""# Grok escalation brief — {utc()}

**Topic (judgment only):** {args.topic}

## Hybrid rule
- Muscle/scripts already measured below — **do not re-scan K:** for vanity.
- Answer architecture / go-no-go / design only.
- Token thrift: short verdict + concrete next actions.

## Live scoreboard (local)
```
{pulse.strip()[:2000]}
```

## Autonomous status
```
{status.strip()[:1500]}
```

## Process counts (land writers)
```
{counts.strip()[:500]}
```

## Canonical pointers
- [[Operations/Data-Silo-Recovery-Status-2026-07-17]]
- [[Operations/Hybrid-Local-Grok-Token-Policy-CANONICAL-2026-07-17]]
- [[Operations/Autonomous-Silo-Runbook-CANONICAL-2026-07-14]]
- SOUL silo agent: [[Operations/SOUL-Data-Silo-Agent-2026-07-17]]

## Ask Grok
{args.topic}
"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    latest = OUT_DIR / "grok-escalation-brief-latest.md"
    latest.write_text(body, encoding="utf-8")
    print(json.dumps({"ok": True, "path": str(out), "latest": str(latest)}, indent=2))
    if args.print:
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
