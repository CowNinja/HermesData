#!/usr/bin/env python3
"""Entity resolution: exact aliases + fuzzy match for OCR/misspellings/nicknames.

Research patterns: entity resolution / record linkage (Fellegi–Sunter spirit),
alias tables, Levenshtein/ratio fuzzy match, canonical ID.

Does not auto-merge placeholders into confirmed without high confidence.
"""
from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

ALIAS_PATH = Path(r"D:\HermesData\config\entity_aliases.json")
ENTITY_PATH = Path(r"D:\HermesData\config\entity_context.json")


def load_aliases() -> dict:
    return json.loads(ALIAS_PATH.read_text(encoding="utf-8"))


def norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9\s\-']", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def expand_surname_typos(text: str, surname_aliases: dict) -> str:
    """Rewrite known OCR surname variants toward canonical form for matching."""
    t = norm(text)
    for canon, variants in surname_aliases.items():
        for v in variants:
            if v != canon:
                t = re.sub(rf"\b{re.escape(v)}\b", canon, t)
    return t


def build_alias_index(data: dict) -> list[tuple[str, str, dict]]:
    """List of (alias_norm, canonical_id, record)."""
    out = []
    for cid, rec in (data.get("canonical_people") or {}).items():
        names = [rec.get("canonical", "")] + list(rec.get("aliases") or [])
        for n in names:
            if n:
                out.append((norm(n), cid, rec))
    return out


def resolve_person(name: str, data: dict | None = None) -> dict | None:
    """Return best match dict or None."""
    data = data or load_aliases()
    fuzzy_cfg = data.get("fuzzy") or {}
    min_r = float(fuzzy_cfg.get("min_ratio", 0.86))
    enabled = fuzzy_cfg.get("enabled", True)
    surname_aliases = data.get("surname_aliases") or {}

    q = norm(name)
    q2 = expand_surname_typos(name, surname_aliases)
    index = build_alias_index(data)

    # 1) exact alias
    for alias, cid, rec in index:
        if q == alias or q2 == alias:
            return {
                "match": "exact",
                "canonical_id": cid,
                "canonical": rec.get("canonical"),
                "role": rec.get("role"),
                "domain": rec.get("domain"),
                "score": 1.0,
                "query": name,
            }

    # 2) substring strong (canonical in query or vice versa) with length guard
    for alias, cid, rec in index:
        if len(alias) >= 4 and (alias in q2 or q2 in alias):
            # avoid short false positives
            if abs(len(alias) - len(q2)) <= 8 or alias in q2.split() or q2 in alias:
                return {
                    "match": "substring",
                    "canonical_id": cid,
                    "canonical": rec.get("canonical"),
                    "role": rec.get("role"),
                    "domain": rec.get("domain"),
                    "score": 0.95,
                    "query": name,
                }

    # 3) fuzzy
    if not enabled:
        return None
    best = None
    for alias, cid, rec in index:
        if len(alias) < 3:
            continue
        r = max(ratio(q, alias), ratio(q2, alias))
        # token-aware: compare last tokens for surnames
        qt, at = q2.split(), alias.split()
        if qt and at:
            r = max(r, ratio(qt[-1], at[-1]) * 0.5 + ratio(" ".join(qt[:1]), " ".join(at[:1])) * 0.5)
        if r >= min_r and (best is None or r > best["score"]):
            best = {
                "match": "fuzzy",
                "canonical_id": cid,
                "canonical": rec.get("canonical"),
                "role": rec.get("role"),
                "domain": rec.get("domain"),
                "score": round(r, 3),
                "query": name,
                "matched_alias": alias,
            }
    return best


def resolve_blob(text: str) -> list[dict]:
    """Find known people mentioned in free text / OCR."""
    data = load_aliases()
    hits = []
    seen = set()
    # candidate tokens: sequences of Capitalized words from original if mixed, else ngrams
    # also try each canonical + alias against text
    for alias, cid, rec in build_alias_index(data):
        if len(alias) < 3:
            continue
        # word boundary-ish
        if re.search(rf"(?i)(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", expand_surname_typos(text, data.get("surname_aliases") or {})):
            if cid not in seen:
                seen.add(cid)
                hits.append(
                    {
                        "match": "blob_alias",
                        "canonical_id": cid,
                        "canonical": rec.get("canonical"),
                        "role": rec.get("role"),
                        "domain": rec.get("domain"),
                        "score": 1.0,
                    }
                )
    # fuzzy surname bloome family block
    tnorm = expand_surname_typos(text, data.get("surname_aliases") or {})
    if re.search(r"\bbloom\b", tnorm):
        for token in re.findall(r"\b[A-Za-z]{3,15}\b", text):
            r = resolve_person(token + " bloom", data)
            if r and r["canonical_id"] not in seen and r["score"] >= 0.86:
                seen.add(r["canonical_id"])
                hits.append(r)
    return hits


def sync_aliases_to_entity_context() -> None:
    """Push canonical people into entity_context for domain_route."""
    data = load_aliases()
    ent = json.loads(ENTITY_PATH.read_text(encoding="utf-8"))
    people = ent.setdefault("people", [])
    by_role = { (p.get("role"), p.get("canonical") if False else None) for p in people }

    def upsert(names: list[str], role: str, domain: str, notes: str, extra: dict | None = None):
        names_l = [n.lower() for n in names if n]
        for row in people:
            if set(names_l) & {x.lower() for x in (row.get("names") or [])}:
                row["names"] = sorted(set([x.lower() for x in row.get("names") or []] + names_l))
                row["role"] = role
                row["domain"] = domain
                row["notes"] = notes
                if extra:
                    row.update(extra)
                return
        row = {
            "names": names_l,
            "role": role,
            "domain": domain,
            "notes": notes,
            "source": "entity_aliases_sync",
            "updated": "2026-07-11",
        }
        if extra:
            row.update(extra)
        people.append(row)

    for cid, rec in (data.get("canonical_people") or {}).items():
        names = [rec.get("canonical", "")] + list(rec.get("aliases") or [])
        # strip pure nickname-only that are too short for domain_route short match issues
        notes = rec.get("notes") or f"canonical_id={cid}"
        if rec.get("dob"):
            notes += f" DOB {rec['dob']}"
        if rec.get("mother"):
            notes += f" mother={rec['mother']}"
        upsert(names, rec.get("role", "person"), rec.get("domain", "Core-Personal/Family"), notes, {"canonical_id": cid})

    # family tree block
    ent["family_tree"] = {
        "self": "Jeffrey Bloom",
        "father": "Gary Bloom",
        "mother": "Jan / Janet Bloom",
        "sisters": ["Jenni", "Jodi"],
        "sons": [
            {
                "name": "Blaizen Buckshot Bloom",
                "dob": "2003-06-26",
                "mother": "Stefanie Lynn Folden",
                "note": "oldest",
            },
            {
                "name": "Spencer Anthony Bloom",
                "dob": "2013-10-01",
                "mother": "Sara Ballas",
                "note": "youngest",
            },
        ],
        "source": "jeff_2026-07-11",
    }
    ent["people"] = people
    ENTITY_PATH.write_text(json.dumps(ent, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="Names to resolve")
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--blob-file", default="")
    args = ap.parse_args()
    if args.sync:
        sync_aliases_to_entity_context()
        print(json.dumps({"synced": True}))
    data = load_aliases()
    for n in args.names:
        print(json.dumps(resolve_person(n, data), indent=2))
    if args.blob_file:
        text = Path(args.blob_file).read_text(encoding="utf-8", errors="replace")
        print(json.dumps(resolve_blob(text), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
