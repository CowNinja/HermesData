#!/usr/bin/env python3
"""Hermes no_agent entry: model management full tick (--full-tick --summary)."""
from model_management_cron_bridge import run

if __name__ == "__main__":
    raise SystemExit(run("full"))
