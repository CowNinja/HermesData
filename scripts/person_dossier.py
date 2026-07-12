#!/usr/bin/env python3
"""Holistic person dossier: identity + validity handles + ledger + silo hits.

Usage:
  python person_dossier.py jeffrey_bloom
  python person_dossier.py --name "Jan Bloom"
  python person_dossier.py gary_bloom --json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

DB = Path(r"D:\HermesData\state\contacts_db.json")
REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def find_person(db: dict, key: str) -> tuple[str, dict] | None:
    people = db.get("people") or {}
    if key in people:
        return key, people[key]
    nk = norm(key)
    for cid, p in people.items():
        names = [p.get("canonical_name"), cid.replace("_", " "), *(p.get("name_variants") or [])]
        for n in names:
            if n and norm(str(n)) == nk:
                return cid, p
            if n and nk in norm(str(n)) and len(nk) >= 4:
                return cid, p
    return None


def extra_registry_hits(p: dict, limit: int = 8) -> list:
    if not REG.exists():
        return []
    toks = []
    for n in [p.get("canonical_name"), *(p.get("name_variants") or [])][:5]:
        if n and len(str(n)) >= 5:
            toks.append(str(n).lower())
    for h in (p.get("handles") or {}).get("email") or []:
        if isinstance(h, dict) and h.get("status") == "active" and h.get("value"):
            toks.append(str(h["value"]).lower())
    if not toks:
        return []
    con = sqlite3.connect(str(REG))
    hits = []
    seen = set()
    for t in toks[:6]:
        for row in con.execute(
            "SELECT dest_path, domain, process_status FROM ingest WHERE lower(dest_path) LIKE ? LIMIT 5",
            (f"%{t}%",),
        ):
            if row[0] in seen:
                continue
            seen.add(row[0])
            hits.append({"path": row[0], "domain": row[1], "process_status": row[2]})
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break
    con.close()
    return hits


def dossier(cid: str, p: dict) -> dict:
    handles = p.get("handles") or {}

    def pack(kind: str):
        rows = []
        for h in handles.get(kind) or []:
            if isinstance(h, dict):
                rows.append(
                    {
                        "value": h.get("value"),
                        "status": h.get("status"),
                        "confidence": (h.get("validity") or {}).get("confidence"),
                        "signals": (h.get("validity") or {}).get("signals"),
                        "first_seen": h.get("first_seen"),
                        "last_seen": h.get("last_seen"),
                    }
                )
            else:
                rows.append({"value": h, "status": "legacy_string"})
        return rows

    ledger = p.get("ledger") or []
    return {
        "canonical_id": cid,
        "canonical_name": p.get("canonical_name"),
        "roles": p.get("roles"),
        "domain_primary": p.get("domain_primary"),
        "confidence": p.get("confidence"),
        "relations": p.get("relations") or [],
        "name_variants": p.get("name_variants") or [],
        "handles": {
            "email": pack("email"),
            "phone": pack("phone"),
            "address": pack("address"),
            "active_summary": p.get("handles_active"),
            "historical_summary": p.get("handles_historical"),
        },
        "ledger_tail": ledger[-15:],
        "ledger_count": len(ledger),
        "silo_links": p.get("silo_links") or {},
        "registry_hits_live": extra_registry_hits(p),
        "bio": p.get("bio") or {},
        "note": "Historical handles retained for synaptic connections; status marks validity.",
    }


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
    db = json.loads(DB.read_text(encoding="utf-8"))
    hit = find_person(db, key)
    if not hit:
        print(json.dumps({"error": "not found", "query": key}))
        return 2
    cid, p = hit
    doc = dossier(cid, p)
    if args.json:
        print(json.dumps(doc, indent=2))
        return 0
    # human markdown-ish
    lines = [
        f"# Dossier: {doc['canonical_name']} (`{cid}`)",
        "",
        f"Roles: {', '.join(doc['roles'] or [])} · Domain: {doc['domain_primary']} · {doc['confidence']}",
        "",
        "## Active contact",
        "",
    ]
    act = (doc["handles"].get("active_summary") or {})
    lines.append(f"- emails: {act.get('email') or []}")
    lines.append(f"- phones: {act.get('phone') or []}")
    lines += ["", "## All emails (validity)", ""]
    for h in doc["handles"]["email"]:
        lines.append(f"- **{h.get('status')}** `{h.get('value')}` · {h.get('confidence')} · {h.get('signals')}")
    lines += ["", "## All phones (validity)", ""]
    for h in doc["handles"]["phone"]:
        lines.append(f"- **{h.get('status')}** `{h.get('value')}` · {h.get('confidence')}")
    lines += ["", f"## Ledger (last {len(doc['ledger_tail'])} of {doc['ledger_count']})", ""]
    for e in doc["ledger_tail"]:
        lines.append(f"- {e.get('action')} {e.get('kind')}: `{str(e.get('value'))[:80]}` ← {str(e.get('source'))[:60]}")
    lines += ["", "## Silo connections", ""]
    for path in (doc.get("silo_links") or {}).get("sample_paths") or []:
        lines.append(f"- `{path}`")
    for h in doc.get("registry_hits_live") or []:
        lines.append(f"- [{h.get('domain')}] `{h.get('path')}`")
    lines += ["", "## Relations", ""]
    for r in doc["relations"]:
        lines.append(f"- {r.get('type')} → `{r.get('to_id')}`")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
