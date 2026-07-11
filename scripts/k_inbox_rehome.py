#!/usr/bin/env python3
"""Re-home K silo _Inbox/from-g-drive files using current domain_route + entity lexicon.

Copy-within-K only (no source purge). Updates .meta.json if present.
Default: dry-run. --apply to move.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\HermesData\scripts")))
from domain_route import domain_for  # noqa: E402
try:
    from ingest_registry import connect as reg_connect
except Exception:
    reg_connect = None

INBOX = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\_Inbox\from-g-drive"
)
SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\k-inbox-rehome-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()
    if not INBOX.is_dir():
        print(json.dumps({"error": "no inbox"}))
        return 1

    moved = skipped = 0
    rows = []
    for p in sorted(INBOX.iterdir()):
        if not p.is_file():
            continue
        if p.name.endswith(".meta.json") or ".train." in p.name:
            continue
        dom = domain_for(p.name)
        if dom.endswith("_Inbox"):
            skipped += 1
            continue
        dest = SILO / dom / "from-g-drive" / p.name
        status = "planned"
        if dest.exists():
            status = "skip-dest-exists"
            skipped += 1
        elif args.apply:
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(dest))
                meta = Path(str(p) + ".meta.json")
                # meta may be name.ext.meta.json
                meta2 = p.with_suffix(p.suffix + ".meta.json")
                for m in (meta, meta2):
                    if m.exists():
                        mdest = dest.with_suffix(dest.suffix + ".meta.json")
                        shutil.move(str(m), str(mdest))
                        try:
                            data = json.loads(mdest.read_text(encoding="utf-8"))
                            data["rehomed_to"] = str(dest)
                            data["rehomed_domain"] = dom
                            data["rehomed_at"] = utc()
                            mdest.write_text(json.dumps(data, indent=2), encoding="utf-8")
                        except Exception:
                            pass
                status = "moved"
                moved += 1
                if reg_connect:
                    try:
                        icon = reg_connect()
                        icon.execute(
                            "UPDATE ingest SET dest_path=? WHERE dest_path=?",
                            (str(dest), str(p)),
                        )
                        icon.commit()
                    except Exception:
                        pass
            except Exception as e:
                status = f"ERR {e}"
        else:
            status = f"would→{dom}"
            moved += 1  # count would-move
        rows.append((p.name[:50], dom, status))
        if (moved if args.apply else len(rows)) >= args.limit and args.apply:
            break
        if not args.apply and len([r for r in rows if r[2].startswith("would")]) >= args.limit:
            break

    lines = [
        f"# K Inbox re-home — {utc()}",
        f"**Mode:** {'APPLY' if args.apply else 'DRY-RUN'}",
        f"moved/would={moved} skipped={skipped}",
        "",
        "| File | Domain | Status |",
        "|------|--------|--------|",
    ]
    for name, dom, st in rows[:80]:
        lines.append(f"| `{name}` | {dom} | {st} |")
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "moved_or_would": moved,
                "skipped": skipped,
                "receipt": str(RECEIPT),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
