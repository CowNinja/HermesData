#!/usr/bin/env python3
"""Normalize contacts_db handles into validity-aware records + historical ledger.

- Split concatenated ':::' values
- Promote strings → handle_record with status/validity
- Heuristic active vs historical (never delete)
- Append ledger observations
- Optional silo registry link scan

Usage:
  python contacts_normalize_ledger.py           # dry-run stats
  python contacts_normalize_ledger.py --apply
  python contacts_normalize_ledger.py --apply --link-silo --link-limit 5
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DB = Path(r"D:\HermesData\state\contacts_db.json")
REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
IDENTITY = Path(r"D:\HermesData\config\google_account_identity.json")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\contacts-normalize-ledger-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_identity_emails() -> set[str]:
    out: set[str] = set()
    if not IDENTITY.exists():
        return out
    try:
        d = json.loads(IDENTITY.read_text(encoding="utf-8"))
        for k in ("primary", "aliases", "active", "emails"):
            v = d.get(k)
            if isinstance(v, str) and "@" in v:
                out.add(v.lower())
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, str) and "@" in x:
                        out.add(x.lower())
                    elif isinstance(x, dict):
                        e = x.get("email") or x.get("value")
                        if isinstance(e, str) and "@" in e:
                            out.add(e.lower())
        # common nested
        for e in d.get("accounts") or []:
            if isinstance(e, dict):
                em = e.get("email")
                if em:
                    out.add(str(em).lower())
    except Exception:
        pass
    # hard known current for Jeff (from silo policy)
    out.update(
        {
            "mr.jeffrey.j.bloom@gmail.com",
            "jeffrey.j.bloom@gmail.com",
        }
    )
    return out


def norm_email(v: str) -> str:
    return v.strip().lower()


def norm_phone(v: str) -> str:
    digits = re.sub(r"\D", "", v)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def split_values(raw: str) -> List[str]:
    parts = re.split(r"\s*:::\s*|\s*;\s*|\s*\|\s*", raw.strip())
    return [p.strip() for p in parts if p and p.strip()]


def classify_email(value: str, self_emails: set[str], is_self: bool) -> Tuple[str, str, List[str]]:
    """return status, confidence, signals"""
    e = norm_email(value)
    signals: List[str] = []
    if "voice.google.com" in e or "txt.voice" in e:
        return "historical", "stale", ["sms_gateway", "not_primary_inbox"]
    if e.endswith("@facebook.com") or "facebook.com" in e:
        return "historical", "stale", ["social_bridge", "facebook"]
    if ".smil.mil" in e:
        return "historical", "stale", ["military_smil", "likely_inactive_path"]
    if e in self_emails and is_self:
        return "active", "confirmed", ["self_identity_current"]
    if is_self and e.endswith("@gmail.com") and "jeffrey" in e:
        return "active", "likely", ["self_gmail_pattern"]
    if e.endswith("@cowninja.com") or e.endswith("@cowninja.com"):
        local = e.split("@", 1)[0]
        if local in {"jeffrey", "jeffrey.j.bloom", "jj", "jjbloom", "jeffrey.bloom", "cowninja", "cowninjatech"}:
            return "unknown", "likely", ["self_domain", "personal_or_brand"]
        return "historical", "stale", ["service_alias", "self_domain", "keep_for_synaptic"]
    if e.endswith("@navy.mil") or e.endswith("@mail.mil"):
        return "unknown", "unknown", ["military_domain", "verify_later"]
    if any(x in e for x in (".edu", "hotmail.com", "yahoo.com", "aol.com")):
        return "historical", "stale", ["legacy_consumer_or_edu", "may_still_work"]
    return "unknown", "unknown", ["needs_verify"]


def classify_phone(value: str) -> Tuple[str, str, List[str]]:
    n = norm_phone(value)
    if len(n) < 10:
        return "invalid", "invalid", ["too_short"]
    # can't know active without live check
    return "unknown", "unknown", ["needs_verify"]


def make_handle(
    kind: str,
    value: str,
    source: str,
    self_emails: set[str],
    is_self: bool,
    first_seen: Optional[str] = None,
) -> dict:
    now = first_seen or utc()
    if kind == "email":
        status, conf, signals = classify_email(value, self_emails, is_self)
        normalized = norm_email(value)
    elif kind == "phone":
        status, conf, signals = classify_phone(value)
        normalized = norm_phone(value)
    else:
        status, conf, signals = "unknown", "unknown", []
        normalized = value.strip().lower()
    return {
        "kind": kind,
        "value": value.strip(),
        "normalized": normalized,
        "status": status,
        "validity": {
            "confidence": conf,
            "signals": signals,
            "last_verified": now if conf == "confirmed" else None,
            "method": "heuristic",
        },
        "first_seen": now,
        "last_seen": now,
        "sources": [source] if source else [],
        "notes": "",
    }


def as_records(items: Any, kind: str, source: str, self_emails: set[str], is_self: bool) -> List[dict]:
    out: List[dict] = []
    if not items:
        return out
    if isinstance(items, dict):
        # already weird
        items = [items]
    for it in items:
        if isinstance(it, dict) and it.get("value"):
            # already record-like
            rec = dict(it)
            rec.setdefault("kind", kind)
            rec.setdefault("normalized", norm_email(rec["value"]) if kind == "email" else str(rec["value"]))
            rec.setdefault("status", "unknown")
            rec.setdefault(
                "validity",
                {
                    "confidence": "unknown",
                    "signals": [],
                    "last_verified": None,
                    "method": "heuristic",
                },
            )
            rec.setdefault("first_seen", utc())
            rec.setdefault("last_seen", utc())
            rec.setdefault("sources", [])
            if source and source not in rec["sources"]:
                rec["sources"].append(source)
            # reclassify emails
            if kind == "email":
                st, conf, sigs = classify_email(rec["value"], self_emails, is_self)
                rec["status"] = st
                rec["validity"]["confidence"] = conf
                rec["validity"]["signals"] = sorted(set((rec["validity"].get("signals") or []) + sigs))
            out.append(rec)
            continue
        if isinstance(it, str):
            for part in split_values(it):
                out.append(make_handle(kind, part, source, self_emails, is_self))
    # dedupe by normalized
    seen = set()
    deduped = []
    for r in out:
        key = r.get("normalized") or r.get("value")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def append_ledger(person: dict, entry: dict) -> None:
    led = person.setdefault("ledger", [])
    # simple dedupe: same kind+value+source+action
    sig = (entry.get("kind"), entry.get("value"), entry.get("source"), entry.get("action"))
    for e in led[-50:]:
        if (e.get("kind"), e.get("value"), e.get("source"), e.get("action")) == sig:
            return
    led.append(entry)


def link_silo(person: dict, limit: int = 5) -> int:
    if not REG.exists():
        return 0
    tokens = []
    # Prefer full names (>= 2 tokens or len>=8) — avoid "Jan"/"Dad" false positives
    for n in [person.get("canonical_name"), *(person.get("name_variants") or [])][:8]:
        if not n:
            continue
        s = str(n).strip()
        if len(s.split()) >= 2 or len(s) >= 8:
            tokens.append(s.lower())
    for bucket in ("email", "phone"):
        for h in person.get("handles", {}).get(bucket) or []:
            if isinstance(h, dict) and h.get("value"):
                tokens.append(str(h["value"]).lower()[:80])
    tokens = [t for t in tokens if len(t) >= 4][:8]
    if not tokens:
        return 0
    con = sqlite3.connect(str(REG))
    hits = []
    for t in tokens:
        rows = con.execute(
            "SELECT dest_path, domain FROM ingest WHERE lower(dest_path) LIKE ? LIMIT ?",
            (f"%{t}%", limit),
        ).fetchall()
        for path, domain in rows:
            hits.append({"path": path, "domain": domain, "token": t})
    con.close()
    # unique paths
    seen = set()
    uniq = []
    for h in hits:
        if h["path"] in seen:
            continue
        seen.add(h["path"])
        uniq.append(h)
        if len(uniq) >= limit:
            break
    links = person.setdefault("silo_links", {})
    links["file_hit_count"] = max(int(links.get("file_hit_count") or 0), len(uniq))
    links["sample_paths"] = [u["path"] for u in uniq]
    links["last_scan"] = utc()
    for u in uniq:
        append_ledger(
            person,
            {
                "at": utc(),
                "kind": "file_hit",
                "value": u["path"],
                "source": "ingest_registry",
                "action": "observed",
                "meta": {"domain": u["domain"], "token": u["token"]},
            },
        )
    return len(uniq)


def normalize_person(cid: str, p: dict, self_emails: set[str], do_links: bool, link_limit: int) -> dict:
    is_self = "self" in (p.get("roles") or []) or cid == "jeffrey_bloom"
    handles = p.get("handles")
    source = "normalize_ledger"
    # normalize list-style handles
    if isinstance(handles, list):
        emails = []
        phones = []
        for item in handles:
            if not isinstance(item, dict):
                continue
            typ = str(item.get("type") or "").lower()
            val = item.get("value")
            vals = val if isinstance(val, list) else ([val] if val else [])
            for v in vals:
                if not v:
                    continue
                if typ == "email" or (isinstance(v, str) and "@" in v):
                    emails.append(str(v))
                elif typ == "phone":
                    phones.append(str(v))
        handles = {"email": emails, "phone": phones, "social": [], "gaming": [], "postal": [], "other": []}
        p["handles"] = handles

    if not isinstance(handles, dict):
        handles = {}
        p["handles"] = handles

    for kind in ("email", "phone", "postal", "other"):
        raw = handles.get(kind) or []
        recs = as_records(raw, kind if kind != "other" else "other", source, self_emails, is_self)
        handles[kind] = recs
        for r in recs:
            append_ledger(
                p,
                {
                    "at": utc(),
                    "kind": kind,
                    "value": r["value"],
                    "source": source,
                    "action": "merged",
                    "meta": {"status": r["status"], "signals": r["validity"].get("signals")},
                },
            )

    # keep social/gaming as-is but ensure list
    for kind in ("social", "gaming"):
        handles.setdefault(kind, handles.get(kind) or [])

    # active summary convenience fields
    p["handles_active"] = {
        "email": [h["value"] for h in handles.get("email") or [] if isinstance(h, dict) and h.get("status") == "active"],
        "phone": [h["value"] for h in handles.get("phone") or [] if isinstance(h, dict) and h.get("status") == "active"],
    }
    p["handles_historical"] = {
        "email": [h["value"] for h in handles.get("email") or [] if isinstance(h, dict) and h.get("status") == "historical"],
        "phone": [h["value"] for h in handles.get("phone") or [] if isinstance(h, dict) and h.get("status") == "historical"],
    }

    if do_links:
        link_silo(p, limit=link_limit)

    p["updated"] = utc()
    p["ledger_version"] = 1
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--link-silo", action="store_true")
    ap.add_argument("--link-limit", type=int, default=5)
    args = ap.parse_args()

    db = json.loads(DB.read_text(encoding="utf-8"))
    people = db.setdefault("people", {})
    self_emails = load_identity_emails()

    stats = {
        "people": len(people),
        "emails_total": 0,
        "emails_active": 0,
        "emails_historical": 0,
        "emails_unknown": 0,
        "phones_total": 0,
        "linked_people": 0,
    }

    for cid, p in people.items():
        normalize_person(cid, p, self_emails, args.link_silo, args.link_limit)
        for h in p.get("handles", {}).get("email") or []:
            if not isinstance(h, dict):
                continue
            stats["emails_total"] += 1
            st = h.get("status")
            if st == "active":
                stats["emails_active"] += 1
            elif st == "historical":
                stats["emails_historical"] += 1
            else:
                stats["emails_unknown"] += 1
        for h in p.get("handles", {}).get("phone") or []:
            if isinstance(h, dict):
                stats["phones_total"] += 1
        if (p.get("silo_links") or {}).get("sample_paths"):
            stats["linked_people"] += 1

    db["schema_version"] = 2
    db["policy"] = {
        **(db.get("policy") or {}),
        "contact_ledger": True,
        "never_delete_handles": True,
        "validity_model": "active|historical|unknown|invalid|suppressed",
        "updated": utc(),
    }

    if args.apply:
        bak = DB.with_suffix(f".json.bak-ledger-{datetime.now().strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(DB, bak)
        DB.write_text(json.dumps(db, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        stats["backup"] = str(bak)

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Contacts normalize + ledger — {utc()}",
        "",
        f"**Mode:** {'APPLY' if args.apply else 'DRY-RUN'}",
        f"**People:** {stats['people']}",
        f"**Emails:** total {stats['emails_total']} · active {stats['emails_active']} · historical {stats['emails_historical']} · unknown {stats['emails_unknown']}",
        f"**Phones:** {stats['phones_total']}",
        f"**Silo-linked people:** {stats['linked_people']}",
        "",
        "Principle: old addresses/phones/emails stay in **ledger** + handles with status — never deleted.",
        "",
        "[[Operations/Contact-Ledger-and-Validity-CANONICAL-2026-07-12]]",
        "",
    ]
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    stats["receipt"] = str(RECEIPT)
    stats["apply"] = args.apply
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
