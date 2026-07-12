#!/usr/bin/env python3
"""Travel-mode gray person/relationship queue.

Scans entity_context + new registry name-like tokens; accumulates questions
Jeff can answer when he returns. NEVER blocks the factory. NEVER requires live chat.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ENTITY = Path(r"D:\HermesData\config\entity_context.json")
QUEUE = Path(r"D:\HermesData\state\gray_entities_queue.json")
VAULT = Path(r"D:\PhronesisVault\Operations\logs\gray-entities-queue-latest.md")
DB = Path(r"D:\HermesData\state\ingest_registry.sqlite3")

# roles that need Jeff for intimate/relationship gray
GRAY_ROLES = {"unknown", "unsure", "", None}
INTIMATE_HINTS = re.compile(
    r"\b(girlfriend|boyfriend|wife|husband|ex[- ]|dating|partner|fiance|fiancé|lover|crush)\b",
    re.I,
)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_queue() -> dict:
    if QUEUE.is_file():
        try:
            return json.loads(QUEUE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"items": [], "updated_at": None, "policy": "accumulate_only_no_live_ping"}


def main() -> int:
    data = json.loads(ENTITY.read_text(encoding="utf-8")) if ENTITY.is_file() else {}
    people = data.get("people") or []
    q = load_queue()
    by_id = {i.get("id") or i.get("canonical"): i for i in q.get("items") or []}

    added = 0
    JUNK = ("dental", "accepted", "reminder", "enrollment", "package", "postcard",
             "kool smiles", "invitation", "statement", "record", "relayed", "weis")
    for pe in people:
        can = pe.get("canonical") or (pe.get("names") or [None])[0]
        if not can:
            continue
        cl = str(can).lower()
        if any(j in cl for j in JUNK):
            continue
        # skip single token short
        if " " not in cl and len(cl) < 5:
            continue
        if pe.get("confidence") == "confirmed":
            continue
        conf = (pe.get("confidence") or "").lower()
        role = (pe.get("role") or "").lower()
        notes = pe.get("notes") or ""
        domain = pe.get("domain") or ""

        reasons = []
        if conf in ("", "unknown", "unsure", "inferred") and not pe.get("confirmed"):
            if conf != "confirmed":
                reasons.append(f"confidence={conf or 'missing'}")
        if "unsure" in notes.lower() or "gray" in notes.lower():
            reasons.append("notes_flag_unsure")
        if INTIMATE_HINTS.search(notes) or INTIMATE_HINTS.search(role):
            reasons.append("possible_intimate_relationship")
        if role in ("unknown", "person", "") and "Family" not in domain and "Friends" not in domain:
            if conf != "confirmed":
                reasons.append("role_domain_unclear")
        # open marital third surname for Jodi
        if "jodi" in str(can).lower() and "third" in notes.lower():
            reasons.append("jodi_third_marriage_surname_unknown")

        if not reasons:
            continue

        key = str(can)
        item = {
            "id": key,
            "canonical": can,
            "domain": domain,
            "role": pe.get("role"),
            "confidence": pe.get("confidence"),
            "reasons": reasons,
            "question": (
                f"Who is **{can}** to you? "
                f"(A) Family (B) Friend (C) Medical/professional (D) Other — free text. "
                f"Context: {reasons}"
            ),
            "first_seen": by_id.get(key, {}).get("first_seen") or utc(),
            "last_seen": utc(),
            "status": by_id.get(key, {}).get("status") or "open",
        }
        if key not in by_id:
            added += 1
        by_id[key] = item

    # Aryel-style known opens from notes
    known_opens = [
        {
            "id": "Aryel",
            "canonical": "Aryel",
            "question": "Aryel — friend / family / unsure? (gdoc stub only until Takeout)",
            "reasons": ["gdoc_stub", "identity_unsure"],
            "status": "open",
        },
        {
            "id": "Jodi_third_marriage",
            "canonical": "Jodi Suzanne Bloom — 3rd marriage surname",
            "question": "Jodi's third (short) marriage surname if it appears in files?",
            "reasons": ["optional_when_found"],
            "status": "open",
        },
    ]
    for ko in known_opens:
        if ko["id"] not in by_id:
            ko["first_seen"] = utc()
            ko["last_seen"] = utc()
            by_id[ko["id"]] = ko
            added += 1

    items = sorted(by_id.values(), key=lambda x: x.get("last_seen") or "", reverse=True)
    open_items = [i for i in items if i.get("status") == "open"]
    payload = {
        "updated_at": utc(),
        "policy": "accumulate_only_no_live_ping_travel",
        "open_count": len(open_items),
        "items": items,
    }
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        f"# Gray entities queue — {utc()}",
        "",
        f"**Open:** {len(open_items)} · **Added this run:** {added}",
        "",
        "_Travel mode: accumulate only. Jeff answers when convenient._",
        "",
        "| Person | Reasons | Question |",
        "|--------|---------|----------|",
    ]
    for i in open_items[:40]:
        lines.append(
            f"| {i.get('canonical')} | {', '.join(i.get('reasons') or [])} | {i.get('question','')[:80]} |"
        )
    VAULT.parent.mkdir(parents=True, exist_ok=True)
    VAULT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"open": len(open_items), "added": added, "queue": str(QUEUE)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
