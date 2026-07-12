#!/usr/bin/env python3
"""Affirm/correct Navy career dates from Jeff + silo detective."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
p = Path(r"D:\HermesData\config\entity_context.json")
d = json.loads(p.read_text(encoding="utf-8"))

d["navy_career_arc"] = {
    "updated": ts,
    "source": "jeff_memory + silo document dates",
    "confidence": "high_on_dated_docs",
    "sequence": [
        {
            "order": 1,
            "phase": "MEPS_enlistment",
            "dates": {"meps_orders": "2003-02-03", "enlist": "2003-02-12"},
            "evidence": ["2003-02-03 MEPS ORDERS", "2003-02-12 DD4 enlistment"],
            "status": "affirmed",
        },
        {
            "order": 2,
            "phase": "RTC_Great_Lakes",
            "dates": {"report": "2003-02-13", "approx_end": "2003-04"},
            "jeff": "February 2003, ~8 weeks boot",
            "evidence": ["2003-02-13 RTMP035R Gain Entry Report RTC Great Lakes"],
            "status": "affirmed",
        },
        {
            "order": 3,
            "phase": "IT_A_School_Great_Lakes",
            "dates": {"graduate": "2003-08-05"},
            "course": "IT Class A School A-202-0014",
            "evidence": ["2003-08-05 IT A School Graduate Certificate"],
            "status": "affirmed",
        },
        {
            "order": 4,
            "phase": "SARP_Great_Lakes",
            "dates": {"approx": "2003_between_A_school_and_Enterprise"},
            "jeff": "SARP at Great Lakes for drinking problem",
            "evidence": "filename miss so far — Jeff narrative; OCR body search pending",
            "status": "jeff_memory_pending_doc",
        },
        {
            "order": 5,
            "phase": "USS_Enterprise_CVN65",
            "dates": {
                "orders_signed": "2003-07-30",
                "approx_report": "2003-08_after_A_school",
                "onboard_through": "2008-02",
            },
            "jeff": "Thought June/July 2003 transfer",
            "correction": "Orders 2003-07-30; A-school grad 2003-08-05 → report likely Aug 2003",
            "evidence": [
                "2003-07-30 CVN65 Orders signed",
                "2003-11-05 CVN65 letters",
                "2007 STA-21 LOR CVN65",
                "2008-01-10 CVN65 reenlistment",
                "2008-02-26 Enterprise to OTCN reporting info",
            ],
            "status": "affirmed_start_corrected",
        },
        {
            "order": 6,
            "phase": "OTC_Newport_STA21_BOOST_NSI",
            "dates": {
                "report_newport": "2008-02-26",
                "boost_photo": "2008-05-01",
                "detach_hrnrotc": "2008-07-16",
            },
            "jeff": "Left Enterprise early 2008 for Newport — months then ODU",
            "evidence": [
                "2008-02-26 NSIPS Newport report / Enterprise to OTCN",
                "2008-02-28 Tricare Newport RI",
                "2008-05-01 BOOST class photo",
                "2008-07-16 OTCN detaching to HRNROTC",
            ],
            "status": "affirmed",
        },
        {
            "order": 7,
            "phase": "HRNROTC_ODU",
            "dates": {"orders": "2008-07-22", "checkin": "2008-07-22"},
            "evidence": [
                "2008-07-22 Orders HRNROTC signed",
                "2008-07-22 NSIPS HRNROTC reporting",
                "2008-07 ODU ID / STA-21 TA fall 2008",
            ],
            "status": "affirmed",
        },
        {
            "order": 8,
            "phase": "MVA_TBI",
            "dates": {"accident": "2009-10-21"},
            "jeff": "October 2009",
            "evidence": [
                "2009-10-21 MVA accident report",
                "2009-10-21 Bloom crash reports",
                "2009-12-18 Norfolk GDC traffic case",
            ],
            "status": "affirmed_exact",
        },
        {
            "order": 9,
            "phase": "USS_Elrod_FFG55",
            "dates": {
                "orders": "2011-12-15",
                "early_ship": "2012-01-05",
                "detach": "2015-01-14",
            },
            "jeff": "Thought transferred 2011",
            "correction": "Orders Dec 2011; ship med Jan 2012 → report ~Jan 2012",
            "evidence": [
                "2011-12-15 USS ELROD FFG55 Orders",
                "2012-01-05 ELROD medication HM2 Murphy",
                "2015-01-14 NSIPS FFG55 Detaching",
            ],
            "status": "affirmed_report_Jan2012",
        },
        {
            "order": 10,
            "phase": "NCDOC_last",
            "dates": {
                "checkin": "2015-02-12",
                "eval": "2015-08-10",
                "separation_pack": "2018-03-02",
            },
            "evidence": [
                "2015-02-12 NCDOC Check-In sheets",
                "2015-08-10 Eval NCDOC",
                "2018-03-02 Separation Orders",
            ],
            "status": "affirmed",
        },
    ],
    "corrections_vs_jeff_memory": [
        "Enterprise report closer to Aug 2003 after A-school than June/July",
        "Elrod orders Dec 2011 / report ~Jan 2012 not mid-2011",
        "Accident exact day 2009-10-21 (month correct)",
    ],
    "still_open": [
        "SARP exact dates",
        "Exact RTC graduation day",
        "Exact Enterprise report-aboard page-13 date",
        "Rate/NEC progression detail",
    ],
}

orgs = d.setdefault("orgs", [])
if not any(str(o.get("canonical", "")).upper() == "SARP" for o in orgs):
    orgs.append(
        {
            "canonical": "SARP",
            "names": ["SARP", "Substance Abuse Rehabilitation Program"],
            "domain": "Navy-Service",
            "notes": "Jeff: Great Lakes 2003 after drinking problem; between A-school and Enterprise",
            "confidence": "confirmed_program",
            "updated": ts,
        }
    )

d["updated"] = ts
p.write_text(json.dumps(d, indent=2), encoding="utf-8")

Path(r"D:\PhronesisVault\Research\Silo-Entities\Navy-Career-Arc.md").write_text(
    f"""# Navy career arc — Jeffrey Jay Bloom (dated)

_Updated {ts}_

## Timeline (detective × Jeff)

| When | What | Status |
|------|------|--------|
| 2003-02-03…12 | MEPS / enlistment | Affirmed |
| **2003-02-13** | **RTC Great Lakes** gain entry (~8 wk) | Affirmed |
| **2003-08-05** | **IT A-School** graduate (A-202-0014) Great Lakes | Affirmed |
| ~2003 | **SARP** Great Lakes | Jeff memory; doc date TBD |
| **2003-07-30** orders · **~Aug 2003+** | **USS Enterprise CVN-65** until early 2008 | Affirmed (start corrected) |
| **2008-02-26 → 2008-07-16** | **OTC Newport STA-21** (BOOST/NSI) | Affirmed |
| **2008-07-22+** | **HRNROTC @ ODU** EET | Affirmed |
| **2009-10-21** | **MVA → TBI** | Affirmed exact |
| **2011-12-15** orders · **~2012-01** | **USS Elrod FFG-55** until **2015-01-14** detach | Affirmed |
| **2015-02-12 → ~2018-03** | **NCDOC** last command | Affirmed |

## Corrections
1. Enterprise report **after A-school Aug 2003**, not June report.  
2. Elrod **orders Dec 2011**, **report ~Jan 2012**.  
3. Accident **2009-10-21**.

## Open
SARP dated packet · RTC grad day · page-13 Enterprise report · rate timeline
""",
    encoding="utf-8",
)
print("ok")
