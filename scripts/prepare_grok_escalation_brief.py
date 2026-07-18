#!/usr/bin/env python3
"""Build a short, fact-preloaded brief for Grok (token thrift).

Runs local measurements, classifies escalate-worthiness, writes vault receipt.
Paste path into Grok Discord driver thread 1524846849360531456 — not a raw K: walk.

Usage:
  python D:\\HermesData\\scripts\\prepare_grok_escalation_brief.py --topic "watchdog dual-writer"
  python D:\\HermesData\\scripts\\prepare_grok_escalation_brief.py --topic "next sources" --print
  python D:\\HermesData\\scripts\\prepare_grok_escalation_brief.py --list-triggers
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
OUT_DIR = Path(r"D:\PhronesisVault\Operations\logs")
PY = sys.executable
GROK_THREAD = "1524846849360531456"
SILO_THREAD = "1524529242019336434"
CANON = "Operations/Grok-Thread-Architecture-Judgment-CANONICAL-2026-07-18"

# Topic keywords → should escalate to Grok (driver)
ESCALATE_TRIGGERS = {
    "dual-writer": ["dual.writer", "two continuous", "multi.?writer", "second continuous"],
    "purge": ["purge", "wipe drive", "destroy silo"],
    "vw_live": ["vaultwalker live", "vw live", "live index", "live relocate"],
    "gateway_arch": ["double.?boot", "gateway architecture", "8642 design", "forkguard design"],
    "hybrid": ["hybrid rout", "token policy", "which model", "grok vs local", "route to grok"],
    "canon_audit": ["hallucinat", "canon conflict", "which doc is law", "policy dispute"],
    "topology": ["four.?world", "new world", "wall breach", "rp leak"],
}

# Should stay on silo grunt (do not burn Grok)
STAY_LOCAL = [
    r"ocr_open",
    r"unprocessed count",
    r"six_numbers",
    r"is continuous (alive|running)",
    r"train batch",
    r"scoreboard",
    r"how many landed",
]


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


def classify(topic: str) -> dict:
    t = topic.lower()
    hits = []
    for name, pats in ESCALATE_TRIGGERS.items():
        for pat in pats:
            if re.search(pat, t, re.I):
                hits.append(name)
                break
    stay = [p for p in STAY_LOCAL if re.search(p, t, re.I)]
    if stay and not hits:
        recommendation = "STAY_LOCAL_SILO_THREAD"
    elif hits:
        recommendation = "ESCALATE_GROK"
    else:
        recommendation = "ESCALATE_GROK_IF_JUDGMENT_ELSE_SILO"
    return {"trigger_hits": hits, "stay_local_hits": stay, "recommendation": recommendation}


def main() -> int:
    ap = argparse.ArgumentParser(description="Grok escalation brief (judgment only)")
    ap.add_argument("--topic", help="One-line judgment question for Grok")
    ap.add_argument("--print", action="store_true", help="Also print body to stdout")
    ap.add_argument("--list-triggers", action="store_true")
    ap.add_argument("--skip-metrics", action="store_true", help="Skip six_numbers/status (faster)")
    args = ap.parse_args()

    if args.list_triggers:
        print(json.dumps({"escalate": ESCALATE_TRIGGERS, "stay_local": STAY_LOCAL}, indent=2))
        return 0
    if not args.topic:
        ap.error("--topic required unless --list-triggers")

    clf = classify(args.topic)

    six = ""
    pulse = ""
    status = ""
    counts = ""
    if not args.skip_metrics:
        six = run([PY, str(SCRIPTS / "silo_discord_six_numbers.py")], 90)
        pulse = run([PY, str(SCRIPTS / "silo_scoreboard_pulse.py")], 90)
        status = run([PY, str(SCRIPTS / "silo_autonomous_status.py")], 60)
        counts = run(
            [
                PY,
                "-c",
                (
                    "import subprocess; "
                    "r=subprocess.run(['powershell','-NoProfile','-Command',"
                    "\"(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*silo_continuous_loop.py*' -and $_.Name -like 'python*' }).Count\"],"
                    "capture_output=True,text=True); print('continuous_loop', (r.stdout or '').strip()); "
                    "r2=subprocess.run(['powershell','-NoProfile','-Command',"
                    "\"(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*silo_orchestrator_tick.py*' -and $_.Name -like 'python*' }).Count\"],"
                    "capture_output=True,text=True); print('orchestrator_tick', (r2.stdout or '').strip())"
                ),
            ],
            45,
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"grok-escalation-brief-{stamp}.md"
    body = f"""# Grok escalation brief — {utc()}

**Topic (judgment only):** {args.topic}

## Routing
| Field | Value |
|-------|-------|
| Classifier | `{clf['recommendation']}` |
| Trigger hits | {clf['trigger_hits'] or '—'} |
| Stay-local hits | {clf['stay_local_hits'] or '—'} |
| Deliver to | Discord Grok thread `{GROK_THREAD}` |
| Not for | Silo kitchen thrash in `{SILO_THREAD}` (unless STAY_LOCAL) |

If **STAY_LOCAL_SILO_THREAD**: answer in silo thread with tools; do **not** burn Grok.

## Hybrid rule
- Muscle/scripts measured below — **do not re-scan K:** for vanity.
- Grok answers architecture / go-no-go / design only.
- Token thrift: short verdict + concrete next actions.
- Canon: [[{CANON.replace('.md','')}]]

## Live six_numbers
```
{six.strip()[:800] if six else '(skipped)'}
```

## Live scoreboard (local)
```
{pulse.strip()[:1500] if pulse else '(skipped)'}
```

## Autonomous status
```
{status.strip()[:1200] if status else '(skipped)'}
```

## Process counts (exact script match)
```
{counts.strip()[:500] if counts else '(skipped)'}
```

## Canonical pointers
- [[{CANON.replace('.md','')}]]
- [[Operations/Hybrid-Local-Grok-Token-Policy-CANONICAL-2026-07-17]]
- [[Operations/VaultWalker-LIVE-Decision-Card-2026-07-18]]
- [[Operations/SINGLE-GATEWAY-RESTORE]]
- [[Operations/SOUL-Grok-Architecture-Agent-2026-07-18]]
- [[Operations/SOUL-Data-Silo-Agent-2026-07-17]]
- [[Operations/Data-Silo-Recovery-Status-2026-07-17]]

## Ask Grok
{args.topic}

## Expected Grok output shape
1. Verdict (1–3 lines)  
2. Risks  
3. Concrete next actions (who/which thread)  
4. What **not** to do  
"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    latest = OUT_DIR / "grok-escalation-brief-latest.md"
    latest.write_text(body, encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "path": str(out),
                "latest": str(latest),
                "classifier": clf,
                "grok_thread": GROK_THREAD,
            },
            indent=2,
        )
    )
    if args.print:
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
