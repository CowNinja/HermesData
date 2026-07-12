#!/usr/bin/env python3
"""Codify Navy commands, places, medical orgs, people connections."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
p = Path(r"D:/HermesData/config/entity_context.json")
d = json.loads(p.read_text(encoding="utf-8"))
people = d.setdefault("people", [])
orgs = d.setdefault("orgs", [])
places = d.setdefault("places", [])


def upsert(lst, canonical, **kw):
    for row in lst:
        if str(row.get("canonical") or "").lower() == canonical.lower():
            row.update({k: v for k, v in kw.items() if k != "names"})
            row["canonical"] = canonical
            row["confidence"] = "confirmed"
            row["updated"] = ts
            names = list(dict.fromkeys((row.get("names") or []) + kw.get("names", [canonical]) + [canonical]))
            row["names"] = names
            return
    row = {
        "canonical": canonical,
        "names": list(dict.fromkeys(kw.get("names") or [canonical])),
        "confidence": "confirmed",
        "updated": ts,
        **{k: v for k, v in kw.items() if k != "names"},
    }
    lst.append(row)


org_defs = [
    ("NCDOC", ["NCDOC", "Navy Cyber Defense Operations Command", "ncdoc.navy.mil"],
     "Navy command — Jeff photos/email; ITC Melvin Johnson boss", "Navy-Service"),
    ("N332", ["N332", "N32"], "Navy billet/code related to service", "Navy-Service"),
    ("NMCP", ["NMCP", "Naval Medical Center Portsmouth"],
     "Primary Navy medical center", "Medical-Records"),
    ("Hampton VAMC", ["Hampton VAMC", "VAMC Hampton", "Vet Center Hampton", "VAMC"],
     "VA medical — Kapoor PCM, meds, MRI, urology", "Medical-Records"),
    ("CNSVA", ["CNSVA", "Center for Neurorehabilitation Services"],
     "Dr OShanick neurorehab clinic", "Medical-Records"),
    ("USS Elrod FFG-55", ["USS Elrod", "Elrod", "FFG-55", "FFG55"],
     "Ship cruise/photo archive (very large path count)", "Navy-Service"),
    ("CNIC", ["CNIC"], "Commander Navy Installations Command", "Navy-Service"),
    ("TRICARE", ["TRICARE", "TOL", "TRICARE Online"], "Military health benefits", "Medical-Records"),
    ("GDIT", ["GDIT"], "Career contractor cluster", "Core-Personal/Career"),
    ("QTC", ["QTC"], "VA C&P exam contractor", "Medical-Records"),
    ("ODU", ["ODU", "Old Dominion University"], "Education EE", "Core-Personal/Education"),
    ("ECPI", ["ECPI"], "Education", "Core-Personal/Education"),
    ("FFSC", ["FFSC", "Fleet and Family Support"], "Navy family support", "Navy-Service"),
    ("NNSY", ["NNSY", "Norfolk Naval Shipyard"], "FFSC invite location", "Navy-Service"),
    ("RTC Great Lakes", ["RTC", "Great Lakes"], "Boot camp / training", "Navy-Service"),
]
for can, names, notes, domain in org_defs:
    upsert(orgs, can, names=names, notes=notes, domain=domain, type="org_command")

for can, names, notes in [
    ("Norfolk, VA", ["Norfolk"], "Navy/medical gravity"),
    ("Portsmouth, VA", ["Portsmouth"], "NMCP"),
    ("Hampton, VA", ["Hampton"], "VAMC"),
    ("Chesapeake, VA", ["Chesapeake"], "Crosswater / Great Bridge area"),
    ("Virginia Beach, VA", ["Virginia Beach", "Kempsville"], "KPC area"),
    ("Suffolk, VA", ["Suffolk"], "NRBC + Social Services"),
    ("Williamsburg, VA", ["Williamsburg"], "Dr Roberts endo"),
]:
    upsert(places, can, names=names, notes=notes, type="geo")

for can, names, domain, role, notes in [
    ("Dr Foster", ["Dr Foster"], "Medical-Records", "nmcp_provider", "NMCP invites 2017 w/ Means/Johnson"),
    ("Dr Cann", ["Dr Cann", "Dr CANN", "Helen Cann"], "Medical-Records", "nmcp_pcm", "NMCP PCM + voice recordings"),
    ("Helen Cann", ["Helen Cann", "HELEN CANN"], "Medical-Records", "nmcp_pcm_or_staff", "VCF + Dr CANN invites"),
    ("CTN1 Means", ["CTN1 Means"], "Navy-Service", "navy_colleague", "NMCP invite chain"),
    ("Dr Victoria DeFilippo", ["Dr Victoria DeFilippo", "Victoria DeFilippo"], "Medical-Records", "vamc_provider", "VAMC 2019 w/ Jan Bloom notes"),
    ("PA Latif Muiz", ["PA Latif Muiz", "Latif Muiz"], "Medical-Records", "vamc_urology_pa", "VAMC Urology 2019-02-05"),
    ("Alison M. O'Shanick", ["Alison M. O'Shanick"], "Medical-Records", "cnsva_staff", "CNSVA photo"),
    ("Amy Deady", ["Amy Deady"], "Medical-Records", "cnsva_staff", "CNSVA"),
    ("Brittany Henshaw", ["Brittany Henshaw"], "Medical-Records", "cnsva_staff", "CNSVA"),
    ("Haley Smith Ruzbarsky", ["Haley Smith Ruzbarsky"], "Medical-Records", "cnsva_staff", "CNSVA"),
    ("Kamille West", ["Kamille West"], "Medical-Records", "cnsva_staff", "CNSVA"),
    ("Azalia Queen", ["Azalia Queen"], "Navy-Service", "navy_photo_associate", "Navy photo with Jeff"),
    ("Gregory J. O'Shanick", ["Dr O'Shanick", "Gregory J. O'Shanick", "CNSVA Dr O'Shanick"],
     "Medical-Records", "neurorehabilitation_md", "CNSVA appointments 2017-2018"),
]:
    upsert(people, can, names=names, domain=domain, role=role, notes=notes)

d["life_graph_notes"] = {
    "updated": ts,
    "navy_spine": "RTC/training → USS Elrod FFG-55 → NCDOC (ITC Melvin Johnson boss) → care at NMCP/VAMC/CNSVA",
    "medical_spine": "NMCP (Cann, Foster) → CNSVA O'Shanick → Hampton VAMC (Kapoor, DeFilippo) → OT/PT Barefield/Stevenson",
    "church_spine": "KPC → GBEFC → Crosswater PCA (friend graph) → NRBC current; Rescue Church touchpoints",
    "family_spine": "Jeff · Jodi/Jenni · Jeremy Kamies BIL · Blaizen/Spencer · Sara Ballas · Gary/Jan",
}
d["updated"] = ts
p.write_text(json.dumps(d, indent=2), encoding="utf-8")

vault = Path(r"D:/PhronesisVault/Research/Silo-Entities/00-LIFE-GRAPH.md")
vault.parent.mkdir(parents=True, exist_ok=True)
vault.write_text(
    f"""# Life graph — people · places · commands

_Updated {ts}_

## Navy spine
```
RTC / training → USS Elrod (FFG-55) → NCDOC (cyber)
  boss: ITC Melvin Johnson
  medical: NMCP Portsmouth
```

## Medical spine
```
NMCP (Dr Cann, Dr Foster, CTN1 Means)
  → CNSVA (Dr Gregory O'Shanick + staff)
  → Hampton VAMC (Dr Kapoor, DeFilippo, urology)
  → community OT/PT (Barefield, Stevenson)
  → endo (Roberts, Richardson)
```

## Church spine (VA)
```
KPC → GBEFC → Crosswater (friend photos) → NRBC (current)
(+ Rescue Church)
```

## Places
Norfolk · Portsmouth · Hampton · Chesapeake · Virginia Beach · Suffolk · Williamsburg

## Storage
entity_context (people/orgs/places) · person_file_graph · dossiers · timelines · PKO cards
""",
    encoding="utf-8",
)
print(json.dumps({"orgs": len(orgs), "places": len(places), "people": len(people)}))
