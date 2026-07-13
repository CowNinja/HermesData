#!/usr/bin/env python3
"""Harvest small high-signal text from bulk trees (VMs, ISO dirs) without landing disks.

Does NOT print secret values. Flags credential-ish paths for Bitwarden quarantine list.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

HARVEST_EXT = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".log",
    ".env",
    ".ini",
    ".cfg",
    ".conf",
    ".yaml",
    ".yml",
    ".xml",
    ".pdf",
    ".docx",
}
SKIP_EXT = {
    ".vmdk",
    ".vdi",
    ".vhd",
    ".vhdx",
    ".qcow2",
    ".ova",
    ".iso",
    ".img",
    ".mp3",
    ".flac",
    ".exe",
    ".msi",
    ".dll",
    ".sys",
}
SECRET_NAME = re.compile(
    r"(password|passwd|secret|credential|api[_-]?key|token|private.?key|id_rsa|\.pem|\.ppk)",
    re.I,
)
MAX_BYTES = 5_000_000
DEFAULT_ROOTS = [
    Path(r"G:\VirtualBox VMs"),
    Path(r"G:\Users"),
    Path(r"D:\VirtualBox VMs"),
    Path(r"D:\VMs"),
    Path(r"G:\Alex"),
    Path(r"G:\Booksbloom"),
]
OUT = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\_Inbox\from-g-drive\_harvest_from_bulk"
)
QUAR_LIST = Path(r"D:\HermesData\state\secrets_quarantine_candidates.json")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    harvested = []
    secrets = []
    scanned = 0
    OUT.mkdir(parents=True, exist_ok=True)

    for root in DEFAULT_ROOTS:
        if not root.is_dir():
            continue
        try:
            for p in root.rglob("*"):
                if not p.is_file():
                    continue
                scanned += 1
                ext = p.suffix.lower()
                if ext in SKIP_EXT:
                    continue
                if ext not in HARVEST_EXT:
                    continue
                try:
                    sz = p.stat().st_size
                except OSError:
                    continue
                if sz <= 0 or sz > MAX_BYTES:
                    continue
                rel = p.name
                try:
                    rel = str(p.relative_to(root))
                except Exception:
                    pass
                item = {
                    "source": str(p),
                    "root": str(root),
                    "rel": rel,
                    "size": sz,
                    "secretish": bool(SECRET_NAME.search(p.name) or SECRET_NAME.search(str(p))),
                }
                if item["secretish"]:
                    secrets.append({"path": str(p), "size": sz, "seen_at": utc()})
                    # do not copy secrets into inbox training path by default
                    continue
                if args.apply and len(harvested) < args.limit:
                    dest = OUT / root.name / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if not dest.exists():
                        try:
                            shutil.copy2(p, dest)
                            meta = {
                                "source": str(p),
                                "harvest": "small_from_bulk",
                                "copied_at": utc(),
                            }
                            dest.with_suffix(dest.suffix + ".meta.json").write_text(
                                json.dumps(meta, indent=2), encoding="utf-8"
                            )
                        except Exception as e:
                            item["err"] = str(e)
                            continue
                harvested.append(item)
                if len(harvested) >= args.limit:
                    break
        except OSError:
            continue
        if len(harvested) >= args.limit:
            break

    # merge secret candidates (paths only)
    prev = []
    if QUAR_LIST.is_file():
        try:
            prev = json.loads(QUAR_LIST.read_text(encoding="utf-8")).get("items") or []
        except Exception:
            prev = []
    seen = {x.get("path") for x in prev}
    for s in secrets:
        if s["path"] not in seen:
            prev.append(s)
            seen.add(s["path"])
    QUAR_LIST.write_text(
        json.dumps(
            {
                "updated": utc(),
                "policy": "paths_only_no_secret_values_in_this_file",
                "count": len(prev),
                "items": prev[:2000],
                "next": "Jeff green light → Bitwarden import → verify → purge phrase",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "scanned_files_walk": scanned,
                "harvested": len(harvested),
                "secretish_paths": len(secrets),
                "apply": args.apply,
                "out": str(OUT),
                "quarantine_list": str(QUAR_LIST),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
