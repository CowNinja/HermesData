#!/usr/bin/env bash
# Thin launcher — real work is backup-resilience.py v7 (Python-first).
# Cron job Hermes-Resilience-Backup uses script: backup-resilience.py (no_agent).
# This .sh exists only for legacy prompts / manual bash calls.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONUTF8=1
exec python "$ROOT/scripts/backup-resilience.py" "$@"
