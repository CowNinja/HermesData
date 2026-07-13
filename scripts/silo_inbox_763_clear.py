#!/usr/bin/env python3
"""Apply Jeff 2026-07-13 Inbox-763 questionnaire defaults + codify policy."""
from __future__ import annotations

import json
import shutil
import sqlite3
# json used for policy + stdout
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SILO = Path(r"K:/Phronesis-Sovereign/Personal-Digital-Silo")
NSFW = SILO / "Core-Personal" / "Projects" / "from-g-drive" / "_private_nsfw"
RULES = Path(r"D:/HermesData/config/inbox_origin_rules.json")
DB = Path(r"D:/HermesData/state/ingest_registry.sqlite3")
ENTITY = Path(r"D:/HermesData/config/entity_context.json")
POLICY = Path(r"D:/HermesData/config/inbox_clear_policy.json")
RECEIPT = Path(r"D:/PhronesisVault/Operations/logs/silo-inbox-763-clear-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def codify(now: str) -> None:
    data = json.loads(RULES.read_text(encoding="utf-8"))
    ids = {r["id"] for r in data["rules"]}
    news = [
        {
            "id": "braingps_mricloud",
            "match_any_path_substr": ["99_braingps", "mricloud", "braingps"],
            "domain": "Medical-Records",
            "confidence": "high",
            "note": "Jeff Q1A brain imaging → Medical",
        },
        {
            "id": "volbrain_imaging",
            "match_any_path_substr": ["99_volbrain", "volbrain"],
            "domain": "Medical-Records",
            "confidence": "high",
            "note": "Jeff Q1A volBrain → Medical",
        },
        {
            "id": "private_nsfw",
            "match_any_path_substr": [
                "dirty things to moan",
                "nsfw",
                "onlyfans",
                "porn",
                "xxx",
                "erotic",
            ],
            "domain": "Core-Personal/Projects",
            "confidence": "high",
            "note": "Jeff Q5A → Projects/_private_nsfw",
        },
    ]
    for r in news:
        if r["id"] not in ids:
            data["rules"].insert(0, r)
    policy = {
        "at": now,
        "Q1": "A Medical imaging archive",
        "Q2": "A Digital-Footprint Android",
        "Q3": "A provenance stubs clear Inbox domain",
        "Q4": "A ghost_cleared",
        "Q5": "A Projects/_private_nsfw",
        "Q6": "A Medical or Family by name",
        "Q7": "A Projects BooksBloom business",
        "Q8": "A Life-Archive nested default",
        "private_nsfw_path": str(NSFW),
    }
    data["jeff_inbox_763_policy"] = policy
    RULES.write_text(json.dumps(data, indent=2), encoding="utf-8")
    POLICY.write_text(json.dumps(policy, indent=2), encoding="utf-8")
    if ENTITY.exists():
        try:
            ent = json.loads(ENTITY.read_text(encoding="utf-8"))
        except Exception:
            ent = {}
        ent["inbox_clear_policy_2026_07_13"] = policy
        ent["private_nsfw_path"] = str(NSFW)
        ENTITY.write_text(json.dumps(ent, indent=2), encoding="utf-8")
    NSFW.mkdir(parents=True, exist_ok=True)
    readme = NSFW / "00-README.md"
    if not readme.exists():
        readme.write_text(
            "# Private NSFW holding\n\n"
            "Jeff policy 2026-07-13 Q5A: explicit material under Projects nested origin.\n"
            "Not twin-training gold by default.\n",
            encoding="utf-8",
        )


def classify(path: str) -> tuple[str, str]:
    low = path.lower().replace("/", "\\")
    name = Path(path).name.lower()
    if any(
        k in low
        for k in (
            "dirty things to moan",
            "nsfw",
            "onlyfans",
            "porn",
            "xxx",
            "erotic",
        )
    ):
        return "Core-Personal/Projects", "private_nsfw"
    if any(
        k in low
        for k in (
            "99_braingps",
            "mricloud",
            "braingps",
            "99_volbrain",
            "volbrain",
            "dicom",
            ".dcm",
            ".nii",
        )
    ):
        return "Medical-Records", "imaging_archive"
    if "android" in low:
        return "Digital-Footprint", "android"
    if "booksbloom" in low or "farms" in name:
        return "Core-Personal/Projects", "booksbloom_business"
    if any(
        k in low
        for k in (
            "richardson",
            "endocrin",
            "medical",
            "medicaid",
            "spencer",
            "vamc",
            "tricare",
        )
    ):
        if "spencer" in low or "medicaid" in low or "jan bloom" in low:
            return "Core-Personal/Family", "family_medicalish"
        return "Medical-Records", "medical_doc"
    if name.endswith((".gdoc", ".gsheet", ".gslides", ".gform")):
        return "Core-Personal/Life-Archive", "google_stub"
    if "\\pers\\" in low or low.rstrip("\\").endswith("\\pers"):
        return "Core-Personal/Life-Archive", "pers"
    return "Core-Personal/Life-Archive", "default_q8a"


def shelf_dest(domain: str, dest: str, why: str) -> Path | None:
    if not dest:
        return None
    p = Path(dest)
    parts = str(p).replace("/", "\\").split("\\")
    rel = None
    for i, x in enumerate(parts):
        if x.lower() == "from-g-drive":
            rel = "\\".join(parts[i + 1 :])
            break
    if rel is None:
        rel = p.name
    if why == "private_nsfw":
        return NSFW / Path(rel).name
    return SILO / domain / "from-g-drive" / rel


def main() -> int:
    now = utc()
    codify(now)
    con = sqlite3.connect(str(DB), timeout=180)
    con.execute("PRAGMA busy_timeout=180000")
    rows = con.execute(
        "SELECT id, dest_path, source_path, sha256 FROM ingest WHERE domain LIKE '%Inbox%'"
    ).fetchall()
    stats: Counter[str] = Counter()
    moved = 0
    domain_updates = 0

    for id_, dest, src, sha in rows:
        path = dest or src or ""
        domain, why = classify(path)
        stats[why] += 1
        p = Path(dest) if dest else None
        exists = bool(p and p.is_file())

        if why == "google_stub":
            new_dest = dest
            if exists:
                nd = shelf_dest(domain, dest, why)
                if nd and p and nd.resolve() != p.resolve():
                    try:
                        nd.parent.mkdir(parents=True, exist_ok=True)
                        if nd.exists():
                            nd = nd.with_name(nd.stem + "__stub" + nd.suffix)
                        shutil.move(str(p), str(nd))
                        new_dest = str(nd)
                        moved += 1
                    except Exception:
                        stats["stub_move_err"] += 1
            con.execute(
                "UPDATE ingest SET domain=?, dest_path=COALESCE(?, dest_path), "
                "process_status=?, notes=COALESCE(notes,'')||?, last_seen=? WHERE id=?",
                (
                    domain,
                    new_dest,
                    "provenance_stub",
                    f" |Q3A stub {now}",
                    now,
                    id_,
                ),
            )
            domain_updates += 1
            continue

        if not exists:
            if sha:
                alt = con.execute(
                    "SELECT dest_path, domain FROM ingest WHERE sha256=? "
                    "AND domain NOT LIKE '%Inbox%' AND dest_path IS NOT NULL LIMIT 1",
                    (sha,),
                ).fetchone()
                if alt and Path(alt[0]).is_file():
                    con.execute(
                        "UPDATE ingest SET domain=?, dest_path=?, last_seen=? WHERE id=?",
                        (alt[1], alt[0], now, id_),
                    )
                    domain_updates += 1
                    stats["ghost_repoint"] += 1
                    continue
            con.execute(
                "UPDATE ingest SET domain=?, process_status=?, "
                "notes=COALESCE(notes,'')||?, last_seen=? WHERE id=?",
                (
                    domain,
                    "ghost_cleared",
                    f" |Q4A ghost_cleared {now} why={why}",
                    now,
                    id_,
                ),
            )
            domain_updates += 1
            stats["ghost_cleared"] += 1
            continue

        nd = shelf_dest(domain, dest, why)
        if nd is None or p is None:
            continue
        new_dest = dest
        try:
            if nd.resolve() != p.resolve():
                nd.parent.mkdir(parents=True, exist_ok=True)
                if nd.exists():
                    nd = nd.with_name(nd.stem + "__inbox" + nd.suffix)
                shutil.move(str(p), str(nd))
                new_dest = str(nd)
                moved += 1
        except Exception:
            stats["move_err"] += 1
            continue
        con.execute(
            "UPDATE ingest SET domain=?, dest_path=?, process_status=?, last_seen=? WHERE id=?",
            (domain, new_dest, "rehomed_q_policy", now, id_),
        )
        domain_updates += 1

    con.commit()
    inbox_left = con.execute(
        "SELECT COUNT(*) FROM ingest WHERE domain LIKE '%Inbox%'"
    ).fetchone()[0]
    con.close()

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(
        f"""# Inbox 763 clear — {now}

Jeff: 1A 2A 3A 4A 5A(+_private_nsfw) 6A 7A 8A

| Stat | Value |
|------|------:|
| Domain updates | {domain_updates} |
| Files moved | {moved} |
| Inbox remaining | {inbox_left} |

Why: {dict(stats)}

NSFW: `{NSFW}`
Policy: `D:/HermesData/config/inbox_clear_policy.json`
""",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "domain_updates": domain_updates,
                "moved": moved,
                "inbox_left": inbox_left,
                "stats": dict(stats),
                "receipt": str(RECEIPT),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
