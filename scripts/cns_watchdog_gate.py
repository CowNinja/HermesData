#!/usr/bin/env python3
"""CNS vault watchdog gate -- no_agent cron leaf (avoids LLM truncation)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERMES = Path(r"D:\HermesData")
VENV_PY = HERMES / "hermes-agent" / "venv" / "Scripts" / "python.exe"
CNS_TARGET = Path(r"K:\PhronesisVault")
INGESTOR = HERMES / "skills" / "cns_ingestor.py"
INDEX_OUT = HERMES / "PhronesisVault" / "index"


def main() -> int:
    if not CNS_TARGET.is_dir():
        print(f"[SKIP] CNS target not mounted: {CNS_TARGET}")
        return 0
    py = str(VENV_PY) if VENV_PY.is_file() else sys.executable
    proc = subprocess.run(
        [py, str(INGESTOR), "--target", str(CNS_TARGET), "--output", str(INDEX_OUT)],
        cwd=str(HERMES),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "CNS ingest failed")[-500:]
        print(tail)
        return proc.returncode
    out = (proc.stdout or "").strip()
    print(out[-300:] if out else "OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())