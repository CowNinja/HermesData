#!/usr/bin/env python3
"""Enrich contacts_db from Bitwarden safe inventory (no passwords).

Attaches email-like usernames and notable hosts to matching people.
Only non-secret fields. Jeff-approved dossier densification.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

SAFE = Path(r"D:\HermesData\state\secrets-work\bw-items-safe.json")
CONTACTS = Path(r"D:\HermesData\state\contacts_db.json")
EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I)

# map username/email fragments -> contacts_db id
SELF_HINTS = {
    "jeffrey.j.bloom@gmail.com",
    "mr.jeffrey.j.bloom@gmail.com",
    "warz123456789012@gmail.com",
    "jbloo005@odu.edu",
    "jj_bloom",
    "cowninja",
    "jeffrey.j.bloom",
    "mr.jeffrey.j.bloom",
}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    if not SAFE.is_file() or not CONTACTS.is_file():
        print(json.dumps({"error": "missing_files"}))
        return 2
    items = json.loads(SAFE.read_text(encoding="utf-8"))
    db = json.loads(CONTACTS.read_text(encoding="utf-8"))
    people = db.setdefault("people", {})
    jeff = people.setdefault(
        "jeffrey_bloom",
        {"canonical_id": "jeffrey_bloom", "canonical_name": "Jeffrey Jay Bloom", "handles": []},
    )
    raw_h = jeff.get("handles")
    if isinstance(raw_h, dict):
        handles = []
        for k, v in raw_h.items():
            if isinstance(v, dict):
                handles.append({"type": k, **v})
            else:
                handles.append({"type": k, "value": v})
        jeff["handles"] = handles
    elif isinstance(raw_h, list):
        handles = raw_h
    else:
        handles = []
        jeff["handles"] = handles
    existing = set()
    for h in handles:
        if not isinstance(h, dict):
            continue
        v = h.get("value")
        if isinstance(v, list):
            v = v[0] if v else ""
        existing.add((h.get("type"), str(v or "").lower()))

    added = 0
    emails_seen = set()
    for it in items:
        user = (it.get("username") or "").strip()
        if not user:
            continue
        low = user.lower()
        # self emails / gamertags
        if low in SELF_HINTS or any(h in low for h in ("jeffrey.j.bloom", "cowninja", "jbloo005", "jj_bloom", "warz123")):
            if EMAIL_RE.match(user):
                key = ("email", low)
                if key not in existing:
                    handles.append(
                        {
                            "type": "email",
                            "value": user,
                            "source": "bitwarden_safe",
                            "confidence": "inferred",
                            "at": utc(),
                        }
                    )
                    existing.add(key)
                    added += 1
                    emails_seen.add(low)
            elif low in ("cowninja", "jj_bloom") or low.startswith("warz"):
                key = ("gaming_or_alias", low)
                if key not in existing:
                    handles.append(
                        {
                            "type": "alias",
                            "value": user,
                            "source": "bitwarden_safe",
                            "confidence": "inferred",
                            "at": utc(),
                        }
                    )
                    existing.add(key)
                    added += 1

    jeff["handles"] = handles
    jeff["updated"] = utc()
    db["updated"] = utc()
    CONTACTS.write_text(json.dumps(db, indent=2), encoding="utf-8")
    print(json.dumps({"added_handles": added, "jeff_handle_count": len(handles), "sample_emails": sorted(emails_seen)[:20]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
