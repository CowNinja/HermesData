#!/usr/bin/env python3
"""
Thin wrapper for the extract-wisdom cron job.
Runs the actual extractor with proper flags so it does real work
instead of printing help.
"""

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TARGET = SCRIPT_DIR / "extract_wisdom.py"

def main():
    if not TARGET.exists():
        print(f"ERROR: {TARGET} not found")
        sys.exit(1)

    # Run the two main scan modes as described in the job prompt
    commands = [
        [sys.executable, str(TARGET), "--scan-sessions", "--limit", "30"],
        [sys.executable, str(TARGET), "--scan-errors"],
    ]

    for cmd in commands:
        print(f"Running: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            print(result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            if result.returncode != 0:
                print(f"WARNING: command exited with {result.returncode}")
        except Exception as e:
            print(f"ERROR running {cmd}: {e}")

    print("Extract-wisdom wrapper completed.")

if __name__ == "__main__":
    main()
