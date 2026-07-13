#!/usr/bin/env python3
"""Catalog game ISOs / disk images — do not bulk-ingest into silo."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOTS = [Path("G:/"), Path("D:/"), Path("K:/")]
EXTS = {".iso", ".vmdk", ".vdi", ".img", ".nrg", ".mds", ".mdf"}
OUT = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\Life-Archive\from-g-drive\_media_catalogs"
)
MAX = 5000


def main() -> int:
    found = []
    for root in ROOTS:
        if not root.exists():
            continue
        try:
            for p in root.rglob("*"):
                if not p.is_file():
                    continue
                if p.suffix.lower() not in EXTS:
                    continue
                # skip system
                low = str(p).lower()
                if any(x in low for x in ("\\windows\\", "\\program files", "$recycle")):
                    continue
                try:
                    found.append(
                        {
                            "path": str(p),
                            "name": p.name,
                            "ext": p.suffix.lower(),
                            "size_mb": round(p.stat().st_size / 1e6, 1),
                        }
                    )
                except OSError:
                    continue
                if len(found) >= MAX:
                    break
        except OSError:
            continue
        if len(found) >= MAX:
            break

    OUT.mkdir(parents=True, exist_ok=True)
    doc = {
        "policy": "catalog_only_no_bulk_iso_ingest",
        "at": datetime.now(timezone.utc).isoformat(),
        "count": len(found),
        "items": found,
    }
    (OUT / "catalog_isos_and_disk_images.json").write_text(
        json.dumps(doc, indent=2), encoding="utf-8"
    )
    lines = [f"# ISO/disk image catalog — {doc['at']}", f"count {len(found)}", ""]
    for it in found:
        lines.append(f"{it['size_mb']} MB\t{it['path']}")
    (OUT / "catalog_isos_and_disk_images.txt").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(json.dumps({"count": len(found), "out": str(OUT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
