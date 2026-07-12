#!/usr/bin/env python3
"""Fuse Google/FullContact-style CSV contact exports into contacts_db.json.

- Match existing people by email or normalized name
- Add emails/phones/aliases + evidence path
- Optionally create inferred people (cap) for high-signal rows
- Never stores passwords; phones/emails only

Usage:
  python contacts_fuse_csv.py --csv "K:/.../FullContact Google-CSV of 4048....csv" --limit 500
  python contacts_fuse_csv.py --csv PATH --apply --create-new --create-cap 50
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DB = Path(r"D:\HermesData\state\contacts_db.json")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\contacts-fuse-csv-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm_name(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def slug_id(name: str) -> str:
    s = norm_name(name).replace(" ", "_")
    s = re.sub(r"[^a-z0-9_]", "", s)
    return (s or "unknown")[:64]


def load_db() -> dict:
    return json.loads(DB.read_text(encoding="utf-8"))


def save_db(d: dict) -> None:
    d["updated"] = utc()
    bak = DB.with_suffix(".json.bak-pre-fuse")
    if not bak.exists():
        shutil.copy2(DB, bak)
    DB.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def iter_emails(handles):
    out = []
    if handles is None:
        return out
    if isinstance(handles, list):
        for item in handles:
            if isinstance(item, dict):
                v = item.get('value')
                typ = str(item.get('type') or '').lower()
                if isinstance(v, str) and '@' in v:
                    out.append(v)
                elif isinstance(v, list):
                    out.extend([x for x in v if isinstance(x, str) and '@' in x])
                elif typ == 'email' and isinstance(v, str):
                    out.append(v)
            elif isinstance(item, str) and '@' in item:
                out.append(item)
        return out
    if isinstance(handles, dict):
        emails = handles.get('email') or []
        if isinstance(emails, list):
            for e in emails:
                if isinstance(e, str) and '@' in e:
                    out.append(e)
                elif isinstance(e, dict):
                    v = e.get('value')
                    if isinstance(v, str) and '@' in v:
                        out.append(v)
                    elif isinstance(v, list):
                        out.extend([x for x in v if isinstance(x, str) and '@' in x])
        elif isinstance(emails, str) and '@' in emails:
            out.append(emails)
    return out


def build_indexes(people: dict):
    by_email = {}
    by_name = {}
    for cid, p in people.items():
        for e in iter_emails(p.get('handles')):
            by_email[e.lower()] = cid
        for n in [p.get('canonical_name'), *(p.get('name_variants') or [])]:
            if n:
                by_name[norm_name(str(n))] = cid
        by_name[norm_name(cid.replace('_', ' '))] = cid
    return by_email, by_name



def row_get(row: dict, *keys: str) -> str:
    for k in keys:
        if k in row and str(row[k] or "").strip():
            return str(row[k]).strip()
        # case-insensitive
        for rk, rv in row.items():
            if rk is None:
                continue
            if str(rk).lower() == k.lower() and str(rv or "").strip():
                return str(rv).strip()
    return ""


def extract_row(row: dict) -> dict:
    name = row_get(
        row,
        "Name",
        "Full Name",
        "First Name",
        "Given Name",
    )
    given = row_get(row, "Given Name", "First Name")
    family = row_get(row, "Family Name", "Last Name")
    if not name and (given or family):
        name = f"{given} {family}".strip()
    emails = []
    phones = []
    for k, v in row.items():
        if k is None or not v or not str(v).strip():
            continue
        kl = str(k).lower()
        val = str(v).strip()
        if "e-mail" in kl or "email" in kl:
            if "@" in val:
                emails.append(val)
        if "phone" in kl or "mobile" in kl or "tel" in kl:
            if re.search(r"\d{3}", val):
                phones.append(val)
    # Google CSV specific columns
    for i in range(1, 6):
        e = row_get(row, f"E-mail {i} - Value", f"Email {i} - Value")
        if e and "@" in e:
            emails.append(e)
        ph = row_get(row, f"Phone {i} - Value")
        if ph:
            phones.append(ph)
    emails = sorted(set(emails))
    phones = sorted(set(phones))
    return {"name": name, "emails": emails, "phones": phones, "given": given, "family": family}


def merge_into_person(p: dict, data: dict, source: str) -> List[str]:
    changes = []
    handles = p.get("handles")
    if not isinstance(handles, dict):
        # normalize list-of-handle-dicts → dict shape
        emails = iter_emails(handles)
        phones: List[str] = []
        if isinstance(handles, list):
            for item in handles:
                if isinstance(item, dict) and str(item.get("type", "")).lower() == "phone":
                    v = item.get("value")
                    if isinstance(v, list):
                        phones.extend([str(x) for x in v if x])
                    elif v:
                        phones.append(str(v))
        handles = {"email": emails, "phone": phones}
        p["handles"] = handles
    handles = p.setdefault("handles", {})
    # normalize email list
    em = handles.get("email")
    if em is None:
        em = []
        handles["email"] = em
    if isinstance(em, dict):
        # weird shape
        em = []
        handles["email"] = em
    for e in data["emails"]:
        if e not in em:
            em.append(e)
            changes.append(f"+email {e}")
    ph = handles.get("phone")
    if ph is None:
        ph = []
        handles["phone"] = ph
    if isinstance(ph, dict):
        ph = []
        handles["phone"] = ph
    for x in data["phones"]:
        if x not in ph:
            ph.append(x)
            changes.append(f"+phone {x}")
    if data["name"]:
        vars_ = p.setdefault("name_variants", [])
        if data["name"] not in vars_ and data["name"] != p.get("canonical_name"):
            vars_.append(data["name"])
            changes.append(f"+alias {data['name']}")
    ev = p.setdefault("evidence", [])
    ev.append(
        {
            "source": source,
            "snippet": f"csv fuse name={data['name']} emails={len(data['emails'])} phones={len(data['phones'])}",
            "found_at": utc(),
        }
    )
    if changes:
        p["updated"] = utc()
    return changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--create-new", action="store_true", help="create inferred people for unmatched")
    ap.add_argument("--create-cap", type=int, default=30)
    args = ap.parse_args()

    path = Path(args.csv)
    if not path.is_file():
        print(json.dumps({"error": f"missing {path}"}))
        return 1

    db = load_db()
    people = db.setdefault("people", {})
    by_email, by_name = build_indexes(people)

    matched = 0
    created = 0
    skipped = 0
    examples: List[str] = []

    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        # Google CSV often has BOM
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample[:2048])
        except Exception:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        for i, row in enumerate(reader):
            if i >= args.limit:
                break
            data = extract_row(row)
            if not data["name"] and not data["emails"]:
                skipped += 1
                continue
            cid = None
            for e in data["emails"]:
                cid = by_email.get(e.lower())
                if cid:
                    break
            if not cid and data["name"] and len(norm_name(data["name"]).split()) >= 2:
                cid = by_name.get(norm_name(data["name"]))
            if not cid and data["given"] and data["family"]:
                cid = by_name.get(norm_name(f"{data['given']} {data['family']}"))

            if cid and cid in people:
                ch = merge_into_person(people[cid], data, str(path))
                if ch:
                    matched += 1
                    if len(examples) < 12:
                        examples.append(f"match {cid}: {', '.join(ch[:4])}")
                else:
                    skipped += 1
                # refresh email index
                for e in data["emails"]:
                    by_email[e.lower()] = cid
            elif args.create_new and created < args.create_cap and data["name"] and len(data["name"].split()) >= 2:
                if data["emails"] and all("voice.google.com" in e for e in data["emails"]):
                    skipped += 1
                    continue
                nid = slug_id(data["name"])
                if nid in people:
                    nid = f"{nid}_{created}"
                people[nid] = {
                    "canonical_id": nid,
                    "canonical_name": data["name"],
                    "name_variants": [data["name"]],
                    "roles": ["inferred_contact"],
                    "domain_primary": "Digital-Footprint",
                    "relations": [],
                    "handles": {"email": list(data["emails"]), "phone": list(data["phones"])},
                    "bio": {"notes": "Inferred from contact CSV fuse", "orgs": []},
                    "confidence": "inferred",
                    "status": "active",
                    "evidence": [
                        {
                            "source": str(path),
                            "snippet": "created from csv fuse",
                            "found_at": utc(),
                        }
                    ],
                    "updated": utc(),
                }
                created += 1
                for e in data["emails"]:
                    by_email[e.lower()] = nid
                by_name[norm_name(data["name"])] = nid
                if len(examples) < 12:
                    examples.append(f"create {nid} emails={data['emails'][:2]}")
            else:
                skipped += 1

    if args.apply:
        save_db(db)

    stats = {
        "csv": str(path),
        "apply": args.apply,
        "matched_enriched": matched,
        "created": created,
        "skipped": skipped,
        "people_total": len(people),
        "examples": examples,
    }

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Contacts CSV fuse — {utc()}",
        "",
        f"**CSV:** `{path.name}`",
        f"**Mode:** {'APPLY' if args.apply else 'DRY-RUN'}",
        f"**Matched/enriched:** {matched} · **Created:** {created} · **Skipped:** {skipped}",
        f"**People total:** {len(people)}",
        "",
        "## Examples",
        "",
    ]
    for e in examples:
        lines.append(f"- {e}")
    lines += [
        "",
        "[[Operations/Silo-Next-Enhancements-2026-07-12]]",
        "",
    ]
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    stats["receipt"] = str(RECEIPT)
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
