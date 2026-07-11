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
            "source": "jeff_interview_round3",
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
            "source": "jeff_interview_round3",
            "updated": ts,
        }
    )
    return "added"


# 1 Abigail - VA/legal matter -> Projects
print(
    "abigail",
    upsert_org(
        ["abigail", "abigail va"],
        "Core-Personal/Projects",
        "va_legal_matter",
        "VA reply brief / legal matter. R3 best guess confirmed.",
    ),
)

# 2 BHC Sewell's Point - Navy medical center where Jeff received care
print(
    "bhc",
    upsert_org(
        [
            "bhc sewell's point",
            "bhc sewells point",
            "sewell's point",
            "sewells point",
            "bhc",
        ],
        "Medical-Records",
        "navy_medical_center",
        "Navy medical center (Sewell's Point) where Jeff received care. R3",
    ),
)

# 3 Condo + Cox - housing Family, ISP Finance
print(
    "condo",
    upsert_org(
        ["condo", "home theater config condo"],
        "Core-Personal/Family",
        "housing",
        "Condo owned/lived Norfolk VA. R3",
    ),
)
print(
    "cox",
    upsert_org(
        ["cox", "cox communications", "cox cable"],
        "Core-Personal/Finance",
        "isp_utility",
        "ISP while in Norfolk condo. R3",
    ),
)

# 4 HubDuino / Ogorchock / ST_Anything - Projects
print(
    "hubduino",
    upsert_org(
        [
            "hubduino",
            "st_anything",
            "st-anything",
            "daniel ogorchock",
            "ogorchock",
        ],
        "Core-Personal/Projects",
        "smart_home_oss",
        "Maker/smart-home project stack. R3",
    ),
)

# 5 Kidde - household product safety
print(
    "kidde",
    upsert_org(
        ["kidde", "kidde product safety"],
        "Core-Personal/Family",
        "household_product_recall",
        "Product safety recall docs. R3",
    ),
)

d["updated"] = ts
d["people"] = people
d["orgs"] = orgs
ENTITY.write_text(json.dumps(d, indent=2), encoding="utf-8")

Path(r"D:\PhronesisVault\Operations\logs\entity-interview-round3-2026-07-10.md").write_text(
    f"""# Entity interview Round 3 — {ts}

| # | Entity | Jeff | Domain |
|---|--------|------|--------|
| 1 | Abigail | VA/legal matter (best guess OK) | Projects |
| 2 | BHC Sewell's Point | Navy **medical center** (care there) | Medical-Records |
| 3 | Condo + Cox | Norfolk condo home + ISP | Family + Finance |
| 4 | HubDuino / Ogorchock / ST_Anything | Tech project | Projects |
| 5 | Kidde | Household product/safety | Family |

""",
    encoding="utf-8",
)

sys.path.insert(0, r"D:\HermesData\scripts")
import importlib
import domain_route

importlib.reload(domain_route)
for t in [
    "Abigail VA reply brief at 100%.gdoc",
    "The Unofficial Map Guide To BHC Sewell's Point.pdf",
    "2010-08-07 - Home Theater Config Condo shelf and Cox.pdf",
    "DanielOgorchock-ST_Anything-HubDuino-Drivers-RAW.txt",
    "00-Kidde Product Safety Recall-merged.docx",
]:
    print(domain_route.domain_for(t), "|", t[:55])
