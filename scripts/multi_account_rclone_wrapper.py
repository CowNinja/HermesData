#!/usr/bin/env python3
"""
DEPRECATED: Multi-account rclone wrapper (legacy).

This has been replaced by the robust production orchestrator:
    scripts/multi_account_ingest_orchestrator.py

It now forwards to the new script for backward compatibility.
New features (provenance in every manifest entry, auto-walker, config, dry-run, etc.)
live in the orchestrator.

Run the new one directly for all future work.
"""

from pathlib import Path
import subprocess
import sys

if __name__ == "__main__":
    print("WARNING: multi_account_rclone_wrapper.py is deprecated.")
    print("Please use: python scripts/multi_account_ingest_orchestrator.py [args]")
    print("See the new script for --help, --dry-run, --config, provenance, auto discovery_walker etc.")
    orchestrator = Path(__file__).parent / "multi_account_ingest_orchestrator.py"
    if orchestrator.exists():
        cmd = [sys.executable, str(orchestrator)] + sys.argv[1:]
        print("Forwarding to:", " ".join(cmd))
        sys.exit(subprocess.call(cmd))
    else:
        print("Orchestrator not found. Please create/run manually.")
        sys.exit(1)
