#!/usr/bin/env python3
"""Multi-tag + primary domain helpers for twin-ready silo organization.

Primary domain = filesystem shelf (one place).
tags[] = facets for training/twin filters without endless folder nests.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

GUIDE = Path(r"D:\HermesData\config\domain_taxonomy_guidance.json")


def load_guide() -> dict:
    try:
        return json.loads(GUIDE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def suggest_tags(name: str, domain: str, path_hint: str = "") -> list[str]:
    blob = f"{name} {path_hint}".lower()
    tags: list[str] = []
    if re.search(r"ring|doorbell|camera|nvr|security cam", blob):
        tags += ["home_security", "home_automation", "twin_ok"]
    if re.search(r"hubitat|smartthings|home.?automation|skynet|home.?network|hubduino", blob):
        tags += ["home_automation", "home_network", "twin_high"]
    if re.search(r"journal|diary|log\b|notes\b|notebook", blob):
        tags += ["journal", "needs_parse", "multi_topic"]
    if re.search(r"sermon|church|gospel|bible", blob):
        tags += ["church_community"]
    if domain.endswith("Friends"):
        tags.append("friend")
    if domain.endswith("Family"):
        tags.append("family")
    if domain.startswith("Medical"):
        tags.append("twin_high")
    if domain.startswith("Navy"):
        tags.append("twin_high")
    # dedupe preserve order
    seen = set()
    out = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def explain_primary(domain: str) -> str:
    g = load_guide()
    return (g.get("domains") or {}).get(domain, "")


if __name__ == "__main__":
    import sys

    for a in sys.argv[1:]:
        from domain_route import domain_for

        d = domain_for(a)
        print(json.dumps({"name": a, "domain": d, "tags": suggest_tags(a, d)}, indent=2))
