#!/usr/bin/env python3
"""Broad domain routing from filename (+ optional path). Open taxonomy, lenient silo.

Friends ≠ Family. Home security/automation → Projects (not Family).
"""
from __future__ import annotations

import json
import re
from pathlib import Path as _Path

_ENTITY = _Path(r"D:\HermesData\config\entity_context.json")

# Order matters — first regex match wins (after entity longest-match)
RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"va\s*dmv|dmv\b.*driver|temporary driving permit", re.I),
        "Core-Personal/Finance",
    ),
    (
        re.compile(r"va\s+home\s+loan|va\s+loan\s+number|va\s+mortgage", re.I),
        "Core-Personal/Finance",
    ),
    # Medical before housing
    (
        re.compile(
            r"medical|dental|health|healthevet|myhealth|clinvar|genome|diagnosis|"
            r"lab\b|labs\b|blood|pharmacy|prescription|acth|endocrin|richardson|"
            r"\bva\s+(rating|clinic|hospital|medical|benefits)|myhealthevet|buddy statement|vital signs|invoice totals.*medical|clinic|"
            r"secure messaging|\bdr\.?\s+[A-Z]|adrenal|nmcp|open.?emr|scymed|mirtazapine|cetirizine|mg tab|"
            r"\bcnp\b|compensation and pension|\btol\b|tricare|\bqtc\b|shpe|hnfs|vamc|cnsva|sgli|sglv",
            re.I,
        ),
        "Medical-Records",
    ),
    # Navy
    (
        re.compile(
            r"navy|navadmin|navpers|psrs?|eval\b|fitrep|dd ?form|dd\-?214|"
            r"orders|cjtf|djibouti|hoa\b|seabee|usn\b|nrotc|pcs\b|leave and earnings|"
            r"n332|ncdoc|bhc sewell|\bles\b|\btsp\b|thrift savings|\bnex\b|navy exchange",
            re.I,
        ),
        "Navy-Service",
    ),
    # Home automation / security / network → Projects (Jeff 2026-07-11)
    (
        re.compile(
            r"ring\b|doorbell|ringvideo|hubitat|smartthings|home.?automation|"
            r"home.?network|skynet|hubduino|st_anything|st-anything|nvr\b|"
            r"security cam|ip camera|clickmate|warz|lewz|last empire|"
            r"landroid|worx\b|memu|memuplay|albion|miststanding|nomads of the mist|_farms|all_farms|cujo|getcujo",
            re.I,
        ),
        "Core-Personal/Projects",
    ),
    # Finance
    (
        re.compile(
            r"income|expense|tax|finance|cash|bank|receipt|gas of |\bgas\b|utility|utilities|"
            r"mortgage|insurance|invoice|payment|budget|irs\b|w-?2|1099|navy cash|"
            r"amazon|order history|shopping|\bpurchase\b|cox\b|lowe|paypal|transaction_download|hrsd|hrubs|abnb|imco|uimn",
            re.I,
        ),
        "Core-Personal/Finance",
    ),
    # Spiritual content (not people)
    (
        re.compile(
            r"sermon|bible|gospel|spiritual|corinthians|ministry|prayer|scripture",
            re.I,
        ),
        "Core-Personal/Spiritual",
    ),
    # Career
    (
        re.compile(
            r"resume|curriculum|career|job |interview|linkedin|position|vacancy|"
            r"systems manager|network support|security engineer|systems administrator|"
            r"cover letter|performance review|cnda|gdit|general dynamics",
            re.I,
        ),
        "Core-Personal/Career",
    ),
    # Family (blood/household life — NOT friends)
    (
        re.compile(
            r"family|letter from dad|wedding|kids|spouse|bloom family|"
            r"grandma|grandpa|gary bloom|\bcondo\b",
            re.I,
        ),
        "Core-Personal/Family",
    ),
    # Education
    (
        re.compile(
            r"school|transcript|course|education|degree|diploma|certification|training record|ecpi",
            re.I,
        ),
        "Core-Personal/Education",
    ),
    # Community / hobby / co-op (Jeff teaching FLL, GHW)
    (
        re.compile(
            r"first lego|lego league|\bfll\b|lego racer|ghw\b|homeschool warrior|gods homeschool",
            re.I,
        ),
        "Life-Archive",
    ),
    # Digital footprint
    (
        re.compile(
            r"affidavit|facebook_affidavit|gmail filters|browser history",
            re.I,
        ),
        "Digital-Footprint",
    ),
    # Housing street (not Dr title)
    (
        re.compile(
            r"\bstreet\b|\bave\b|\bavenue\b|\blane\b|lease|landlord|whimbrel|crosswater|"
            r"\b\d{1,5}\s+\w+\s+(dr|drive|rd|road|st|ln)\b",
            re.I,
        ),
        "Core-Personal/Family",
    ),
    # Digital footprint
    (
        re.compile(
            r"ifttt|myhosts|password|email address|e-mail address|google takeout|"
            r"backup codes|2fa|authenticator",
            re.I,
        ),
        "Digital-Footprint",
    ),
]


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
            # map friend role → Friends domain
            role = (row.get("role") or "").lower()
            if role in {
                "friend",
                "childhood_friend",
                "friend_navy",
                "church_friend",
                "community_friend",
            }:
                dom = "Core-Personal/Friends"
            for n in row.get("names") or []:
                key = (n or "").lower().strip()
                # Min length + stopwords: avoid father/jeff/david false hits
                if len(key) < 4:
                    continue
                if key in {
                    "notes", "note", "file", "copy", "doc", "the", "and", "for",
                    "father", "mother", "sister", "brother", "friend", "family",
                    "david", "sarah", "erin", "john", "mike", "admin", "user",
                    "gary", "jeff", "jan", "jodi",  # too short alone; use full names
                }:
                    continue
                # single token under 6 chars requires word boundary
                if " " not in key and len(key) < 6:
                    if not re.search(
                        r"(?i)(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", low
                    ):
                        continue
                elif key not in low:
                    # multi-word or long token: substring ok if long enough
                    if len(key) < 8 or key not in low:
                        if key not in low:
                            continue
                if best is None or len(key) > best[0]:
                    best = (len(key), dom)
    return best[1] if best else None


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
