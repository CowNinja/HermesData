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
            row["source"] = row.get("source") or "jeff_interview"
            return "updated"
    people.append(
        {
            "names": names,
            "role": role,
            "domain": domain,
            "notes": notes,
            "source": "jeff_interview_round1",
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
            "source": "jeff_interview_round1",
            "updated": ts,
        }
    )
    return "added"


print("gary", upsert_person(
    ["gary bloom", "gary"],
    "father",
    "Core-Personal/Family",
    "Jeff dad — interview R1",
))
print("qadeeb", upsert_org(
    ["ahmed al-qadeeb", "ahmad al-qadeeb", "al-qadeeb", "qadeeb", "ahmed", "ahmad"],
    "Core-Personal/Projects",
    "osint_target",
    "Work/investigation target — not personal relationship. R1",
))
print("lowes", upsert_org(
    ["lowe's", "lowes", "lowe"],
    "Core-Personal/Finance",
    "retail",
    "Shopping/store R1",
))
print("crosswater", upsert_org(
    ["crosswater", "crosswater bcc"],
    "Core-Personal/Spiritual",
    "former_church",
    "Former church Jeff was member of. R1",
))
print("n332", upsert_org(
    ["n332", "n332 division", "ncdoc", "nc doc"],
    "Navy-Service",
    "navy_command",
    "NCDOC station until March 2018; N332 division. R1",
))

d["updated"] = ts
d["people"] = people
d["orgs"] = orgs
ENTITY.write_text(json.dumps(d, indent=2), encoding="utf-8")
print("saved")

log = Path(r"D:\PhronesisVault\Operations\logs\entity-interview-round1-2026-07-10.md")
log.write_text(
    f"""# Entity interview Round 1 — {ts}

| # | Entity | Jeff | Domain / role |
|---|--------|------|----------------|
| 1 | Gary Bloom | **Dad** | Family / father |
| 2 | Ahmed Al-Qadeeb | **Target** (work) | Projects / osint_target |
| 3 | Lowe's | Shopping | Finance / retail |
| 4 | Crosswater | **Former church** (member) | Spiritual |
| 5 | N332 / NCDOC | Navy until Mar 2018 | Navy-Service |
| 6 | Corinthians | Scripture | Spiritual rules only |
| 7 | Cont. | Ask as found | — |

Lexicon: `D:/HermesData/config/entity_context.json`
""",
    encoding="utf-8",
)

sys.path.insert(0, r"D:\HermesData\scripts")
import importlib
import domain_route

importlib.reload(domain_route)
tests = [
    "2021-09-10 - Gary Bloom call Log.csv",
    "Ahmed Al-Qadeeb 01 All Content.txt",
    "Lowes orders.xlsx",
    "Crosswater BCC addresses.gsheet",
    "N332 Division site (new).txt",
    "1 Corinthians 1-10-17.gdoc",
]
for t in tests:
    print(domain_route.domain_for(t), "|", t[:55])
