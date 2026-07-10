#!/usr/bin/env python3
"""Pilot wave 2: copy named high-signal files into broad domains. No deletes."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
TI = ROOT / "test-ingest-2026-06-25" / "root-highsignal-sample"
TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\k-pilot-wave2-receipt-latest.md")

# (relative under highsignal, dest domain folder)
ITEMS = [
    ("Pers/2007-07-30 - Letter from dad.pdf", ROOT / "Core-Personal" / "Family"),
    ("Pers/2012-01-11 - Grandma Goldy Letter (6 Pages).pdf", ROOT / "Core-Personal" / "Family"),
    ("Pers/2017-09-10 - Sermon.m4a", ROOT / "Core-Personal" / "Spiritual"),
    ("Pers/2015-05-15 - DD2875 VULNERABILITY MANAGEMENT SYSTEM (VMS) IT1 BLOOM.pdf", ROOT / "Navy-Service" / "Service-Records"),
    ("Medical/2018-02-27 - DD2870, DEC 2003 - Authorization for Disclosure of Medical or Dental Information.pdf", ROOT / "Medical-Records"),
    ("Medical/2016-08-05 - DD1172-2, JAN 2014 Application For Identification Card-DEERS Enrollment.pdf", ROOT / "Medical-Records"),
    ("0000 - Jeffrey Bloom Income & expenses Summary.xlsx", ROOT / "Core-Personal" / "Finance"),
    ("002 JeffGenome merged ClinVar Report SequencingCom.xlsx", ROOT / "Medical-Records"),
    ("1 Corinthians 1-10-17.gdoc", ROOT / "Core-Personal" / "Spiritual"),
    ("051456Z APR 20 NAVADMIN 100 20  .gdoc", ROOT / "Navy-Service" / "Awards-and-Orders"),
]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    rows = []
    for rel, dest in ITEMS:
        src = TI / rel
        dest.mkdir(parents=True, exist_ok=True)
        if not src.exists():
            rows.append(f"MISS `{rel}`")
            continue
        out = dest / src.name
        if out.exists():
            rows.append(f"SKIP exists `{src.name}` → `{dest.relative_to(ROOT)}`")
            continue
        shutil.copy2(src, out)
        digest = sha256_file(out)
        meta = {
            "source": str(src),
            "dest": str(out),
            "sha256": digest,
            "copied_at": TS,
            "pilot": "k-pilot-wave2-named",
            "mode": "copy_only_broad_domain",
        }
        out.with_suffix(out.suffix + ".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        rows.append(f"COPY `{src.name}` → `{dest.relative_to(ROOT)}`")

    RECEIPT.write_text(
        "\n".join(
            [
                f"# K Pilot Wave 2 — {TS}",
                "",
                "Named high-signal files → **broad domains** (open taxonomy).",
                "",
                *([f"- {r}" for r in rows]),
                "",
                "[[Operations/K-Silo-Holistic-Foundation-2026-07-10]]",
                "[[Operations/K-Life-Domain-Taxonomy-CANONICAL-2026-07-10]]",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps({"rows": len(rows), "receipt": str(RECEIPT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
