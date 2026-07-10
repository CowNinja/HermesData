#!/usr/bin/env python3
"""Resolve path → data class from touch_policy_registry.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REG = Path(r"D:\HermesData\config\touch_policy_registry.json")


def load() -> dict:
    return json.loads(REG.read_text(encoding="utf-8"))


def classify(path: str | Path, reg: dict | None = None) -> tuple[int, str]:
    reg = reg or load()
    p = str(Path(path)).replace("/", "\\")
    best = None
    best_len = -1
    for row in reg.get("path_prefixes", []):
        pref = row["prefix"].replace("/", "\\")
        if p.lower().startswith(pref.lower()) and len(pref) > best_len:
            best = row
            best_len = len(pref)
    if best:
        return int(best["class"]), best.get("note", "")
    return int(reg.get("default_unknown", 3)), "unknown→default"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: touch_policy.py <path> [<path>...]")
        return 2
    reg = load()
    for a in sys.argv[1:]:
        c, note = classify(a, reg)
        print(f"{c}\t{note}\t{a}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
