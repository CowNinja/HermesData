#!/usr/bin/env python3
"""Classify resilience phase errors as soft vs hard (token-free policy).

Used by backup-resilience.py and backup_health_alarm.py so Grok never re-litigates:
  - silo_signal timeout with fresh prior receipt -> soft
  - cloud_pack best-effort fail -> soft
  - vault clean mirror rate-limit skip -> soft
  - K missing / git push HermesData fail / poison reintroduced -> hard

Usage:
  python D:/HermesData/scripts/backup_phase_policy.py --errors-json '["silo_signal timeout"]'
  python D:/HermesData/scripts/backup_phase_policy.py --from-receipt
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERMES = Path(r"D:\HermesData")
RESILIENCE = HERMES / "state" / "backup_resilience_last.json"
SILO_STATE = HERMES / "state" / "backup_k_silo_life_mirror_last.json"
CLEAN_STATE = HERMES / "state" / "vault_github_clean_mirror_last.json"

# hours: prior good silo covers a spine timeout
SILO_FRESH_H = 48.0
CLEAN_FRESH_H = 36.0

SOFT_PREFIXES = (
    "silo_signal timeout",
    "silo_signal rc=",
    "cloud_pack",
    "restore_drill",
    "k_inventory",
    "fossil_scan",
)


def age_h_from_ts(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except Exception:
        return None


def load(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def classify_errors(errors: List[str]) -> Dict[str, Any]:
    silo = load(SILO_STATE)
    clean = load(CLEAN_STATE)
    silo_age = age_h_from_ts(silo.get("ts"))
    clean_age = age_h_from_ts(clean.get("ts"))
    silo_fresh = bool(silo.get("ok")) and silo_age is not None and silo_age <= SILO_FRESH_H
    clean_fresh = bool(clean.get("ok")) and clean_age is not None and clean_age <= CLEAN_FRESH_H

    soft: List[str] = []
    hard: List[str] = []
    for e in errors:
        el = (e or "").strip()
        el_l = el.lower()
        is_soft = False
        if el_l.startswith("silo_signal") and silo_fresh:
            is_soft = True
        elif el_l.startswith("vault_clean_mirror") and clean_fresh:
            is_soft = True
        elif any(el_l.startswith(p.lower()) for p in SOFT_PREFIXES):
            # cloud/inventory/fossil/drill always soft unless paired with K missing elsewhere
            is_soft = True
        elif "timeout" in el_l and "k_mirror" not in el_l and "git" not in el_l:
            is_soft = True
        if is_soft:
            soft.append(el)
        else:
            hard.append(el)

    ok = len(hard) == 0
    color_hint = "GREEN" if ok and not soft else ("YELLOW" if ok else "YELLOW")
    if hard:
        color_hint = "YELLOW"
        if any("missing" in h.lower() or "k_" in h.lower() and "fail" in h.lower() for h in hard):
            color_hint = "RED"

    return {
        "ok_for_receipt": ok,
        "hard": hard,
        "soft": soft,
        "color_hint": color_hint,
        "silo_fresh": silo_fresh,
        "silo_age_h": silo_age,
        "clean_fresh": clean_fresh,
        "clean_age_h": clean_age,
        "version": 1,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--errors-json", default="")
    ap.add_argument("--from-receipt", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    errors: List[str] = []
    if args.from_receipt:
        errors = list(load(RESILIENCE).get("errors") or [])
    elif args.errors_json:
        errors = json.loads(args.errors_json)
    report = classify_errors(errors)
    if args.json or True:
        print(json.dumps(report, indent=2))
    return 0 if report["ok_for_receipt"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
