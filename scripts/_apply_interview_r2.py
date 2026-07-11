#!/usr/bin/env python3
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ENTITY = Path(r"D:\HermesData\config\entity_context.json")
d = json.loads(ENTITY.read_text(encoding="utf-8"))
ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
people = d.setdefault("people", [])
orgs = d.setdefault("orgs", [])


def upsert_person(names, role, domain, notes=""):
    names = [n.lower() for n in names]
    for row in people:
        existing = {x.lower() for x in row.get("names") or []}
        if set(names) & existing:
            row["names"] = sorted(set(list(existing) + names))
            row["role"] = role
            row["domain"] = domain
            if notes:
                row["notes"] = notes
            return "updated"
    people.append(
        {
            "names": names,
            "role": role,
            "domain": domain,
            "notes": notes,
            "source": "jeff_interview_round2",
            "updated": ts,
        }
    )
    return "added"


def upsert_org(names, domain, role="", notes=""):
    names = [n.lower() for n in names]
    for row in orgs:
        existing = {x.lower() for x in row.get("names") or []}
        if set(names) & existing:
            row["names"] = sorted(set(list(existing) + names))
            row["domain"] = domain
            if role:
                row["role"] = role
            if notes:
                row["notes"] = notes
            return "updated"
    orgs.append(
        {
            "names": names,
            "domain": domain,
            "role": role,
            "notes": notes,
            "source": "jeff_interview_round2",
            "updated": ts,
        }
    )
    return "added"


print(
    "booksbloom",
    upsert_org(
        ["booksbloom", "books bloom", "booksbloom logo"],
        "Core-Personal/Projects",
        "family_business",
        "Parents book business Jeff helps with. R2",
    ),
)
print(
    "dameion",
    upsert_person(
        ["dameion", "dameionlove", "dameionlove@gmail.com"],
        "friend_navy",
        "Core-Personal/Family",
        "Possible Navy friend. R2",
    ),
)
print(
    "scymed",
    upsert_org(
        ["scymed", "scymed network"],
        "Medical-Records",
        "lab_calc_project",
        "Project for medical lab result calculations. R2",
    ),
)
print(
    "cnda",
    upsert_org(
        [
            "cnda",
            "certified network defence architect",
            "certified network defense architect",
        ],
        "Navy-Service",
        "navy_cert_training",
        "Navy-related cert/training. R2",
    ),
)
print(
    "peterson",
    upsert_person(
        ["jordan peterson", "peterson"],
        "thought_leader",
        "Life-Archive",
        "Inspirational thought leader / media. R2",
    ),
)
print(
    "marcinko",
    upsert_person(
        ["richard marcinko", "marcinko"],
        "author_navy_seal_inspiration",
        "Navy-Service",
        "Author and Navy SEAL inspiration. R2",
    ),
)

d["updated"] = ts
d["people"] = people
d["orgs"] = orgs
ENTITY.write_text(json.dumps(d, indent=2), encoding="utf-8")

Path(r"D:\PhronesisVault\Operations\logs\entity-interview-round2-2026-07-10.md").write_text(
    f"""# Entity interview Round 2 — {ts}

| # | Entity | Jeff | Domain |
|---|--------|------|--------|
| 1 | BooksBloom | Parents book business (Jeff helps) | Projects |
| 2 | Dameion / dameionlove | Possible Navy friend | Family |
| 3 | ScyMed | Medical lab calc project | Medical-Records |
| 4 | CNDA | Navy-related | Navy-Service |
| 5 | Jordan Peterson | Thought leader | Life-Archive |
| 6 | Richard Marcinko | Author + Navy SEAL inspiration | Navy-Service |

Lexicon: entity_context.json
""",
    encoding="utf-8",
)

sys.path.insert(0, r"D:\HermesData\scripts")
import importlib
import domain_route

importlib.reload(domain_route)
for t in [
    "BooksBloom Logo-small.png",
    "dameionlove@gmail.com search.pdf",
    "ScyMed Network Alphabetic Index.gsheet",
    "Certified Network Defence Architect CNDA.pdf",
    "Jordan Peterson Is Walter White.gdoc",
    "Richard Marcinko - Order of Books.gsheet",
]:
    print(domain_route.domain_for(t), "|", t[:50])
