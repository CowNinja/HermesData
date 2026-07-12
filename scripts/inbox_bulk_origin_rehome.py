#!/usr/bin/env python3
"""Fast bulk re-home of K Inbox using origin-folder rules (no LLM).

Paperless-style path matching + medallion bronze→silver promotion.
Recursive. Preserves relative path under target shelf.
Default dry-run. --apply moves on K only.

Usage:
  python inbox_bulk_origin_rehome.py --limit 2000
  python inbox_bulk_origin_rehome.py --apply --limit 5000 --only amazon
  python inbox_bulk_origin_rehome.py --apply --limit 5000 --prefix "Phillips"
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(r"D:\HermesData\scripts")))
from domain_route import domain_for  # noqa: E402

SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
INBOX = SILO / "Core-Personal" / "_Inbox" / "from-g-drive"
RULES_PATH = Path(r"D:\HermesData\config\inbox_origin_rules.json")
DB = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\inbox-bulk-origin-rehome-latest.md")
SKIP_SUFFIXES = (
    ".meta.json",
    ".train.md",
    ".context.json",
    ".ocr.md",
    ".context.train.md",
    ".extract.json",
)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_rules() -> List[Dict[str, Any]]:
    data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return list(data.get("rules") or [])


def match_origin(path_str: str, rules: List[Dict[str, Any]]) -> Optional[Tuple[str, str]]:
    """Return (domain, rule_id) or None if no bulk rule.

    Rules with confidence=defer or domain=null are skipped (name/entity path later).
    First matching rule in file order wins.
    """
    low = path_str.replace("/", "\\").lower()
    for rule in rules:
        conf = (rule.get("confidence") or "").lower()
        if conf == "defer" or not rule.get("domain"):
            continue
        for sub in rule.get("match_any_path_substr") or []:
            s = sub.lower().replace("/", "\\")
            if s in low:
                return str(rule["domain"]), str(rule.get("id") or "rule")
    return None


def is_primary_file(p: Path) -> bool:
    name = p.name
    if name.startswith("00-INDEX"):
        return False
    for suf in SKIP_SUFFIXES:
        if name.endswith(suf) or name.endswith(suf + ".train.md"):
            return False
    if ".train." in name or name.endswith(".meta.json"):
        return False
    return p.is_file()


def iter_candidates(limit_scan: int, prefix: Optional[str]) -> List[Path]:
    out: List[Path] = []
    if not INBOX.is_dir():
        return out
    root = INBOX
    if prefix:
        # allow partial folder name match under inbox
        hits = [d for d in INBOX.iterdir() if d.is_dir() and prefix.lower() in d.name.lower()]
        if len(hits) == 1:
            root = hits[0]
        elif hits:
            # scan each
            for h in hits:
                for p in h.rglob("*"):
                    if is_primary_file(p):
                        out.append(p)
                        if len(out) >= limit_scan:
                            return out
            return out
    for p in root.rglob("*"):
        if is_primary_file(p):
            out.append(p)
            if len(out) >= limit_scan:
                break
    return out


def move_with_sidecars(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    # common sidecar patterns
    for suf in SKIP_SUFFIXES:
        for cand in (Path(str(src) + suf), src.with_suffix(src.suffix + suf)):
            if cand.is_file():
                try:
                    shutil.move(str(cand), str(dest) + suf if not str(dest).endswith(suf) else str(dest.parent / (dest.name + suf)))
                except Exception:
                    try:
                        shutil.move(str(cand), str(Path(str(dest) + suf)))
                    except Exception:
                        pass


def update_registry(src: str, dest: str, domain: str) -> None:
    if not DB.exists():
        return
    try:
        con = sqlite3.connect(str(DB))
        con.execute(
            "UPDATE ingest SET domain=?, dest_path=?, last_seen=? WHERE dest_path=?",
            (domain, dest, utc(), src),
        )
        con.commit()
        con.close()
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=2000, help="max files to MOVE/plan")
    ap.add_argument("--scan", type=int, default=0, help="max files to scan (default limit*20)")
    ap.add_argument("--prefix", type=str, default="", help="only under inbox folder name containing this")
    ap.add_argument("--only", type=str, default="", help="alias: amazon|cpap|medical|projects|contacts")
    ap.add_argument("--name-fallback", action="store_true", help="if no origin rule, try domain_for(name+path)")
    args = ap.parse_args()

    only_map = {
        "amazon": "Amazon",
        "cpap": "Phillips",
        "dream": "Dream",
        "medical": "Medical",
        "projects": "Projects",
        "contacts": "Contacts",
        "ancestry": "Ancestry",
        "ifttt": "IFTTT",
        "gmail": "Gmail",
    }
    prefix = args.prefix
    if args.only:
        prefix = only_map.get(args.only.lower(), args.only)

    rules = load_rules()
    scan_n = args.scan or max(args.limit * 25, 5000)
    files = iter_candidates(scan_n, prefix or None)

    planned: List[Dict[str, Any]] = []
    stay = 0
    for p in files:
        try:
            rel = p.relative_to(INBOX)
        except Exception:
            stay += 1
            continue
        path_blob = str(p)
        hit = match_origin(path_blob, rules)
        domain = None
        why = "stay"
        if hit:
            domain, rid = hit
            why = f"origin_rule:{rid}"
        elif args.name_fallback:
            d = domain_for(p.name, str(rel))
            if d and "Inbox" not in d:
                domain = d
                why = "name_path_fallback"
        if not domain or "Inbox" in domain:
            stay += 1
            continue
        dest = SILO / domain / "from-g-drive" / rel
        if dest.exists():
            # content-address collision: suffix
            digest = __import__("hashlib").sha256(str(p).encode()).hexdigest()[:8]
            dest = dest.with_name(f"{dest.stem}__{digest}{dest.suffix}")
        planned.append(
            {
                "src": str(p),
                "dest": str(dest),
                "domain": domain,
                "why": why,
                "rel": str(rel),
            }
        )
        if len(planned) >= args.limit:
            break

    applied = 0
    errors = 0
    if args.apply:
        for m in planned:
            try:
                move_with_sidecars(Path(m["src"]), Path(m["dest"]))
                update_registry(m["src"], m["dest"], m["domain"])
                # context crumb
                try:
                    Path(str(m["dest"]) + ".context.json").write_text(
                        json.dumps(
                            {
                                "rehomed_from_inbox": True,
                                "why": m["why"],
                                "domain": m["domain"],
                                "method": "inbox_bulk_origin_rehome",
                                "at": utc(),
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
                applied += 1
            except Exception as e:
                m["error"] = str(e)
                errors += 1

    # domain tally
    from collections import Counter

    by_dom = Counter(m["domain"] for m in planned)
    by_why = Counter(m["why"] for m in planned)

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Inbox bulk origin re-home — {utc()}",
        "",
        f"**Mode:** {'APPLY' if args.apply else 'DRY-RUN'}",
        f"**Scanned candidates:** {len(files)} · **planned:** {len(planned)} · **applied:** {applied} · **errors:** {errors} · **stay_seen:** {stay}",
        f"**Prefix/only:** `{prefix or '(all)'}`",
        f"**By domain:** {dict(by_dom)}",
        f"**By why:** {dict(by_why)}",
        "",
        "| Domain | Why | Rel |",
        "|--------|-----|-----|",
    ]
    for m in planned[:40]:
        lines.append(f"| {m['domain']} | {m['why']} | `{m['rel'][:70]}` |")
    lines += [
        "",
        "[[Operations/Inbox-Sorting-Research-and-Bulk-Origin-CANONICAL-2026-07-12]]",
        "",
    ]
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")

    print(
        json.dumps(
            {
                "apply": args.apply,
                "scanned": len(files),
                "planned": len(planned),
                "applied": applied,
                "errors": errors,
                "stay_sampled": stay,
                "by_domain": dict(by_dom),
                "by_why": dict(by_why),
                "prefix": prefix or None,
                "receipt": str(RECEIPT),
            },
            indent=2,
        )
    )
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
