#!/usr/bin/env python3
"""Contacts / person graph — one JSON SSOT (contacts_db.json).

Lookup is exact. Card facts require evidence.source + date.
Never promote entity_context / OCR aliases into a card.

Write after Send/Leave:
  python contacts_db.py observe-gmail --id sara_ballas \\
    --message-id 1a01ba72b7364ee5 --from mistyflavor.sb@gmail.com \\
    --to mr.jeffrey.j.bloom@gmail.com --date 2026-08-19 \\
    --subject "..." --action leave
Mint only with the same evidence (never from a fuzzy name):
  python contacts_db.py observe-gmail --mint --name "Kevin Example" \\
    --message-id ... --from ... --to ... --date ...
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

DB = Path(r"D:\HermesData\state\contacts_db.json")
SCHEMA = Path(r"D:\HermesData\config\contacts_schema.json")
IDENTITY = Path(r"D:\HermesData\config\google_account_identity.json")

SELF_EMAILS = {
    "mr.jeffrey.j.bloom@gmail.com",
    "jeffrey.j.bloom@gmail.com",
    "booksbloom@gmail.com",
    "booksbloom@yahoo.com",
}


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def extract_email(raw: str) -> str:
    m = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", raw or "")
    return (m.group(0) if m else "").strip().lower()


def load() -> dict:
    return json.loads(DB.read_text(encoding="utf-8"))


def save(d: dict) -> None:
    d["updated"] = utc_iso()
    DB.write_text(json.dumps(d, indent=2), encoding="utf-8")


def load_self_emails() -> set[str]:
    out = set(SELF_EMAILS)
    if IDENTITY.exists():
        try:
            ident = json.loads(IDENTITY.read_text(encoding="utf-8"))
            for k in ("primary", "aliases", "active", "emails"):
                v = ident.get(k)
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
        except Exception:
            pass
    return out


def get_person(cid: str) -> dict | None:
    return (load().get("people") or {}).get(cid)


def find_person_exact(db: dict, key: str) -> tuple[str, dict] | None:
    """Exact id / canonical / variant only. No substring. No entity_context."""
    people = db.get("people") or {}
    if key in people:
        return key, people[key]
    nk = norm(key)
    if not nk:
        return None
    for cid, p in people.items():
        names = [p.get("canonical_name"), cid.replace("_", " ")]
        names.extend(p.get("name_variants") or [])
        for n in names:
            if n and norm(str(n)) == nk:
                return cid, p
    return None


def has_dated_evidence(p: dict) -> bool:
    for ev in p.get("evidence") or []:
        if not isinstance(ev, dict):
            continue
        src = str(ev.get("source") or ev.get("source_path") or "").strip()
        dt = str(ev.get("found_at") or ev.get("date") or ev.get("at") or "").strip()
        if src and dt:
            return True
    for e in p.get("ledger") or []:
        if not isinstance(e, dict):
            continue
        src = str(e.get("source") or "").strip()
        dt = str(e.get("at") or e.get("date") or "").strip()
        if src.startswith("gmail:") and dt:
            return True
    return False


def rebuild_handles_active(p: dict) -> dict:
    """Active = last Gmail From/To verified. Rest stay historical/unknown."""
    emails_act: list[str] = []
    phones_act: list[str] = []
    emails_hist: list[str] = []
    phones_hist: list[str] = []
    handles = p.setdefault("handles", {})
    for kind, act, hist in (
        ("email", emails_act, emails_hist),
        ("phone", phones_act, phones_hist),
    ):
        for h in handles.get(kind) or []:
            if not isinstance(h, dict) or not h.get("value"):
                continue
            if h.get("status") == "active":
                act.append(h["value"])
            elif h.get("status") == "historical":
                hist.append(h["value"])
    p["handles_active"] = {"email": emails_act, "phone": phones_act}
    p["handles_historical"] = {"email": emails_hist, "phone": phones_hist}
    return p["handles_active"]


def _slug_name(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s[:48] or ""


def _ensure_email_record(p: dict, email: str, source: str, when: str) -> dict:
    handles = p.setdefault("handles", {})
    arr = handles.setdefault("email", [])
    rec = None
    for h in arr:
        if isinstance(h, dict) and extract_email(str(h.get("value") or "")) == email:
            rec = h
            break
        if isinstance(h, str) and extract_email(h) == email:
            rec = None
            break
    if rec is None:
        rec = {
            "kind": "email",
            "value": email,
            "normalized": email,
            "status": "unknown",
            "validity": {
                "confidence": "unknown",
                "signals": [],
                "last_verified": None,
                "method": "heuristic",
            },
            "first_seen": when,
            "last_seen": when,
            "sources": [],
            "notes": "",
        }
        arr.append(rec)
    rec["last_seen"] = when
    srcs = rec.setdefault("sources", [])
    if source and source not in srcs:
        srcs.append(source)
    return rec


def observe_gmail(
    *,
    cid: str = "",
    name: str = "",
    mint: bool = False,
    message_id: str = "",
    thread_id: str = "",
    from_addr: str = "",
    to_addr: str = "",
    date: str = "",
    subject: str = "",
    action: str = "observed",
) -> dict:
    """One write: ledger_entry + add_evidence from a Gmail id. No second DB."""
    mid = (message_id or thread_id or "").strip()
    if not mid:
        return {"ok": False, "error": "need --message-id or --thread-id"}
    from_e = extract_email(from_addr)
    to_e = extract_email(to_addr)
    when = (date or "").strip()
    if not from_e or not when:
        return {
            "ok": False,
            "error": "need --from and --date (evidence.source + date)",
        }
    source = f"gmail:{mid}"
    self_emails = load_self_emails()
    party = from_e if from_e not in self_emails else to_e
    if not party or party in self_emails:
        return {
            "ok": False,
            "error": "no counterparty email (From/To both self or empty)",
            "from": from_e,
            "to": to_e,
        }

    bak = DB.with_suffix(f".json.bak-observe-{utc()}")
    if DB.exists() and not bak.exists():
        shutil.copy2(DB, bak)

    d = load()
    people = d.setdefault("people", {})
    hit = find_person_exact(d, cid) if cid else None
    if hit is None and name:
        hit = find_person_exact(d, name)
    if hit is None:
        if not mint:
            return {
                "ok": False,
                "lookup": "UNKNOWN",
                "reason": "not_on_card",
                "hint": "pass --id of an existing card, or --mint --name with this same evidence",
            }
        if not (name or "").strip():
            return {"ok": False, "error": "--mint requires --name"}
        new_id = cid or _slug_name(name)
        if not new_id:
            return {"ok": False, "error": "could not slug --name"}
        if new_id in people:
            return {
                "ok": False,
                "error": "id_exists",
                "canonical_id": new_id,
                "hint": "use --id, do not mint",
            }
        people[new_id] = {
            "canonical_id": new_id,
            "canonical_name": name.strip(),
            "name_variants": [name.strip()],
            "roles": [],
            "domain_primary": "",
            "relations": [],
            "handles": {"email": [], "phone": []},
            "ledger": [],
            "evidence": [],
            "confidence": "inferred",
            "status": "active",
            "bio": {"notes": "minted from gmail observe; not from entity_context"},
        }
        cid = new_id
        p = people[cid]
        minted = True
    else:
        cid, p = hit
        minted = False

    rec = _ensure_email_record(p, party, source, when)
    rec["status"] = "active"
    rec["validity"] = {
        "confidence": "confirmed",
        "signals": ["gmail_from_to", f"action:{action or 'observed'}"],
        "last_verified": when,
        "method": "gmail_from_to",
    }
    # Other emails on this card: not this From/To → not active.
    for h in (p.get("handles") or {}).get("email") or []:
        if not isinstance(h, dict):
            continue
        if extract_email(str(h.get("value") or "")) == party:
            continue
        if h.get("status") == "active":
            h["status"] = "unknown"
            val = h.setdefault("validity", {})
            if isinstance(val, dict):
                sigs = val.setdefault("signals", [])
                if "displaced_by_gmail_from_to" not in sigs:
                    sigs.append("displaced_by_gmail_from_to")

    ev = p.setdefault("evidence", [])
    if not any(isinstance(x, dict) and x.get("source") == source for x in ev):
        ev.append(
            {
                "source": source,
                "snippet": (subject or f"{action} {party}")[:300],
                "found_at": when,
            }
        )
    led = p.setdefault("ledger", [])
    led.append(
        {
            "at": utc_iso(),
            "kind": "email",
            "value": party,
            "source": source,
            "action": "verified" if action.lower() in {"send", "leave", "observed", "verified"} else action,
            "meta": {
                "thread_id": thread_id or "",
                "message_id": message_id or mid,
                "from": from_e,
                "to": to_e,
                "subject": (subject or "")[:160],
                "mail_action": action,
            },
        }
    )
    rebuild_handles_active(p)
    p["updated"] = utc_iso()
    save(d)
    return {
        "ok": True,
        "minted": minted,
        "canonical_id": cid,
        "canonical_name": p.get("canonical_name"),
        "verified_email": party,
        "source": source,
        "date": when,
        "handles_active": p.get("handles_active"),
        "lookup": "CARD",
    }


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
    """Legacy helper. Prefer observe-gmail (source + date required)."""
    if not source or not str(source).strip():
        return
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
    with_active = sum(
        1 for p in people.values() if (p.get("handles_active") or {}).get("email")
    )
    return {
        "people": len(people),
        "confirmed": confirmed,
        "with_email": with_email,
        "with_handles_active_email": with_active,
        "path": str(DB),
        "law": "exact_lookup; evidence.source+date; no entity_context on cards",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "cmd",
        choices=["stats", "get", "alias", "email", "list", "lookup", "observe-gmail"],
    )
    ap.add_argument("--id", default="")
    ap.add_argument("--value", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--mint", action="store_true")
    ap.add_argument("--message-id", default="")
    ap.add_argument("--thread-id", default="")
    ap.add_argument("--from", dest="from_addr", default="")
    ap.add_argument("--to", dest="to_addr", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--subject", default="")
    ap.add_argument("--action", default="observed", help="observed|send|leave|verified")
    args = ap.parse_args()
    if args.cmd == "stats":
        print(json.dumps(stats(), indent=2))
    elif args.cmd == "list":
        d = load()
        for cid, p in (d.get("people") or {}).items():
            print(f"{cid:20} {p.get('canonical_name')} [{p.get('confidence')}]")
    elif args.cmd == "get":
        print(json.dumps(get_person(args.id), indent=2))
    elif args.cmd == "lookup":
        d = load()
        hit = find_person_exact(d, args.id or args.name or args.value)
        if not hit:
            print(
                json.dumps(
                    {
                        "lookup": "UNKNOWN",
                        "query": args.id or args.name or args.value,
                        "reason": "not_on_card",
                    }
                )
            )
            return 2
        cid, p = hit
        if not has_dated_evidence(p):
            print(
                json.dumps(
                    {
                        "lookup": "UNKNOWN",
                        "query": args.id or args.name,
                        "canonical_id": cid,
                        "reason": "no_evidence_source_date",
                    }
                )
            )
            return 2
        print(
            json.dumps(
                {
                    "lookup": "CARD",
                    "canonical_id": cid,
                    "canonical_name": p.get("canonical_name"),
                    "handles_active": p.get("handles_active") or {},
                }
            )
        )
    elif args.cmd == "alias":
        print(add_alias(args.id, args.value))
    elif args.cmd == "email":
        print(upsert_handle(args.id, "email", args.value))
    elif args.cmd == "observe-gmail":
        rec = observe_gmail(
            cid=args.id,
            name=args.name,
            mint=bool(args.mint),
            message_id=args.message_id,
            thread_id=args.thread_id,
            from_addr=args.from_addr,
            to_addr=args.to_addr,
            date=args.date,
            subject=args.subject,
            action=args.action,
        )
        print(json.dumps(rec, indent=2))
        return 0 if rec.get("ok") else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
