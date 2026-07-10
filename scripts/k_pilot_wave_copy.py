#!/usr/bin/env python3
"""K silo pilot wave — COPY ONLY with provenance. No deletes.

Organization principle (Jeff 2026-07-10):
  Broad Google Drive–style subsilos — NOT deep rabbit-hole pilot folders.
  Prefer: Medical-Records/Diagnosis-History, Core-Personal/Finance/Navy-Cash
  Avoid: pilot-YYYY-MM-DD/ultra-specific-name nests as permanent homes.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
TI = ROOT / "test-ingest-2026-06-25"
TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\k-pilot-wave-receipt-latest.md")
RECEIPT_JSON = Path(r"D:\HermesData\logs\k-pilot-wave-receipt-latest.json")

# Broad destinations only (expand this list carefully)
PILOTS = [
    {
        "src": TI / "root-highsignal-sample" / "Medical" / "medical & dental record" / "Diagnosis History",
        "dest": ROOT / "Medical-Records" / "Diagnosis-History",
        "bucket": "Medical-Records/Diagnosis-History",
    },
    {
        "src": TI / "root-highsignal-sample" / "Pers" / "Finance" / "Navy Cash MasterCard Debit card",
        "dest": ROOT / "Core-Personal" / "Finance" / "Navy-Cash",
        "bucket": "Core-Personal/Finance/Navy-Cash",
    },
]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_tree(src: Path, dest: Path, bucket: str) -> list[dict]:
    rows: list[dict] = []
    if not src.exists():
        return [{"error": f"missing src {src}", "bucket": bucket}]
    dest.mkdir(parents=True, exist_ok=True)
    for f in src.rglob("*"):
        if not f.is_file():
            continue
        if f.name.lower() == "desktop.ini":
            continue
        name = f.name
        out = dest / name
        if out.exists():
            rows.append({"path": name, "action": "skip_exists", "bucket": bucket})
            continue
        shutil.copy2(f, out)
        digest = sha256_file(out)
        meta = {
            "source": str(f),
            "dest": str(out),
            "sha256": digest,
            "copied_at": TS,
            "pilot": "k-pilot-wave-broad",
            "bucket": bucket,
            "mode": "copy_only_no_delete_broad_subsilo",
        }
        meta_path = out.with_suffix(out.suffix + ".meta.json")
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        rows.append({"path": name, "action": "copied", "sha256": digest[:16], "bucket": bucket})
    return rows


def main() -> int:
    all_rows: list[dict] = []
    for p in PILOTS:
        all_rows.extend(copy_tree(p["src"], p["dest"], p["bucket"]))
    copied = sum(1 for r in all_rows if r.get("action") == "copied")
    skipped = sum(1 for r in all_rows if r.get("action") == "skip_exists")
    errors = [r for r in all_rows if r.get("error")]

    RECEIPT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": TS,
        "copied": copied,
        "skipped": skipped,
        "errors": errors,
        "rows": all_rows,
        "organization": "broad_subsilos_google_drive_style",
        "pilots": [{k: str(v) if isinstance(v, Path) else v for k, v in p.items()} for p in PILOTS],
    }
    RECEIPT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        f"# K Pilot Wave Receipt — {TS}",
        "",
        "**Mode:** COPY ONLY · provenance · **broad subsilos** (no rabbit holes)",
        f"**Copied:** {copied} · **Skipped:** {skipped} · **Errors:** {len(errors)}",
        "",
        "## Broad destinations",
    ]
    for p in PILOTS:
        lines.append(f"- `{p['bucket']}`")
    lines += [
        "",
        "## Principle",
        "Organize like Google Drive: few general folders, not hyper-specific nests.",
        "",
        "## Links",
        "- [[Operations/logs/k-silo-organization-principles]]",
        "- [[Operations/logs/lesson-pilot-k-wave-automation]]",
        "",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"copied": copied, "skipped": skipped, "errors": len(errors)}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
