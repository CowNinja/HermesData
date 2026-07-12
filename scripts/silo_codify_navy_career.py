#!/usr/bin/env python3
"""Codify Jeff Navy career arc + addresses + role confirmations (2026-07-12 amplify)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
p = Path(r"D:\HermesData\config\entity_context.json")
d = json.loads(p.read_text(encoding="utf-8"))
people = d.setdefault("people", [])
orgs = d.setdefault("orgs", [])
places = d.setdefault("places", [])


def upsert(lst, can, **kw):
    for row in lst:
        if str(row.get("canonical") or "").lower() == can.lower():
            row.update({k: v for k, v in kw.items() if k != "names"})
            row["canonical"] = can
            row["confidence"] = kw.get("confidence", "confirmed")
            row["updated"] = ts
            names = list(dict.fromkeys((row.get("names") or []) + kw.get("names", [can]) + [can]))
            row["names"] = names
            return
    lst.append(
        {
            "canonical": can,
            "names": list(dict.fromkeys(kw.get("names") or [can])),
            "confidence": kw.get("confidence", "confirmed"),
            "updated": ts,
            **{k: v for k, v in kw.items() if k != "names"},
        }
    )


# --- Full Navy career (Jeff order; spellings checked) ---
# STA-21 = Seaman to Admiral-21 (not "semen")
# BOOST = Broadened Opportunity for Officer Selection and Training (legacy STA path component)
# NSI = Naval Science Institute (OTC Newport, ~8 weeks officer prep for STA-21)
# HRNROTC = Hampton Roads NROTC unit at ODU

career = {
    "updated": ts,
    "source": "jeff_narrative_2026-07-12 + silo path corroboration",
    "spellings": {
        "STA-21": "Seaman to Admiral-21 (enlisted-to-commissioning)",
        "BOOST": "BOOST program / class (photo 08-05-01 BOOST class photo.jpg in silo)",
        "NSI": "Naval Science Institute — Officer Training Command Newport (OTCN), RI",
        "HRNROTC": "Hampton Roads Naval Reserve Officers Training Corps (at ODU)",
        "ODU": "Old Dominion University — Electrical Engineering Technology degree path",
        "CVN-65": "USS Enterprise CVN-65",
        "FFG-55": "USS Elrod FFG-55",
        "NCDOC": "Navy Cyber Defense Operations Command — last command, Suffolk VA area",
        "RTC": "Recruit Training Command Great Lakes",
    },
    "sequence": [
        {
            "order": 1,
            "id": "RTC_Great_Lakes",
            "name": "RTC Great Lakes",
            "type": "boot_camp",
            "silo_hits_note": "RTC/Great Lakes path hits present",
        },
        {
            "order": 2,
            "id": "USS_Enterprise_CVN65",
            "name": "USS Enterprise (CVN-65)",
            "type": "sea_duty",
            "silo_hits_note": "Enterprise ~67 · CVN ~23 path hits",
        },
        {
            "order": 3,
            "id": "OTC_Newport_STA21",
            "name": "Officer Training Command Newport — STA-21 (BOOST + NSI)",
            "type": "commissioning_pipeline",
            "detail": "Selected Seaman to Admiral (STA-21); attended BOOST and Naval Science Institute at Newport, RI",
            "silo_hits_note": "STA-21 ~79 · Newport ~595 · NSI many · BOOST class photo 2008-05-01",
        },
        {
            "order": 4,
            "id": "HRNROTC_ODU",
            "name": "HRNROTC at Old Dominion University",
            "type": "nrotc_degree",
            "detail": "Electrical Engineering Technology degree path; interrupted by car accident → TBI",
            "silo_hits_note": "HRNROTC ~390 · NROTC ~540 · ODU ~787",
        },
        {
            "order": 5,
            "id": "USS_Elrod_FFG55",
            "name": "USS Elrod (FFG-55)",
            "type": "sea_duty",
            "detail": "Detailed after TBI interruption of ODU path",
            "silo_hits_note": "Elrod/USS ~16k paths (cruise book heavy)",
        },
        {
            "order": 6,
            "id": "NCDOC",
            "name": "NCDOC (Navy Cyber Defense Operations Command)",
            "type": "shore_last_command",
            "detail": "Last command — Suffolk VA area",
            "silo_hits_note": "NCDOC ~611",
        },
    ],
    "open_for_dates": "Exact report dates / rates / NEC — fill from LES/orders/eval waves as OCR improves",
}

d["navy_career_arc"] = career

# Orgs
for can, names, notes, domain in [
    ("RTC Great Lakes", ["RTC", "RTC Great Lakes", "Great Lakes", "Recruit Training Command"], "Boot camp — Jeff sequence #1", "Navy-Service"),
    ("USS Enterprise CVN-65", ["USS Enterprise", "Enterprise", "CVN-65", "CVN 65", "CVN65"], "Jeff sequence #2 sea duty", "Navy-Service"),
    ("Officer Training Command Newport", ["OTC Newport", "OTCN", "Newport Rhode Island", "Officer Training Command"], "STA-21 BOOST + NSI location", "Navy-Service"),
    ("STA-21", ["STA-21", "STA21", "Seaman to Admiral", "Seaman to Admiral-21"], "Enlisted-to-commissioning program Jeff selected for", "Navy-Service"),
    ("BOOST", ["BOOST"], "BOOST component of STA-21 path; class photo 08-05-01", "Navy-Service"),
    ("Naval Science Institute", ["NSI", "Naval Science Institute"], "NSI at OTC Newport for STA-21", "Navy-Service"),
    ("HRNROTC", ["HRNROTC", "Hampton Roads NROTC", "Hampton Roads Naval Reserve Officers Training Corps"], "NROTC unit at ODU", "Navy-Service"),
    ("Old Dominion University", ["ODU", "Old Dominion University"], "EET degree when TBI from car accident", "Core-Personal/Education"),
    ("USS Elrod FFG-55", ["USS Elrod", "Elrod", "FFG-55", "FFG55"], "Jeff sequence #5 after ODU interruption", "Navy-Service"),
    ("NCDOC", ["NCDOC", "Navy Cyber Defense Operations Command"], "LAST command Suffolk VA", "Navy-Service"),
    ("Naval Medical Center Portsmouth", ["NMCP", "Naval Medical Center Portsmouth"], "Big Navy hospital Portsmouth; LCDR Cann PCM", "Medical-Records"),
]:
    upsert(orgs, can, names=names, notes=notes, domain=domain, type="navy_or_edu")

# Addresses
d["addresses"] = {
    "updated": ts,
    "current": {
        "line1": "103 Whimbrel Drive",
        "city": "Suffolk",
        "state": "VA",
        "zip": "23435",
        "notes": "Jeff current; silo Whimbrel ~441 hits",
    },
    "prior": [
        {
            "area": "Norfolk VA condo",
            "approx_purchase": "2008 (Jeff belief)",
            "notes": "Before Suffolk; lived various places before condo",
            "silo": "condo ~193 · Norfolk ~431",
        },
        {
            "area": "various pre-condo",
            "notes": "Jeff: lived all over before Norfolk condo",
        },
    ],
}
upsert(places, "103 Whimbrel Drive, Suffolk VA 23435",
       names=["Whimbrel", "103 Whimbrel", "Whimbrel Drive"],
       notes="Current home Jeff confirmed", type="residence")
upsert(places, "Norfolk VA (condo ~2008+)", names=["Norfolk condo", "Norfolk"], notes="Prior residence before Suffolk", type="residence")
upsert(places, "Newport, RI", names=["Newport", "Newport Rhode Island"], notes="OTC STA-21 BOOST/NSI", type="military_training")
upsert(places, "Great Lakes, IL", names=["Great Lakes", "RTC Great Lakes"], notes="Boot camp", type="military_training")

# People role locks
upsert(people, "CTN1 Means",
       names=["CTN1 Means", "Means"],
       domain="Navy-Service", role="lpo_ncdoc",
       notes="Jeff: LPO (Lead Petty Officer) at NCDOC. Confirmed.")
upsert(people, "Dr Foster",
       names=["Dr Foster"],
       domain="Medical-Records", role="psychologist_nmcp",
       notes="Jeff: psychologist at NMCP (not generic provider). Confirmed.")
upsert(people, "LCDR Cann",
       names=["LCDR Cann", "Dr Cann", "Helen Cann", "Helen L. Cann"],
       domain="Medical-Records", role="nmcp_pcm",
       notes="Jeff: LCDR Cann PCM at NMCP Portsmouth. Confirmed.")
upsert(people, "Christina Barefield",
       names=["Christina Barefield", "Christy Barefield", "Barefield, Christy", "Christina Barefield, OT"],
       domain="Medical-Records", role="occupational_therapist",
       notes="OT Dec2019–Jan2020 calendar — post-TBI civilian OT (not NMCP PCM era). Photo Barefield, Christy.")
upsert(people, "Marjorie Stevenson",
       names=["Marjorie Stevenson", "Marjorie Stevenson, PT"],
       domain="Medical-Records", role="physical_therapist",
       notes="PT late 2019–2020 calendar — post-TBI community PT (dates after active NMCP-heavy period).")

# TBI timeline note
d["tbi_medical_notes"] = {
    "updated": ts,
    "event": "Car accident during HRNROTC/ODU EET studies → traumatic brain injury",
    "diagnosis_clinician": "Dr Gregory J. O'Shanick (CNSVA) — also low cortisol identification",
    "referral_path": "BIAV → O'Shanick",
    "cortisol_silo": "NMCP ER low cortisol Jan 2018; ACTH stim tests; Decadron treatment docs present",
}

d["updated"] = ts
d.setdefault("interview_log", []).append({"at": ts, "event": "full_navy_arc_addresses_roles"})
p.write_text(json.dumps(d, indent=2), encoding="utf-8")

# Vault career card
Path(r"D:\PhronesisVault\Research\Silo-Entities\Navy-Career-Arc.md").write_text(
    f"""# Navy career arc — Jeffrey Jay Bloom

