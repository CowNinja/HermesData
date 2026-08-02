#!/usr/bin/env python3
"""Fast K: inventory snapshot - no deep du of silo trees.

Top-level + Hermes-Resilience first-level sizes only (Windows dir /s would hang).
Uses shutil.disk_usage + bounded os.scandir.

Writes:
  K:/Hermes-Resilience/manifests/k-inventory-last.json
  D:/HermesData/state/k_inventory_last.json

Research: capacity planning without full tree walk; Microsoft Get-PSDrive pattern
 shutil.disk_usage; avoid recursive du on multi-TB silo (pitfall: 180s+ hangs).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HERMES = Path(r"D:\HermesData")
K = Path(r"K:\\")
K_ROOT = Path(r"K:\Hermes-Resilience")
STATE = HERMES / "state" / "k_inventory_last.json"
MAN = K_ROOT / "manifests" / "k-inventory-last.json"


def entry_size(path: Path, file_cap: int = 5000) -> Dict[str, Any]:
    """Bounded size estimate for a top-level entry."""
    if not path.exists():
        return {"exists": False}
    try:
        if path.is_file():
            return {"exists": True, "kind": "file", "bytes": path.stat().st_size}
    except OSError as e:
        return {"exists": True, "error": str(e)[:120]}

    total = 0
    files = 0
    dirs = 0
    truncated = False
    try:
        for root, dirnames, filenames in os.walk(path):
            dirs += len(dirnames)
            for fn in filenames:
                fp = Path(root) / fn
                try:
                    total += fp.stat().st_size
                    files += 1
                except OSError:
                    continue
                if files >= file_cap:
                    truncated = True
                    dirnames.clear()
                    break
            if truncated:
                break
            # don't descend forever into resilience mirrors only one level deeper for huge roots
            depth = len(Path(root).relative_to(path).parts) if root != str(path) else 0
            if depth >= 2 and path.name in {"Phronesis-Sovereign", "HermesData", "PhronesisVault"}:
                dirnames.clear()
    except OSError as e:
        return {"exists": True, "kind": "dir", "error": str(e)[:120]}
    return {
        "exists": True,
        "kind": "dir",
        "bytes": total,
        "files_seen": files,
        "dirs_seen": dirs,
        "truncated": truncated,
        "gb": round(total / (1024**3), 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--deep-resilience", action="store_true", help="size Hermes-Resilience children")
    args = ap.parse_args()
    ts = datetime.now(timezone.utc).isoformat()

    if not Path("K:/").exists() and not K_ROOT.exists():
        payload = {"ts": ts, "ok": False, "error": "K_missing"}
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print("FAIL K missing", file=sys.stderr)
        return 1

    u = shutil.disk_usage("K:\\")
    usage = {
        "total_tb": round(u.total / 1024**4, 3),
        "free_tb": round(u.free / 1024**4, 3),
        "used_tb": round((u.total - u.free) / 1024**4, 3),
        "used_pct": round(100.0 * (u.total - u.free) / u.total, 2),
    }

    top: Dict[str, Any] = {}
    try:
        with os.scandir("K:\\") as it:
            for ent in it:
                if ent.name.startswith("$") or ent.name in {"System Volume Information", "nul"}:
                    continue
                # lightweight: only mark presence + is_dir; deep size optional
                try:
                    top[ent.name] = {
                        "is_dir": ent.is_dir(follow_symlinks=False),
                        "is_file": ent.is_file(follow_symlinks=False),
                    }
                except OSError as e:
                    top[ent.name] = {"error": str(e)[:80]}
    except OSError as e:
        top["_error"] = str(e)[:120]

    resilience_children: Dict[str, Any] = {}
    if args.deep_resilience and K_ROOT.is_dir():
        try:
            with os.scandir(K_ROOT) as it:
                for ent in it:
                    p = Path(ent.path)
                    if ent.is_file(follow_symlinks=False):
                        try:
                            resilience_children[ent.name] = {
                                "kind": "file",
                                "bytes": ent.stat().st_size,
                                "gb": round(ent.stat().st_size / (1024**3), 3),
                            }
                        except OSError:
                            pass
                    else:
                        # one-level file sum only
                        b = 0
                        n = 0
                        try:
                            for root, dns, fns in os.walk(p):
                                for fn in fns:
                                    try:
                                        b += (Path(root) / fn).stat().st_size
                                        n += 1
                                    except OSError:
                                        continue
                                    if n >= 20000:
                                        dns.clear()
                                        break
                                # depth cap 3 under each child
                                try:
                                    if len(Path(root).relative_to(p).parts) >= 3:
                                        dns.clear()
                                except ValueError:
                                    pass
                        except OSError:
                            pass
                        resilience_children[ent.name] = {
                            "kind": "dir",
                            "bytes": b,
                            "gb": round(b / (1024**3), 3),
                            "files_seen": n,
                        }
        except OSError as e:
            resilience_children["_error"] = str(e)[:120]

    # quick known hot paths presence
    hot = {
        "silo": (Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")).is_dir(),
        "hermes_resilience": K_ROOT.is_dir(),
        "mirrors": (K_ROOT / "mirrors").is_dir(),
        "quarantine_fossils": (K_ROOT / "Quarantine" / "fossils").is_dir(),
        "pre_purge_bundle": any((K_ROOT / "restore" / "pre-purge-20260802").glob("*.bundle"))
        if (K_ROOT / "restore" / "pre-purge-20260802").is_dir()
        else False,
    }

    payload = {
        "ts": ts,
        "ok": True,
        "usage": usage,
        "top_level": top,
        "hot_paths": hot,
        "resilience_children": resilience_children or None,
        "version": 1,
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        MAN.parent.mkdir(parents=True, exist_ok=True)
        MAN.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"K inventory ok free_tb={usage['free_tb']} used_pct={usage['used_pct']} "
            f"top={len(top)} silo={hot['silo']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
