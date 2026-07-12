#!/usr/bin/env python3
"""Contact merge hygiene — clean messy historical contact merges without deleting history.

Jeff 2026-07-12: past contact merges were messy; phones/emails may be wrong, old, or
corrupt concatenations. Keep everything in ledger; flag and split for training/twin.

Actions:
- Split ':::' / multi-phone strings into separate handle records
- Flag sms gateways, facebook bridges, masked **** phones
- Flag multi-line / multi-number blobs as merge_relic
- Shared org emails (booksbloom@*) → link both parents + jeff relation note
- Never delete handles — status/signals only

Usage:
  python contacts_merge_hygiene.py
  python contacts_merge_hygiene.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

DB = Path(r"D:\HermesData\state\contacts_db.json")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\contacts-merge-hygiene-latest.md")

SHARED_ORG_EMAILS = {
    "booksbloom@gmail.com": ["gary_bloom", "jan_bloom", "jeffrey_bloom"],
    "booksbloom@yahoo.com": ["gary_bloom", "jan_bloom", "jeffrey_bloom"],
}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def split_blob(val: str) -> List[str]:
    parts = re.split(r"\s*:::\s*|\s*;\s*|\s*\|\s*|\s+and\s+", val.strip())
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # further split phone chains like "+1 757-203-0913 ::: +1 757-203-1088"
        if re.search(r"\d{3}.*\d{3}", p) and " " in p and p.count("-") >= 2 and "@@" not in p:
            # keep as one if single phone
            out.append(p)
        else:
            out.append(p)
    return out


def phone_signals(val: str) -> List[str]:
    sig = []
    if "****" in val or "…" in val or "..." in val:
        sig.append("masked_export")
    if "voice.google.com" in val.lower():
        sig.append("sms_gateway")
    digits = re.sub(r"\D", "", val)
    if len(digits) < 10:
        sig.append("too_short")
    if len(digits) > 15:
        sig.append("too_long_or_concat")
    if val.count("+1") > 1 or val.count(":::") >= 1:
        sig.append("merge_concat_relic")
    return sig


def email_signals(val: str) -> List[str]:
    e = val.lower()
    sig = []
    if "voice.google.com" in e or "txt.voice" in e:
        sig.append("sms_gateway")
    if "facebook.com" in e:
        sig.append("facebook_bridge")
    if "****" in e:
        sig.append("masked_export")
    if ":::" in val:
        sig.append("merge_concat_relic")
    return sig


def ensure_record(kind: str, value: str, base: dict | None = None) -> dict:
    rec = dict(base or {})
    rec["kind"] = kind
    rec["value"] = value.strip()
    if kind == "email":
        rec["normalized"] = value.strip().lower()
    elif kind == "phone":
        rec["normalized"] = re.sub(r"\D", "", value)
        if len(rec["normalized"]) == 11 and rec["normalized"].startswith("1"):
            rec["normalized"] = rec["normalized"][1:]
    else:
        rec["normalized"] = value.strip().lower()
    rec.setdefault("status", "unknown")
    rec.setdefault(
        "validity",
        {
            "confidence": "unknown",
            "signals": [],
            "last_verified": None,
            "method": "merge_hygiene",
        },
    )
    rec.setdefault("first_seen", utc())
    rec["last_seen"] = utc()
    rec.setdefault("sources", [])
    if "merge_hygiene" not in rec["sources"]:
        rec["sources"].append("merge_hygiene")
    rec.setdefault("notes", "")
    return rec


def hygiene_handles(person: dict) -> Dict[str, int]:
    stats = {"split": 0, "flagged": 0, "emails": 0, "phones": 0}
    handles = person.get("handles")
    if not isinstance(handles, dict):
        return stats

    for kind in ("email", "phone"):
        raw = handles.get(kind) or []
        if not isinstance(raw, list):
            continue
        new_list: List[dict] = []
        seen = set()
        for item in raw:
            if isinstance(item, str):
                parts = split_blob(item)
                if len(parts) > 1:
                    stats["split"] += len(parts) - 1
                for part in parts:
                    rec = ensure_record(kind, part)
                    sigs = email_signals(part) if kind == "email" else phone_signals(part)
                    if sigs:
                        stats["flagged"] += 1
                        rec["validity"]["signals"] = sorted(set(sigs))
                        if "merge_concat_relic" in sigs or "too_long_or_concat" in sigs:
                            rec["status"] = "historical"
                            rec["validity"]["confidence"] = "stale"
                            rec["notes"] = "Likely bad historical contact merge; kept for ledger"
                        elif "sms_gateway" in sigs or "facebook_bridge" in sigs:
                            rec["status"] = "historical"
                            rec["validity"]["confidence"] = "stale"
                        elif "masked_export" in sigs:
                            rec["status"] = "historical"
                            rec["validity"]["confidence"] = "stale"
                            rec["notes"] = "Masked export — not dialable/usable as-is"
                    key = rec["normalized"]
                    if key in seen:
                        continue
                    seen.add(key)
                    new_list.append(rec)
            elif isinstance(item, dict) and item.get("value"):
                val = str(item["value"])
                parts = split_blob(val) if ":::" in val or ";" in val else [val]
                if len(parts) > 1:
                    stats["split"] += len(parts) - 1
                for part in parts:
                    rec = ensure_record(kind, part, item if len(parts) == 1 else None)
                    rec["value"] = part
                    if kind == "email":
                        rec["normalized"] = part.lower()
                    else:
                        rec["normalized"] = re.sub(r"\D", "", part)
                    sigs = email_signals(part) if kind == "email" else phone_signals(part)
                    old = list((rec.get("validity") or {}).get("signals") or [])
                    rec.setdefault("validity", {"confidence": "unknown", "signals": [], "last_verified": None, "method": "merge_hygiene"})
                    rec["validity"]["signals"] = sorted(set(old + sigs))
                    if sigs:
                        stats["flagged"] += 1
                    if "merge_concat_relic" in rec["validity"]["signals"] or "masked_export" in rec["validity"]["signals"]:
                        rec["status"] = "historical"
                        rec["validity"]["confidence"] = "stale"
                    key = rec["normalized"]
                    if key in seen:
                        continue
                    seen.add(key)
                    new_list.append(rec)
            else:
                continue
        handles[kind] = new_list
        if kind == "email":
            stats["emails"] = len(new_list)
        else:
            stats["phones"] = len(new_list)

        # multi-phone uncertainty: if >4 phones, mark extras as unknown merge soup
        if kind == "phone" and len(new_list) > 4:
            for rec in new_list:
                sigs = rec.setdefault("validity", {}).setdefault("signals", [])
                if "merge_soup_many_numbers" not in sigs:
                    sigs.append("merge_soup_many_numbers")
                    stats["flagged"] += 1
                if rec.get("status") == "active":
                    rec["status"] = "unknown"
                    rec["validity"]["confidence"] = "unknown"
                    rec["notes"] = (rec.get("notes") or "") + " | many numbers from messy merges — verify before trust"

    person["handles"] = handles
    # refresh summaries
    person["handles_active"] = {
        "email": [h["value"] for h in handles.get("email") or [] if isinstance(h, dict) and h.get("status") == "active"],
        "phone": [h["value"] for h in handles.get("phone") or [] if isinstance(h, dict) and h.get("status") == "active"],
    }
    person["handles_historical"] = {
        "email": [h["value"] for h in handles.get("email") or [] if isinstance(h, dict) and h.get("status") == "historical"],
        "phone": [h["value"] for h in handles.get("phone") or [] if isinstance(h, dict) and h.get("status") == "historical"],
    }
    person.setdefault("ledger", []).append(
        {
            "at": utc(),
            "kind": "hygiene",
            "value": f"merge_hygiene split={stats['split']} flagged={stats['flagged']}",
            "source": "contacts_merge_hygiene.py",
            "action": "merged",
            "meta": stats,
        }
    )
    person["updated"] = utc()
    return stats


def apply_shared_orgs(people: dict) -> int:
    n = 0
    for email, cids in SHARED_ORG_EMAILS.items():
        for cid in cids:
            p = people.get(cid)
            if not p:
                continue
            handles = p.setdefault("handles", {})
            if not isinstance(handles, dict):
                continue
            emails = handles.setdefault("email", [])
            norms = {h.get("normalized") for h in emails if isinstance(h, dict)}
            if email.lower() not in norms:
                rec = ensure_record("email", email)
                rec["status"] = "unknown"
                rec["validity"]["signals"] = ["shared_family_business", "booksbloom"]
                rec["notes"] = "BooksBloom family business — Jeff helps; not exclusive to one person"
                emails.append(rec)
                n += 1
            # relation/org note
            bio = p.setdefault("bio", {})
            orgs = bio.setdefault("orgs", [])
            if "BooksBloom" not in orgs:
                orgs.append("BooksBloom")
            p.setdefault("ledger", []).append(
                {
                    "at": utc(),
                    "kind": "email",
                    "value": email,
                    "source": "shared_org_policy",
                    "action": "observed",
                    "meta": {"org": "BooksBloom", "shared_with": cids},
                }
            )
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = json.loads(DB.read_text(encoding="utf-8"))
    people = db.setdefault("people", {})
    totals = {"split": 0, "flagged": 0, "people": 0}
    per = []
    for cid, p in people.items():
        st = hygiene_handles(p)
        if st["split"] or st["flagged"]:
            totals["people"] += 1
            per.append(f"{cid}: split={st['split']} flagged={st['flagged']} e={st['emails']} ph={st['phones']}")
        totals["split"] += st["split"]
        totals["flagged"] += st["flagged"]

    shared = apply_shared_orgs(people)
    db.setdefault("policy", {})["merge_hygiene"] = {
        "never_delete": True,
        "messy_merge_policy": "split_flag_ledger",
        "phones_uncertain": True,
        "jeff_note": "Historical merges messy; accuracy unknown until verified",
        "updated": utc(),
    }

    if args.apply:
        bak = DB.with_suffix(f".json.bak-hygiene-{datetime.now().strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(DB, bak)
        DB.write_text(json.dumps(db, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        totals["backup"] = str(bak)

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Contacts merge hygiene — {utc()}",
        "",
        f"**Mode:** {'APPLY' if args.apply else 'DRY-RUN'}",
        f"**People touched:** {totals['people']} · **splits:** {totals['split']} · **flags:** {totals['flagged']} · **shared org adds:** {shared}",
        "",
        "Policy: never delete; messy merges → historical/unknown + signals; BooksBloom shared.",
        "",
        "## Per person",
        "",
    ]
    for line in per[:40]:
        lines.append(f"- {line}")
    lines += ["", "[[Operations/Contact-Ledger-and-Validity-CANONICAL-2026-07-12]]", ""]
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    totals["shared_org"] = shared
    totals["receipt"] = str(RECEIPT)
    totals["apply"] = args.apply
    print(json.dumps(totals, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
