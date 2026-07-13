#!/usr/bin/env python3
"""Autonomy control plane: DLQ + metrics + restart gates.

Research: dead-letter queues, fail-soft, observability, incremental loads,
idempotent writes (Databricks/ETL practices 2025-26).
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(r"D:\HermesData\state")
SCRIPTS = Path(r"D:\HermesData\scripts")
DLQ = STATE / "silo_dead_letter_queue.jsonl"
METRICS = STATE / "silo_autonomy_metrics.json"
METRICS_HIST = STATE / "silo_autonomy_metrics.jsonl"
CANON = Path(
    r"D:\PhronesisVault\Operations\Autonomy-Control-Plane-CANONICAL-2026-07-13.md"
)
PY = sys.executable


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def dlq_append(kind: str, path: str, error: str, extra: dict | None = None) -> None:
    rec = {
        "at": utc(),
        "kind": kind,
        "path": path,
        "error": error[:500],
        **(extra or {}),
    }
    with DLQ.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def measure() -> dict:
    m: dict = {"at": utc()}
    st = STATE / "silo_continuous_state.json"
    if st.is_file():
        d = json.loads(st.read_text(encoding="utf-8"))
        m["cycle"] = d.get("cycle")
        try:
            age = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(d["at"].replace("Z", "+00:00"))
            ).total_seconds()
            m["continuous_age_s"] = int(age)
        except Exception:
            m["continuous_age_s"] = None
        m["mode"] = (d.get("assess") or {}).get("mode")
    reg = STATE / "ingest_registry.sqlite3"
    if reg.is_file():
        con = sqlite3.connect(str(reg))
        m["registry"] = con.execute("SELECT COUNT(*) FROM ingest").fetchone()[0]
        m["unique"] = con.execute(
            "SELECT COUNT(DISTINCT sha256) FROM ingest WHERE sha256 IS NOT NULL AND sha256!=''"
        ).fetchone()[0]
        m["process"] = dict(
            con.execute(
                "SELECT process_status, COUNT(*) FROM ingest GROUP BY process_status"
            ).fetchall()
        )
        con.close()
    ocr = STATE / "ocr_backlog.sqlite3"
    if ocr.is_file():
        con = sqlite3.connect(str(ocr))
        m["ocr"] = dict(
            con.execute("SELECT status, COUNT(*) FROM ocr_queue GROUP BY status").fetchall()
        )
        con.close()
    for name, path in [
        ("encrypted_queued", STATE / "encrypted_assets_queue.json"),
        ("secrets_candidates", STATE / "secrets_quarantine_candidates.json"),
    ]:
        if path.is_file():
            try:
                m[name] = json.loads(path.read_text(encoding="utf-8")).get("count")
            except Exception:
                m[name] = None
    # DLQ size
    if DLQ.is_file():
        m["dlq_lines"] = sum(1 for _ in DLQ.open(encoding="utf-8"))
    else:
        m["dlq_lines"] = 0
    return m


def heal(m: dict) -> list[str]:
    actions = []
    age = m.get("continuous_age_s")
    if age is not None and age > 900:
        try:
            subprocess.Popen(
                [PY, str(SCRIPTS / "silo_continuous_loop.py"), "--force-mode", "aggressive"],
                cwd=str(SCRIPTS),
                stdout=open(STATE / "silo_continuous.out", "a"),
                stderr=subprocess.STDOUT,
            )
            actions.append(f"restarted_continuous age={age}")
            dlq_append("control", "continuous", f"stale age={age}")
        except Exception as e:
            actions.append(f"restart_failed {e}")
            dlq_append("control", "continuous", str(e))
    else:
        actions.append(f"continuous_ok age={age}")
    # ensure password template exists
    pw = Path(r"D:\HermesData\config\archive_passwords.local.txt")
    if not pw.is_file():
        pw.write_text(
            "# Local passwords for YOUR encrypted files only. Never commit.\n",
            encoding="utf-8",
        )
        actions.append("created_password_template")
    return actions


def ensure_canon() -> None:
    if CANON.is_file():
        return
    CANON.write_text(
        """# Autonomy control plane (CANONICAL 2026-07-13)

Research: DLQ, fail-soft, observability, incremental/idempotent loads.

## Layers
1. **Land** — drain + hash skip (idempotent)
2. **Depth** — OCR, harvest, zip/tar eval
3. **Connect** — graph, PKO, dossiers
4. **Control** — metrics, DLQ, self-heal, heartbeats

## Dead letter queue
`state/silo_dead_letter_queue.jsonl` — failures that must not block the wave.
Pattern: retry N → DLQ → continue (never silent drop of important classes).

## Metrics
`state/silo_autonomy_metrics.json` + `.jsonl` history

## Heal rules
- continuous age > 900s → restart aggressive loop
- OCR queue starved → rediscover (self_heal_monitor)
- encrypted assets → stage queue (no crack)
- secrets → path quarantine → BW → purge gate

## Autonomy checklist (programmatic)
- [x] three data classes + never roots
- [x] hash differential
- [x] multi-provenance
- [x] music/ISO catalog-only
- [x] zip/tar/gz eval + harvest
- [x] encrypted stage + optional local passwords
- [x] secrets quarantine list
- [x] holistic coverage metrics
- [x] continuous + watchdog + travel heartbeat
- [ ] es.exe Everything CLI (when installed)
- [ ] 7zip/unrar for 7z/rar
- [ ] Jeff password file populated (optional)
""",
        encoding="utf-8",
    )


def main() -> int:
    ensure_canon()
    m = measure()
    actions = heal(m)
    m["actions"] = actions
    METRICS.write_text(json.dumps(m, indent=2), encoding="utf-8")
    with METRICS_HIST.open("a", encoding="utf-8") as f:
        f.write(json.dumps(m) + "\n")
    print(json.dumps({"metrics": {k: m.get(k) for k in (
        "registry", "unique", "continuous_age_s", "cycle", "ocr", "dlq_lines",
        "encrypted_queued", "actions",
    ) if k in m}, "actions": actions}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
