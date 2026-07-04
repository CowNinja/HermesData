#!/usr/bin/env python3
"""Launch RP batch via orchestrator with JSON spec file (ASCII-safe, no shell escaping)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCH = Path(__file__).resolve().parent / "rp_batch_orchestrator.py"
PY = ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", nargs="?", default="")
    parser.add_argument("--spec-file", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    spec: dict = {}
    if args.spec_file:
        spec = json.loads(Path(args.spec_file).read_text(encoding="utf-8-sig"))

    cmd = [str(PY), str(ORCH)]
    if args.prompt:
        cmd.append(args.prompt)
    if spec:
        cmd.extend(["--spec-json", json.dumps(spec, ensure_ascii=True)])
    if args.dry_run:
        cmd.append("--dry-run")

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.stdout:
        print(proc.stdout.strip())
    if proc.stderr:
        print(proc.stderr.strip(), file=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())