#!/usr/bin/env python3
"""Silo relevance heuristics — gold vs junk for land + process.

Codifies Jeff 2026-07-13 lessons:
  - Booksbloom = parents' business + family PC (TRAINING GOLD), not pure junk
  - AppData / Carbonite / Firefox profiles = catalog-only noise
  - Light family noise OK; bulk OS/browser/cache not
  - Medical / Navy / me / family / business = high score

Used by: g_to_k_safe_drain, focus_land, OCR scoring, scoreboard.
"""
from __future__ import annotations

from pathlib import Path

# --- Hard skip (never land full content) ---
JUNK_PATH_SUBSTR = (
    "/appdata/",
    "/application data/",
    "/local settings/",
    "carbonite restored",
    "/diagnostics/",
    "/temp/",
    "/tmp/",
    "/cache/",
    "/caches/",
    "/node_modules/",
    "/.git/",
    "/__pycache__/",
    "/windows/system32",
    "/program files",
    "$recycle.bin",
    "system volume information",
    "thumbs.db",
    "/inetcache/",
    "/packages/",
    "/microsoft/windows/",
    "old firefox data",
    "/firefox/",
    "/chrome/",
    "/edge/user data",
    "/code cache/",
    "/gpu cache/",
    "/service worker/",
    "/indexeddb/",
    "/local storage/",
    "/session storage/",
    "/shader cache/",
)

# Office/lock temps
TEMP_NAME_PREFIXES = ("~$", "~wrl", "thumbs")

JUNK_SUFFIXES = {
    ".tmp",
    ".crdownload",
    ".partial",
    ".jsonlz4",
    ".final",  # firefox session junk
    ".dmp",
    ".etl",
    ".log",  # bulk logs — catalog later if needed
    ".dll",
    ".exe",  # binaries — catalog-only unless in gold business installer exception
    ".sys",
    ".msi",
}

# Allow .exe/.dll only under explicit business tools? default skip binaries for land
BINARY_SKIP = {".dll", ".exe", ".sys", ".msi", ".so", ".dylib"}

# --- Gold signals (path/name) ---
GOLD_KEYS = (
    # me / family
    "bloom",
    "jeff",
    "jodi",
    "alex",
    "spencer",
    "family",
    "parent",
    # business
    "booksbloom",
    "books bloom",
    "heav",
    "homeschool",
    "exhibitor",
    "business",
    "invoice",
    "tax",
    "bookkeeping",
    "keeper",
    "keepersofthebooks",
    "keepers of the books",
    "wswtr",
    "wholesale",
    "retail",
    "customer",
    "order form",
    # medical
    "medical",
    "nmcp",
    "vamc",
    "tricare",
    "mri",
    "clinic",
    "sf600",
    "cortisol",
    "tbi",
    "quest",
    "labcorp",
    "myhealthevet",
    "bhip",
    "tms",
    # navy / career
    "navy",
    "navpers",
    "ncdoc",
    "elrod",
    "enterprise",
    "cvn",
    "orders",
    "eval",
    "dd214",
    "les",
    "sta-21",
    "boost",
    "fitrep",
    "eval",
    # personal records
    "passport",
    "birth",
    "marriage",
    "insurance",
    "deed",
    "will",
    "trust",
)

GOLD_SUFFIXES = {
    ".pdf",
    ".doc",
    ".docx",
    ".txt",
    ".md",
    ".rtf",
    ".csv",
    ".xlsx",
    ".xls",
    ".pptx",
    ".odt",
    ".epub",
    ".mobi",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".heic",
    ".eml",
    ".msg",
    ".pst",
    ".mbox",
}

# Website content gold vs plugin noise
WEB_GOLD_SUBSTR = ("/www.booksbloom.com/", "/content/", "/uploads/", "/images/")
WEB_JUNK_SUBSTR = ("/plugins/", "/jquery", "/node_modules/", "/wp-includes/")


def norm(path: str | Path) -> str:
    return str(path).lower().replace("\\", "/")


