#!/usr/bin/env python3
import json
import re
import subprocess
import sys
from pathlib import Path

# purge junk people/orgs short tokens
p = Path(r"D:\HermesData\config\entity_context.json")
d = json.loads(p.read_text(encoding="utf-8"))
junk = {"notes", "note", "file", "copy", "doc", "the", "and", "for"}


def clean(rows):
    out = []
    for row in rows:
        names = [
            n
            for n in (row.get("names") or [])
            if n.lower() not in junk and len(n.strip()) >= 3
        ]
        if not names:
            continue
        if row.get("role") == "doctor" and set(x.lower() for x in names) <= junk:
            continue
        row = dict(row)
        row["names"] = names
        out.append(row)
    return out


d["people"] = clean(d.get("people") or [])
d["orgs"] = clean(d.get("orgs") or [])
if not any("laura" in " ".join(r.get("names") or []).lower() for r in d["people"]):
    d["people"].append(
        {
            "names": ["laura"],
            "role": "childhood_friend",
            "domain": "Core-Personal/Family",
            "notes": "Childhood friend. R5",
            "source": "jeff_interview_r5",
        }
    )
p.write_text(json.dumps(d, indent=2), encoding="utf-8")
print("cleaned people", len(d["people"]), "orgs", len(d["orgs"]))

new_fn = '''
def _entity_domain(blob: str) -> str | None:
    """Deterministic people/org to domain. Longest match wins."""
    try:
        data = json.loads(_ENTITY.read_text(encoding="utf-8"))
    except Exception:
        return None
    low = blob.lower()
    best = None  # (len, domain)
    for bucket in ("people", "orgs"):
        for row in data.get(bucket) or []:
            dom = row.get("domain")
            if not dom:
                continue
            for n in row.get("names") or []:
                key = (n or "").lower().strip()
                if len(key) < 3:
                    continue
                if key in {"notes", "note", "file", "copy", "doc", "the", "and", "for"}:
                    continue
                if len(key) <= 4:
                    if not re.search(
                        r"(?i)(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", low
                    ):
                        continue
                elif key not in low:
                    continue
                if best is None or len(key) > best[0]:
                    best = (len(key), dom)
    return best[1] if best else None
'''

dr = Path(r"D:\HermesData\scripts\domain_route.py")
t = dr.read_text(encoding="utf-8")
start = t.find("def _entity_domain")
end = t.find("def domain_for")
if start < 0 or end < 0:
    print("FAIL find functions")
    sys.exit(1)
t = t[:start] + new_fn.strip() + "\n\n\n" + t[end:]
dr.write_text(t, encoding="utf-8")
r = subprocess.run([sys.executable, "-m", "py_compile", str(dr)], capture_output=True, text=True)
print("compile", r.returncode, r.stderr)

sys.path.insert(0, r"D:\HermesData\scripts")
import importlib
import domain_route

importlib.reload(domain_route)
for s in [
    "Laura notes.gdoc",
    "SKYnet-notes hosts.properties",
    "RingVideo_20190309.mp4",
    "home automation plan.gdoc",
    "Dr Richardson labs.pdf",
]:
    print(domain_route.domain_for(s), "|", s)
