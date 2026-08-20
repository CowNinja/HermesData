#!/usr/bin/env python3
"""Holistic person dossier from contacts_db only.

Fail closed: UNKNOWN unless exact card match AND evidence.source + date.
Never reads entity_context.json (337 OCR names). Never fuzzy.
File-graph hub counts stay out of packs.

Usage:
  python person_dossier.py jeffrey_bloom
  python person_dossier.py --name "Jan Bloom"
  python person_dossier.py "Joseph Cagle" --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
sys.path.insert(0, str(SCRIPTS))
from contacts_db import (  # noqa: E402
    DB,
    find_person_exact,
    has_dated_evidence,
    load,
    rebuild_handles_active,
)


def pack_handles(p: dict) -> dict:
    handles = p.get("handles") or {}

    def rows(kind: str) -> list:
        out = []
        for h in handles.get(kind) or []:
            if isinstance(h, dict):
                out.append(
                    {
                        "value": h.get("value"),
                        "status": h.get("status"),
                        "confidence": (h.get("validity") or {}).get("confidence"),
                        "last_verified": (h.get("validity") or {}).get("last_verified"),
                        "method": (h.get("validity") or {}).get("method"),
                        "signals": (h.get("validity") or {}).get("signals"),
                    }
                )
            else:
                out.append({"value": h, "status": "legacy_string"})
        return out

    rebuild_handles_active(p)
    return {
        "email": rows("email"),
        "phone": rows("phone"),
        "active_summary": p.get("handles_active") or {},
        "historical_summary": p.get("handles_historical") or {},
    }


def dossier(cid: str, p: dict) -> dict:
    ledger = p.get("ledger") or []
    evidence = p.get("evidence") or []
    return {
        "lookup": "CARD",
        "canonical_id": cid,
        "canonical_name": p.get("canonical_name"),
        "roles": p.get("roles"),
        "domain_primary": p.get("domain_primary"),
        "confidence": p.get("confidence"),
        "relations": p.get("relations") or [],
        "name_variants": p.get("name_variants") or [],
        "handles": pack_handles(p),
        "ledger_tail": ledger[-15:],
        "ledger_count": len(ledger),
        "evidence_tail": evidence[-8:],
        "evidence_count": len(evidence),
        "bio": p.get("bio") or {},
        "note": (
            "Card facts only. File-graph / silo path-hits omitted. "
            "entity_context OCR names are not this card."
        ),
    }


def unknown(query: str, reason: str, **extra) -> dict:
    rec = {
        "lookup": "UNKNOWN",
        "query": query,
        "reason": reason,
        "entity_context": "ignored",
        "fuzzy": False,
    }
    rec.update(extra)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("who", nargs="?", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    key = args.who or args.name
    if not key:
        print(json.dumps({"error": "pass id or --name"}))
        return 1
    db = load()
    hit = find_person_exact(db, key)
    if not hit:
        rec = unknown(key, "not_on_card")
        print(json.dumps(rec, indent=2) if args.json else json.dumps(rec))
        return 2
    cid, p = hit
    if not has_dated_evidence(p):
        rec = unknown(key, "no_evidence_source_date", canonical_id=cid)
        print(json.dumps(rec, indent=2) if args.json else json.dumps(rec))
        return 2
    doc = dossier(cid, p)
    if args.json:
        print(json.dumps(doc, indent=2))
        return 0
    act = (doc["handles"].get("active_summary") or {})
    lines = [
        f"# Dossier: {doc['canonical_name']} (`{cid}`)",
        "",
        f"lookup: CARD | {doc.get('confidence')} | {doc.get('domain_primary')}",
        f"Roles: {', '.join(doc['roles'] or [])}",
        "",
        "## Active contact (Gmail From/To verified)",
        f"- emails: {act.get('email') or []}",
        f"- phones: {act.get('phone') or []}",
        "",
        "## All emails",
    ]
    for h in doc["handles"]["email"]:
        lines.append(
            f"- **{h.get('status')}** `{h.get('value')}` "
            f"verified={h.get('last_verified')} method={h.get('method')}"
        )
    lines += ["", f"## Ledger (last {len(doc['ledger_tail'])} of {doc['ledger_count']})", ""]
    for e in doc["ledger_tail"]:
        lines.append(
            f"- {e.get('action')} {e.get('kind')}: `{str(e.get('value'))[:80]}` "
            f"src={str(e.get('source'))[:60]}"
        )
    lines += ["", "## Relations", ""]
    for r in doc["relations"]:
        lines.append(f"- {r.get('type')} → `{r.get('to_id')}`")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
