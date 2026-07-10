#!/usr/bin/env python3
"""Pilot wave 3: small Medical highsignal folders → Medical-Records. Copy-only."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
SRC_ROOT = ROOT / "test-ingest-2026-06-25" / "root-highsignal-sample" / "Medical"
DEST = ROOT / "Medical-Records"
TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\k-pilot-wave3-receipt-latest.md")

# Small named folders / files only — broad dest, no rabbit-hole permanent homes
TARGETS = [
    "00 - medical USEFUL WEBSITES.doc",
    "2018-02-07 - NMCP Ombudsman FAQs(3 pages).pdf",
    "2017-11-05 @ 1111 - Bloom - Lower Body and Stability.docx",
]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in TARGETS:
        src = SRC_ROOT / name
        if not src.exists():
            rows.append(f"MISS `{name}`")
            continue
        out = DEST / name
        if out.exists():
            rows.append(f"SKIP `{name}`")
            continue
        shutil.copy2(src, out)
        meta = {
            "source": str(src),
            "dest": str(out),
            "sha256": sha256_file(out),
            "copied_at": TS,
            "pilot": "wave3-medical",
            "mode": "copy_only_broad",
        }
        out.with_suffix(out.suffix + ".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        rows.append(f"COPY `{name}` → Medical-Records/")

    RECEIPT.write_text(
        "\n".join(
            [
                f"# K Pilot Wave 3 (Medical tranche) — {TS}",
                "",
                *([f"- {r}" for r in rows]),
                "",
                "[[Operations/K-Silo-Holistic-Foundation-2026-07-10]]",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps({"rows": rows, "receipt": str(RECEIPT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