_Updated {ts} · Jeff-confirmed sequence + silo corroboration_

## Sequence
1. **RTC Great Lakes** — boot camp  
2. **USS Enterprise (CVN-65)**  
3. **OTC Newport / STA-21** — **BOOST** + **NSI** (Seaman to Admiral-21 enlisted-to-commissioning)  
4. **HRNROTC @ ODU** — Electrical Engineering Technology; **car accident → TBI**  
5. **USS Elrod (FFG-55)** — detailed after ODU interruption  
6. **NCDOC** — **last command** (Suffolk VA)

## Spellings (locked)
| Term | Meaning |
|------|---------|
| STA-21 | Seaman to Admiral-21 |
| BOOST | Officer path component (class photo 2008-05-01 in silo) |
| NSI | Naval Science Institute (OTC Newport) |
| HRNROTC | Hampton Roads NROTC (ODU) |
| CVN-65 | USS Enterprise |
| FFG-55 | USS Elrod |
| NCDOC | Navy Cyber Defense Operations Command |

## Key people at commands
| Person | Role |
|--------|------|
| CTN1 Means | **LPO at NCDOC** |
| ITC Melvin Johnson | **Boss at NCDOC** |
| LCDR Cann | **PCM at NMCP** |
| Dr Foster | **Psychologist at NMCP** |
| Dr Rodriguez | **Psychiatrist at Boone BHC** (Little Creek) |
| Dr O'Shanick | **TBI diagnosis + cortisol** (CNSVA via BIAV) |

## Homes
- Prior: Norfolk condo (~2008) after various rentals  
- Current: **103 Whimbrel Drive, Suffolk VA 23435**

## Open (OCR / records)
Exact report dates, rates, NECs — harvest from LES/orders/evals as robust re-OCR runs.
""",
    encoding="utf-8",
)
print(json.dumps({"career_steps": 6, "orgs": len(orgs), "people": len(people)}))
