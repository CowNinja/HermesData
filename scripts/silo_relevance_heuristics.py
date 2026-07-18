#!/usr/bin/env python3
"""Silo relevance heuristics — gold vs junk for land + process.

Codifies Jeff 2026-07-13/14 lessons:
  - Booksbloom = parents' business + family PC (TRAINING GOLD), not pure junk
  - Mom's books / Keepers / WSWTR / Who Should We Then Read = family twin gold
  - AppData / Carbonite / Firefox profiles = catalog-only noise
  - Light family noise OK; bulk OS/browser/cache not
  - Medical / Navy / me / family / business = high score (Med/Navy first process)
  - Entertainment media (DVD/mp4 rips, music libs) = INTEREST catalog only
    (titles denote interests; binary content is NOT twin training data)
  - Never boost bare "water" — phone autocorrect of WSWTR (Jeff 2026-07-14)

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
    "/program files (x86)",
    "/programdata/",
    "/program data/",
    "/windows/winsxs",
    "/windows/installer",
    "/twrp_backup/",
    "/twrp img",
    "/recovery/",
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
    # hardware/driver dumps — not twin training
    "/drivers/",
    "drivermax",
    "windows10_install",
    # empty/noise roots
    "/snap/",
    # MemoryCard phone OS dumps (overnight 2026-07-18 lesson)
    "/amdkmafd/",
    "/amdkmpfd/",
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

# Entertainment / interest media — catalog title/path/size only (Jeff 2026-07-14).
# Like music libraries: denotes interests, content itself is not training data.
# Exceptions: personal/family recordings, medical audio, Navy/business conference audio.
ENTERTAINMENT_MEDIA_SUFFIXES = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".vob",
    ".iso",  # also disk images; personal ISOs still catalog
    ".vmdk",
    ".vdi",
    ".vhd",
    ".vhdx",
    ".mp3",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".wma",
    ".aiff",
}

# Path roots that are pure entertainment catalogs (not family home video archives)
INTEREST_MEDIA_ROOT_MARKERS = (
    "/star_of_bethlehem",
    "/old_music",
    "/music rip",
    "/z_jenni_kids_music",
    "/old_music_library",
)

# Personal recording / training-audio exceptions (still land)
PERSONAL_AUDIO_GOLD_MARKERS = (
    "booksbloom",
    "nche",
    "conference",
    "mixdown",
    "interview",
    "journal",
    "voicemail",
    "call_",
    "cnsva",
    "vamc",
    "nmcp",
    "medical",
    "navy",
    "pha",
    "sf600",
    "eval",
    "fitrep",
    "bloom_jeffrey",
    "bloom_jan",
    "bloom_gary",
    "family",
    "spencer",
    "alex",
)

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
    "gary",
    "jan",
    "jenni",
    "ballas",
    # business + mom books (family training)
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
    "who should we then",
    "who should we then read",
    # Mom books brand: WSWTR only (Jeff 2026-07-14 — "water" was phone autocorrect of wswtr)
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


def is_entertainment_media(path: str | Path) -> bool:
    """True when binary media is interest-catalog only (not twin training content).

    Jeff 2026-07-14: STAR_OF_BETHLEHEM mp4/DVD-class, music libraries, commercial rips.
    Titles still denote interests → catalog path/size/name only.
    Personal/family/medical/Navy/business recordings still land.
    """
    low = norm(path)
    p = Path(path)
    suf = p.suffix.lower()
    if suf not in ENTERTAINMENT_MEDIA_SUFFIXES:
        return False
    # Personal / training audio-video exceptions
    if any(m in low for m in PERSONAL_AUDIO_GOLD_MARKERS):
        return False
    # Explicit interest-media roots always catalog
    if any(m in low for m in INTEREST_MEDIA_ROOT_MARKERS):
        return True
    # Commercial-ish video containers without personal markers → catalog
    if suf in {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".m4v", ".mpg", ".mpeg", ".vob"}:
        return True
    # Audio libs / disk images default catalog unless gold marker above
    if suf in {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".aiff", ".iso", ".vmdk", ".vdi", ".vhd", ".vhdx"}:
        return True
    return False


def is_catalog_only(path: str | Path) -> bool:
    """True = record path/size only, do not full-copy."""
    if is_junk_path(path):
        return True
    p = Path(path)
    if p.suffix.lower() in BINARY_SKIP:
        return True
    if is_entertainment_media(path):
        return True
    # legacy explicit set (subset of entertainment media)
    if p.suffix.lower() in {".iso", ".vmdk", ".vdi", ".vhd", ".vhdx", ".mp3", ".flac", ".m4a"}:
        # personal audio gold already excluded via is_entertainment_media
        if not any(m in norm(path) for m in PERSONAL_AUDIO_GOLD_MARKERS):
            return True
    return False


def gold_score(path: str | Path) -> int:
    """Higher = more useful for twin/RAG training. 0 = noise."""
    low = norm(path)
    name = Path(path).name.lower()
    suf = Path(path).suffix.lower()
    if is_junk_path(path):
        return 0
    if is_entertainment_media(path):
        return 5  # interest marker only
    s = 10  # base: personal silo land is not zero
    if suf in GOLD_SUFFIXES:
        s += 25
    if suf in {".pdf", ".docx", ".doc", ".txt", ".md"}:
        s += 20
    for k in GOLD_KEYS:
        if k in low or k in name:
            s += 15
    # Booksbloom family business + mom books (WSWTR / Keepers) — NOT bare "water"
    if "booksbloom" in low or "keepers" in low or "who should we then" in low or "wswtr" in low:
        if any(g in low for g in WEB_GOLD_SUBSTR) or "/documents/" in low or "/desktop/" in low:
            s += 30
        if "/users/" in low and "/documents/" in low:
            s += 25
        if any(
            t in low
            for t in (
                "who should we then",
                "keepers of the books",
                "keepersofthebooks",
                "wswtr",
            )
        ):
            s += 40  # mom-authored / family business titles = family twin gold
        if is_junk_path(path):
            return 0
    # MemoryCard family/me trees
    if "memorycard_backups" in low and any(
        k in low for k in ("bloom_jeffrey", "bloom_jan", "bloom_gary", "ballas_sara", "google drive")
    ):
        s += 35
    # Medical / Navy hard boost (process priority)
    if any(k in low for k in ("nmcp", "vamc", "navpers", "sf600", "medical", "navy", "cnsva", "boone")):
        s += 40
    if suf in BINARY_SKIP:
        s = min(s, 5)
    return s


def land_decision(path: str | Path) -> str:
    """Return: land | catalog | skip."""
    if is_junk_path(path):
        return "catalog"  # path metadata only when catalog pipeline runs
    if is_catalog_only(path) or is_entertainment_media(path):
        return "catalog"
    if gold_score(path) < 15 and Path(path).suffix.lower() in {".js", ".css", ".map", ".woff", ".woff2"}:
        return "skip"
    # empty / pure noise roots
    low = norm(path)
    if any(x in low for x in ("/zz-random/", "/ip-updater/", "/drivers/")) and Path(path).suffix.lower() in BINARY_SKIP:
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


# Temporal layer (Jeff 2026-07-14): historical graph gold != current facts
# Outdated insurance/medical cards = excellent training; may not be live-relevant.


def temporal_relevance(path: str | Path, text_sample: str = "") -> str:
    """Return current | historical | unknown.

    historical = training + graph provenance; do NOT treat as live truth.
    current = prefer for day-to-day answers when docs conflict.
    """
    import re

    low = norm(path) + " " + (text_sample or "")[:2000].lower()
    years: list[int] = []
    for m in re.finditer(r"(?:19|20)\d{2}", low):
        try:
            y = int(m.group(0))
            if 1990 <= y <= 2099:
                years.append(y)
        except Exception:
            pass
    cardish = any(
        k in low
        for k in (
            "enrollment card",
            "insurance card",
            "id card",
            "member id",
            "tricare dental",
            "insurance id",
            "benefits card",
        )
    )
    if cardish and years and max(years) <= 2022:
        return "historical"
    if cardish and any(k in low for k in ("expired", "old ", "prior", "cancelled", "former")):
        return "historical"
    if years and max(years) >= 2024:
        return "current"
    if any(k in low for k in ("2024", "2025", "2026", "current", "active", "latest", "updated")):
        return "current"
    if years and max(years) <= 2022:
        return "historical"
    return "unknown"


def twin_scopes(path: str | Path) -> list[str]:
    """Which twin/project corpora this file may feed (Jeff 2026-07-18).

    Broad land stays on; filtering is at *use* time via metadata, not at land.
    Scopes are additive — family context can be both jeff_context and mom_twin.
    """
    low = norm(path)
    scopes: list[str] = []
    # Jeff primary twin — medical/navy/me trees
    if any(
        k in low
        for k in (
            "medical",
            "navy",
            "nmcp",
            "vamc",
            "navpers",
            "sf600",
            "ahlta",
            "myhealthevet",
            "dd214",
            "dd280",
            "bloom_jeffrey",
            "/jeffrey",
            "jeff ",
            "cnsva",
            "boone",
        )
    ):
        scopes.append("jeff_twin")
    # Mom / BooksBloom business twin
    if any(
        k in low
        for k in (
            "booksbloom",
            "bloom_jan",
            "jan l. bloom",
            "jan bloom",
            "keepers of the books",
            "keepersofthebooks",
            "wswtr",
            "who should we then",
            "egan",  # family business PC user often mom-side work
        )
    ):
        scopes.append("mom_twin")
    # Dad / Gary
    if any(k in low for k in ("bloom_gary", "gary a. bloom", "gary bloom")):
        scopes.append("dad_context")
    # Family graph (training about Jeff's life, not always first-person Jeff)
    if any(
        k in low
        for k in (
            "/family/",
            "core-personal/family",
            "ballas_sara",
            "sara l. ballas",
            "spencer",
            "alex s. mcbride",
        )
    ):
        scopes.append("family_context")
    # Friends / social graph
    if any(k in low for k in ("/friends/", "core-personal/friends")):
        scopes.append("friends_context")
    # Career / professional residual
    if any(k in low for k in ("/career/", "meba", "sec501")):
        scopes.append("career_context")
    # Default: still silo-useful archive if nothing matched but not noise
    if not scopes and gold_tier(path) != "noise":
        scopes.append("life_archive")
    return scopes


def train_meta_flags(path: str | Path) -> dict:
    """Flags for .train.md / index: historical graph OK, not live truth.

    Jeff 2026-07-18: multi-twin silo — scopes let later projects select
    jeff_twin vs mom_twin vs family_context without re-landing.
    """
    t = temporal_relevance(path)
    tier = gold_tier(path)
    scopes = twin_scopes(path)
    return {
        "temporal": t,
        "gold_tier": tier,
        "twin_scopes": scopes,
        "twin_training_value": "high"
        if tier in ("twin_critical", "twin_useful")
        else "medium",
        "use_as_current_fact": t == "current",
        "use_as_historical_graph": True,
        # Primary subject hint for retrieval routing
        "primary_scope": scopes[0] if scopes else "life_archive",
        "note": (
            "Outdated insurance/medical cards = historical gold, not current advice"
            if t == "historical"
            else "Multi-scope OK: filter at train/retrieve time, not at land"
        ),
    }


def _year_hint(path: str | Path) -> int | None:
    import re
    years = []
    for m in re.finditer(r"(?:19|20)\d{2}", norm(path)):
        try:
            y = int(m.group(0))
            if 1990 <= y <= 2099:
                years.append(y)
        except Exception:
            pass
    return max(years) if years else None


def pick_most_current(paths: list) -> dict:
    """Among duplicate-ish docs (e.g. same insurance card, many dates), pick live vs historical.

    Jeff 2026-07-14: most current = relevance for use today; older = context + training only.
    """
    items = []
    for p in paths:
        y = _year_hint(p)
        items.append({"path": str(p), "year": y, "temporal": temporal_relevance(p)})
    dated = [i for i in items if i["year"] is not None]
    if dated:
        best = max(dated, key=lambda i: i["year"])
        current_path = best["path"]
    else:
        # fall back: prefer temporal==current else first
        cur = [i for i in items if i["temporal"] == "current"]
        current_path = cur[0]["path"] if cur else (items[0]["path"] if items else None)
    return {
        "live_use": current_path,
        "historical": [i["path"] for i in items if i["path"] != current_path],
        "rule": "most_current_for_today; older_for_graph_and_training",
    }
