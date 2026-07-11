#!/usr/bin/env python3
"""Gateway boot entrypoint for stack integrity review.

Called by gateway/phronesis_boot_integrity.py at Hermes startup (startup probe).
Can also be run manually:

  python gateway_boot_integrity.py --mode fast
  python gateway_boot_integrity.py --mode full --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from stack_integrity_review import run_review  # noqa: E402


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gateway boot integrity probe")
    ap.add_argument("--mode", choices=("fast", "full"), default="fast")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)

    report = run_review(fast=args.mode == "fast")
    report["boot_probe"] = True
    report["mode"] = args.mode

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        label = "PASS" if report["ok"] else "FAIL"
        print(f"Gateway boot integrity ({args.mode}): {label}")
        for layer in report["layers"]:
            mark = "OK" if layer["ok"] else "FAIL"
            print(f"  [{mark}] {layer['layer']}: {layer['detail']}")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())