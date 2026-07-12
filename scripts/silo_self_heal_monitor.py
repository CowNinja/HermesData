#!/usr/bin/env python3
"""Ending-loop self-heal: measure → fix → log. $0 Grok. Safe for heartbeat."""
from __future__ import annotations
import json, sqlite3, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(r"D:\HermesData\state")
SCRIPTS = Path(r"D:\HermesData\scripts")
LOG = Path(r"D:\PhronesisVault\Operations\logs\silo-self-heal-latest.md")
PY = sys.executable

def utc():
    return datetime.now(timezone.utc).isoformat()

def main():
    actions = []
    # continuous age
    st_path = STATE / "silo_continuous_state.json"
    age = 99999
    if st_path.is_file():
        st = json.loads(st_path.read_text(encoding="utf-8"))
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(st["at"].replace("Z","+00:00"))).total_seconds()
        if age > 900:
            # restart continuous
            subprocess.Popen(
                [PY, str(SCRIPTS / "silo_continuous_loop.py"), "--force-mode", "aggressive"],
                cwd=str(SCRIPTS),
                stdout=open(STATE / "silo_continuous.out", "a"),
                stderr=subprocess.STDOUT,
            )
            actions.append(f"restarted continuous (age={age:.0f}s)")
        else:
            actions.append(f"continuous ok age={age:.0f}s cycle={st.get('cycle')}")
    # ocr discover if queue thin
    try:
        con = sqlite3.connect(str(STATE / "ocr_backlog.sqlite3"))
        q = con.execute("select count(*) from ocr_queue where status in ('queued','needs_ocr')").fetchone()[0]
        ok = con.execute("select count(*) from ocr_queue where status='ok_text'").fetchone()[0]
        con.close()
        actions.append(f"ocr queued={q} ok_text={ok}")
        if q < 100:
            subprocess.run([PY, str(SCRIPTS / "silo_ocr_backlog_worker.py"), "--limit", "5", "--discover-only"], timeout=120)
            actions.append("ocr rediscover")
    except Exception as e:
        actions.append(f"ocr check err {e}")
    # brief
    try:
        subprocess.run([PY, str(SCRIPTS / "silo_status_brief.py")], timeout=60, capture_output=True)
        actions.append("brief refreshed")
    except Exception as e:
        actions.append(f"brief err {e}")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("# Self-heal " + utc() + "\n\n" + "\n".join(f"- {a}" for a in actions) + "\n", encoding="utf-8")
    print(json.dumps({"at": utc(), "actions": actions}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