def is_junk_path(path: str | Path) -> bool:
    low = norm(path)
    name = Path(path).name.lower()
    if name == "desktop.ini" or name.startswith("~$") or name.startswith("~wrl"):
        return True
    if name.endswith(".tmp") or "_files/" in low:
        return True
    if any(j in low for j in JUNK_PATH_SUBSTR):
        return True
    # Booksbloom website plugins
    if "booksbloom" in low and any(j in low for j in WEB_JUNK_SUBSTR):
        return True
    return False


def is_catalog_only(path: str | Path) -> bool:
    """True = record path/size only, do not full-copy."""
    if is_junk_path(path):
        return True
    p = Path(path)
    if p.suffix.lower() in BINARY_SKIP:
        return True
    if p.suffix.lower() in {".iso", ".vmdk", ".vdi", ".vhd", ".vhdx", ".mp3", ".flac", ".m4a"}:
        return True
    return False


def gold_score(path: str | Path) -> int:
    """Higher = more useful for twin/RAG training. 0 = noise."""
    low = norm(path)
    name = Path(path).name.lower()
    suf = Path(path).suffix.lower()
    if is_junk_path(path):
        return 0
    s = 10  # base: personal silo land is not zero
    if suf in GOLD_SUFFIXES:
        s += 25
    if suf in {".pdf", ".docx", ".doc", ".txt", ".md"}:
        s += 20
    for k in GOLD_KEYS:
        if k in low or k in name:
            s += 15
    # Booksbloom family business weight
    if "booksbloom" in low:
        if any(g in low for g in WEB_GOLD_SUBSTR) or "/documents/" in low or "/desktop/" in low:
            s += 30
        if "/users/" in low and "/documents/" in low:
            s += 25
        if is_junk_path(path):
            return 0
    # Medical / Navy hard boost
    if any(k in low for k in ("nmcp", "vamc", "navpers", "sf600", "medical", "navy")):
        s += 40
    if suf in BINARY_SKIP:
        s = min(s, 5)
    return s


def land_decision(path: str | Path) -> str:
    """Return: land | catalog | skip."""
    if is_junk_path(path):
        return "catalog"  # path metadata only when catalog pipeline runs
    if is_catalog_only(path):
        return "catalog"
    if gold_score(path) < 15 and Path(path).suffix.lower() in {".js", ".css", ".map", ".woff", ".woff2"}:
        return "skip"
    return "land"


# Gold tiers (2026-07-13): twin_critical | twin_useful | archive_only | noise
IMAGING_OCR_DEMOTE = (
    "99_volbrain",
    "volbrain",
    "/dicom",
    ".dcm",
    "nii.gz",
    "nrrd",
    "segmentation",
    "mricloud",
    "braingps",
    "raw_export",
)


def is_private_nsfw(path: str | Path) -> bool:
    low = norm(path)
    return any(k in low for k in (
        "_private_nsfw", "dirty things to moan", "onlyfans", "/porn", "nsfw"
    ))


def gold_tier(path: str | Path) -> str:
    """Return twin_critical | twin_useful | archive_only | noise."""
    low = norm(path)
    if is_junk_path(path) or gold_score(path) <= 0:
        return "noise"
    if is_private_nsfw(path):
        return "archive_only"  # hold private; not twin gold
    if any(k in low for k in IMAGING_OCR_DEMOTE) and not any(
        k in low for k in ("note", "report", "sf600", "clinic", "progress")
    ):
        return "archive_only"
    if any(
        k in low
        for k in (
            "medical",
            "navy",
            "vamc",
            "nmcp",
            "sf600",
            "ahlta",
            "myhealthevet",
            "booksbloom",
            "family",
            "navpers",
            "dd214",
            "dd2807",
            "dd2808",
        )
    ):
        return "twin_critical"
    if gold_score(path) >= 25:
        return "twin_useful"
    return "archive_only"


def ocr_priority_boost(path: str | Path) -> int:
    """Extra OCR score points — text gold up, pure imaging down."""
    tier = gold_tier(path)
    g = gold_score(path)
    if tier == "noise":
        return -80
    if tier == "archive_only":
        return -40  # land/shelf OK; don't starve text queue
    if tier == "twin_critical":
        return 55 if g >= 60 else 40
    if g >= 50:
        return 30
    if g >= 30:
        return 15
    return 0
