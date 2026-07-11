#!/usr/bin/env python3
"""Parse church/community photo-directory OCR into structured training data.

Handles compound docs: image page + OCR names → families JSON + train.md + placeholders.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ENTITY = Path(r"D:\HermesData\config\entity_context.json")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_families(ocr_text: str) -> list[dict]:
    """Parse patterns like SURNAME: A, B / C, D or SURNAME: A, B w/ C + D."""
    families = []
    # normalize
    text = ocr_text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    # split on ALLCAPS surname tokens followed by colon
    for m in re.finditer(
        r"\b([A-Z]{2,}(?:[A-Z\-']*[A-Z])?)\s*[:;]\s*([^:]+?)(?=\s+[A-Z]{2,}\s*[:;]|\s*$)",
        text,
    ):
        surname = m.group(1).strip(" .")
        rest = m.group(2).strip(" /,-")
        # skip garbage
        if len(surname) < 2 or surname in {"THE", "AND", "FOR", "WITH"}:
            continue
        # members: split on , / +
        raw_parts = re.split(r"[,/+\|]+|\bw/\b|\bw/o\b", rest)
        members = []
        for p in raw_parts:
            p = re.sub(r"[^A-Za-z\-\s\.]", " ", p)
            p = re.sub(r"\s+", " ", p).strip(" .")
            if len(p) < 2 or len(p) > 40:
                continue
            if p.upper() == p and len(p) > 12:
                continue
            # title case
            members.append(p.title())
        if not members:
            continue
        families.append(
            {
                "surname": surname.title(),
                "members": members,
                "raw": m.group(0)[:120],
            }
        )
    return families


def write_structured(image_path: Path, ocr_path: Path, families: list[dict], context: str) -> dict:
    base = image_path
    out_json = Path(str(base) + ".compound.json")
    out_md = Path(str(base) + ".compound.train.md")
    rec = {
        "type": "photo_directory_compound",
        "image": str(image_path),
        "ocr_source": str(ocr_path),
        "context": context,
        "family_count": len(families),
        "families": families,
        "tags": [
            "compound_document",
            "photo_directory",
            "church_community",
            "multi_person",
            "needs_human_link",
            "twin_ok",
        ],
        "primary_domain": "Core-Personal/Spiritual",
        "secondary_tags": ["friends_community", "family_mentions"],
        "at": utc(),
    }
    out_json.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    lines = [
        f"# Compound extract: {image_path.name}",
        "",
        f"Context: {context}",
        f"Families parsed: {len(families)}",
        "",
        "This is a **photo directory page** (images + names). Training use:",
        "- social/community graph around Jeff",
        "- not clinical medical",
        "- link confirmed people to Friends/Family lexicon over time",
        "",
        "## Families",
        "",
    ]
    for fam in families:
        lines.append(f"### {fam['surname']}")
        for m in fam["members"]:
            lines.append(f"- {m}")
        lines.append("")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    rec["compound_json"] = str(out_json)
    rec["compound_train_md"] = str(out_md)
    return rec


def seed_placeholders(families: list[dict], context: str, limit: int = 40) -> int:
    d = json.loads(ENTITY.read_text(encoding="utf-8"))
    existing = set()
    for row in d.get("people") or []:
        for n in row.get("names") or []:
            existing.add(n.lower())
    added = 0
    for fam in families:
        if added >= limit:
            break
        sur = fam["surname"]
        for m in fam["members"][:6]:
            full = f"{m} {sur}".strip()
            key = full.lower()
            # skip if looks like Jeff family already known
            if any(x in key for x in ("jeff", "gary", "jan", "jenni", "jodi", "bloom", "bloome")):
                continue
            if key in existing or m.lower() in existing:
                continue
            d.setdefault("people", []).append(
                {
                    "names": [key, m.lower()],
                    "role": "placeholder",
                    "domain": "Core-Personal/Friends",
                    "status": "placeholder",
                    "notes": f"PLACEHOLDER from {context} directory OCR; church/community until confirmed",
                    "source": "compound_directory_parse",
                    "updated": utc()[:10],
                }
            )
            existing.add(key)
            added += 1
            if added >= limit:
                break
    d["updated"] = utc()[:10]
    ENTITY.write_text(json.dumps(d, indent=2), encoding="utf-8")
    return added


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ocr_md")
    ap.add_argument("--image", default="")
    ap.add_argument("--context", default="Crosswater church directory")
    ap.add_argument("--placeholders", action="store_true")
    args = ap.parse_args()
    ocr_path = Path(args.ocr_md)
    text = ocr_path.read_text(encoding="utf-8", errors="replace")
    # strip header
    if "---" in text:
        text = text.split("---", 1)[-1]
    families = parse_families(text)
    image = Path(args.image) if args.image else Path(str(ocr_path).replace(".ocr.md", ""))
    rec = write_structured(image, ocr_path, families, args.context)
    if args.placeholders:
        rec["placeholders_added"] = seed_placeholders(families, args.context)
    print(json.dumps({"families": len(families), **{k: rec[k] for k in rec if k != "families"}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
