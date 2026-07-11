#!/usr/bin/env python3
"""Broad domain routing from filename (+ optional path). Open taxonomy, lenient silo."""
from __future__ import annotations

import re

import json
from pathlib import Path as _Path

_ENTITY = _Path(r"D:\HermesData\config\entity_context.json")


def _entity_domain(blob: str) -> str | None:
    """Deterministic people/org → domain (Jeff lexicon)."""
    try:
        data = json.loads(_ENTITY.read_text(encoding="utf-8"))
    except Exception:
        return None
    low = blob.lower()
    for person in data.get("people") or []:
        for n in person.get("names") or []:
            if n.lower() in low:
                return person.get("domain")
    for org in data.get("orgs") or []:
        for n in org.get("names") or []:
            if n.lower() in low:
                return org.get("domain")
    return None


# Order matters — first match wins
RULES: list[tuple[re.Pattern[str], str]] = [
    # Medical (before housing — avoid "Dr" → family)
    (
        re.compile(
            r"medical|dental|health|healthevet|myhealth|clinvar|genome|diagnosis|"
            r"lab\b|labs\b|blood|pharmacy|prescription|acth|endocrin|richardson|"
            r"va\b|buddy statement|vital signs|invoice totals.*medical|clinic|"
            r"secure messaging|\bdr\.?\s+[A-Z]",
            re.I,
        ),
        "Medical-Records",
    ),
    # Navy / service
    (
        re.compile(
            r"navy|navadmin|navpers|psrs?|eval\b|fitrep|dd ?form|dd\-?214|"
            r"orders|cjtf|djibouti|hoa\b|seabee|usn\b|nrotc|pcs\b|leave and earnings",
            re.I,
        ),
        "Navy-Service",
    ),
    # Finance
    (
        re.compile(
            r"income|expense|tax|finance|cash|bank|receipt|gas of |\bgas\b|utility|utilities|"
            r"mortgage|insurance|invoice|payment|budget|irs\b|w-?2|1099|navy cash|"
            r"amazon|order history|shopping|\bpurchase\b",
            re.I,
        ),
        "Core-Personal/Finance",
    ),
    # Spiritual
    (
        re.compile(
            r"sermon|bible|gospel|spiritual|church|corinthians|ministry|prayer|scripture",
            re.I,
        ),
        "Core-Personal/Spiritual",
    ),
    # Career
    (
        re.compile(
            r"resume|curriculum|career|job |interview|linkedin|position|vacancy|"
            r"systems manager|network support|security engineer|systems administrator|"
            r"cover letter|performance review",
            re.I,
        ),
        "Core-Personal/Career",
    ),
    # Family
    (
        re.compile(
            r"family|letter from dad|wedding|kids|spouse|mother|father|bloom family",
            re.I,
        ),
        "Core-Personal/Family",
    ),
    # Education
    (
        re.compile(
            r"school|transcript|course|education|degree|diploma|certification|training record",
            re.I,
        ),
        "Core-Personal/Education",
    ),
    # Housing / street addresses (not bare "Dr" title)
    (
        re.compile(
            r"\bstreet\b|\bave\b|\bavenue\b|\blane\b|lease|landlord|whimbrel|crosswater|"
            r"\b\d{1,5}\s+\w+\s+(dr|drive|rd|road|st|ln)\b",
            re.I,
        ),
        "Core-Personal/Family",
    ),
    # Digital footprint / tech life
    (
        re.compile(
            r"ifttt|myhosts|password|email address|e-mail address|google takeout|"
            r"backup codes|2fa|authenticator|\bscan\b|\bscans\b",
            re.I,
        ),
        "Digital-Footprint",
    ),
]


def domain_for(name: str, path_hint: str = "") -> str:
    blob = f"{name} {path_hint}"
    ent = _entity_domain(blob)
    if ent:
        return ent
    for pat, dom in RULES:
        if pat.search(blob):
            return dom
    return "Core-Personal/_Inbox"


if __name__ == "__main__":
    import sys

    for a in sys.argv[1:]:
        print(domain_for(a), a)
