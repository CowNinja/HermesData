#!/usr/bin/env python3
"""Contacts / person graph — robust relational store for silo + twin.

JSON SSOT now; SQLite export optional later.
Merge evidence, handles, aliases without losing history.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

DB = Path(r"D:\HermesData\state\contacts_db.json")
SCHEMA = Path(r"D:\HermesData\config\contacts_schema.json")


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load() -> dict:
    return json.loads(DB.read_text(encoding="utf-8"))


def save(d: dict) -> None:
    d["updated"] = utc()
    DB.write_text(json.dumps(d, indent=2), encoding="utf-8")


def get_person(cid: str) -> dict | None:
    return (load().get("people") or {}).get(cid)


def upsert_handle(cid: str, kind: str, value, platform: str | None = None) -> str:
    d = load()
    p = d.setdefault("people", {}).setdefault(cid, {"canonical_id": cid, "handles": {}})
    h = p.setdefault("handles", {})
    if kind in {"email", "phone", "postal"}:
        arr = h.setdefault(kind, [])
        v = value if isinstance(value, str) else str(value)
        if v and v not in arr:
            arr.append(v)
            save(d)
            return "added"
        return "exists"
    if kind in {"social", "gaming"}:
        arr = h.setdefault(kind, [])
        entry = {"platform": platform or "unknown", "handle": value}
        if not any(x.get("handle") == value and x.get("platform") == entry["platform"] for x in arr):
            arr.append(entry)
            save(d)
            return "added"
        return "exists"
    return "unknown_kind"


def add_alias(cid: str, alias: str) -> str:
    d = load()
    p = d.setdefault("people", {}).get(cid)
    if not p:
        return "missing_person"
    vars_ = p.setdefault("name_variants", [])
    a = alias.strip()
    if a and a not in vars_:
        vars_.append(a)
        save(d)
        return "added"
    return "exists"


def add_evidence(cid: str, source: str, snippet: str = "") -> None:
    d = load()
    p = d.setdefault("people", {}).get(cid)
    if not p:
        return
    ev = p.setdefault("evidence", [])
    ev.append({"source": source, "snippet": snippet[:300], "found_at": utc()})
    save(d)


def extract_handles_from_text(text: str) -> dict:
    emails = sorted(set(re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)))
    phones = sorted(set(re.findall(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", text)))
    return {"email": emails[:20], "phone": phones[:20]}


def stats() -> dict:
    d = load()
    people = d.get("people") or {}
    confirmed = sum(1 for p in people.values() if p.get("confidence") == "confirmed")
    with_email = sum(1 for p in people.values() if (p.get("handles") or {}).get("email"))
    return {
        "people": len(people),
        "confirmed": confirmed,
        "with_email": with_email,
        "path": str(DB),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["stats", "get", "alias", "email", "list"])
    ap.add_argument("--id", default="")
    ap.add_argument("--value", default="")
    args = ap.parse_args()
    if args.cmd == "stats":
        print(json.dumps(stats(), indent=2))
    elif args.cmd == "list":
        d = load()
        for cid, p in (d.get("people") or {}).items():
            print(f"{cid:20} {p.get('canonical_name')} [{p.get('confidence')}]")
    elif args.cmd == "get":
        print(json.dumps(get_person(args.id), indent=2))
    elif args.cmd == "alias":
        print(add_alias(args.id, args.value))
    elif args.cmd == "email":
        print(upsert_handle(args.id, "email", args.value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
