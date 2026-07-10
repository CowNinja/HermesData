#!/usr/bin/env python3
"""Verify multi-part GGUF pairs on disk. Do NOT concatenate -- llama.cpp loads splits natively."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERMES_ROOT = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")
INVENTORY_PATH = Path(r"D:\PhronesisModels\model_inventory.json")
ACK_PATH = VAULT / "Operations" / "l04-split-gguf-ack.json"

SPLIT_RE = re.compile(r"^(.+)-(\d+)-of-(\d+)\.gguf$", re.IGNORECASE)


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def discover_split_pairs(gguf_truth: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Group split filenames by base prefix and total part count."""
    groups: Dict[str, Dict[str, Any]] = {}
    for fname in sorted(gguf_truth.keys()):
        m = SPLIT_RE.match(fname)
        if not m:
            continue
        prefix, part_s, total_s = m.group(1), int(m.group(2)), int(m.group(3))
        key = f"{prefix}-of-{total_s}"
        entry = groups.setdefault(
            key,
            {
                "pair_key": key,
                "prefix": prefix,
                "total_parts": total_s,
                "parts_found": [],
                "parts_missing": [],
                "complete": False,
                "tier": str((gguf_truth.get(fname) or {}).get("tier") or "unknown"),
            },
        )
        entry["parts_found"].append({"part": part_s, "filename": fname})

    for key, entry in groups.items():
        total = int(entry["total_parts"])
        found_nums = {int(p["part"]) for p in entry["parts_found"]}
        missing = [i for i in range(1, total + 1) if i not in found_nums]
        entry["parts_missing"] = [
            f"{entry['prefix']}-{i:05d}-of-{total:05d}.gguf" for i in missing
        ]
        entry["complete"] = len(missing) == 0
        entry["parts_found"] = sorted(entry["parts_found"], key=lambda x: x["part"])
    return sorted(groups.values(), key=lambda x: x["pair_key"])


def verify_and_ack(*, write_ack: bool = True) -> Dict[str, Any]:
    inv = _load_json(INVENTORY_PATH)
    gguf_truth = inv.get("gguf_truth") or {}
    pairs = discover_split_pairs(gguf_truth)
    ack = _load_json(ACK_PATH)
    verified = set(ack.get("verified_pairs") or [])

    complete_pairs = [p for p in pairs if p["complete"]]
    incomplete_pairs = [p for p in pairs if not p["complete"]]

    newly_acked: List[str] = []
    if write_ack:
        for p in complete_pairs:
            key = p["pair_key"]
            if key not in verified:
                verified.add(key)
                newly_acked.append(key)
        if newly_acked or complete_pairs:
            ack = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "verified_pairs": sorted(verified),
                "note": "llama.cpp loads split GGUF natively -- do not concatenate",
                "pairs": complete_pairs,
            }
            _save_json(ACK_PATH, ack)

    ok = len(incomplete_pairs) == 0
    return {
        "ok": ok,
        "action": "verify-split-gguf",
        "complete_count": len(complete_pairs),
        "incomplete_count": len(incomplete_pairs),
        "complete_pairs": complete_pairs,
        "incomplete_pairs": incomplete_pairs,
        "newly_acked": newly_acked,
        "ack_path": str(ACK_PATH),
        "hint": (
            "Split pairs verified for llama.cpp native load. L04 cleared for complete pairs."
            if ok
            else "Missing split parts detected -- download or repair before load."
        ),
    }


def main() -> int:
    payload = verify_and_ack(write_ack="--no-ack" not in sys.argv)
    print(json.dumps(payload))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())