#!/usr/bin/env python3
"""
Tightened Classifier for Digital Twin Ingestion
- Rich context: source_folder_path, parent_folders, sibling_files
- User exact 3 buckets + Hybrid overlay
- source_drive_defaults: paths containing MemoryCard_Backups/Google Drive → high-confidence PERSONAL unless explicit orphan/stub
- Entity keywords: bloom, spencer, booksbloom, jeff, cowni in name OR full_path
- Fixed indentation and syntax
- schema v2 manifest support
"""

import os
import hashlib
import argparse
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List

# Wire dt_tagging_helper (L3 overlay per Lightweight-Relevance-Evaluation-Framework)
try:
    sys.path.insert(0, os.path.dirname(__file__))
    from dt_tagging_helper import enhance_with_dt_tags
except Exception as e:
    print(f"WARNING: dt_tagging_helper not importable: {e}")
    def enhance_with_dt_tags(res): return res  # fallback

# Sovereign integration
try:
    from es_wrapper import search_structured
except ImportError:
    search_structured = None

# Optional Magika
MAGIKA_AVAILABLE = False
try:
    from magika import Magika
    _magika = Magika()
    MAGIKA_AVAILABLE = True
except Exception:
    MAGIKA_AVAILABLE = False


def get_file_type(path_str: str) -> str:
    if MAGIKA_AVAILABLE:
        try:
            result = _magika.identify_path(path_str)
            if hasattr(result, "output"):
                out = result.output
                return getattr(out, "label", getattr(out, "ct_label", str(result)))
            return str(result)
        except Exception:
            pass
    ext = os.path.splitext(path_str)[1].lower()
    return f"ext:{ext}" if ext else "unknown"


def get_partial_hash(path: str, max_bytes: int = 12288) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            h.update(f.read(max_bytes))
        return h.hexdigest()[:12]
    except Exception:
        return "hash-error"


def get_full_hash(path: str) -> str:
    """Full SHA-256 content hash for dedup, versioning, provenance."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(12288), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return "hash-error"


def get_rich_context(path_str: str, max_parent_levels: int = 3, max_siblings: int = 20) -> Dict:
    """Source folder path + surrounding files for context and linking."""
    p = Path(path_str)
    parents = []
    current = p.parent
    for _ in range(max_parent_levels):
        if current.name:
            parents.append(current.name)
            current = current.parent
        else:
            break
    parents = list(reversed(parents))

    siblings = []
    try:
        for s in list(p.parent.iterdir())[:max_siblings + 1]:
            if s != p:
                siblings.append({"name": s.name, "ext": s.suffix.lower() if s.is_file() else "dir", "is_dir": s.is_dir()})
    except Exception:
        pass

    return {
        "source_folder_path": str(p.parent),
        "parent_folders": parents,
        "sibling_files": siblings,
        "sibling_count": len(siblings)
    }


def get_file_stats(path_str: str) -> Dict:
    try:
        stat = os.stat(path_str)
        return {
            "size_bytes": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "ctime": datetime.fromtimestamp(stat.st_ctime).isoformat(),
        }
    except Exception:
        return {"size_bytes": 0, "mtime": None, "ctime": None}


def get_content_preview(path_str: str, max_bytes: int = 2048) -> str:
    try:
        ext = Path(path_str).suffix.lower()
        if ext in [".txt", ".md", ".csv", ".json", ".log", ".py", ".js"]:
            with open(path_str, "rb") as f:
                data = f.read(max_bytes)
            return data.decode("utf-8", errors="ignore")[:400]
    except Exception:
        pass
    return ""


def classify_file(path_str: str) -> Dict:
    p = Path(path_str)
    name = p.name.lower()
    ext = p.suffix.lower()
    full_path = str(p).lower()

    context = get_rich_context(path_str)
    stats = get_file_stats(path_str)
    preview = get_content_preview(path_str).lower()

    # Sensitive (conservative, filename-only)
    sensitive_kws = ["password", "secret", "credential", "api_key", "private_key", "auth_token", "ssn", "medical_record", "va_form", "navy_id"]
    is_sensitive = any(kw in name for kw in sensitive_kws)

    # High-signal boosters
    is_companion = any(x in name for x in ["kindroid", "replika", "companion"]) or "chat" in name
    is_knowledge = ext in [".md", ".txt"] and any(x in name for x in ["roadmap", "synthesis", "timeline", "personal", "journal", "ingestion", "inventory"])
    personal_folder_signals = any(pf.lower() in ["documents", "downloads", "desktop", "pictures", "videos", "music", "cowni", "personal"] for pf in context.get("parent_folders", []))
    has_personal_content = any(kw in preview for kw in ["jeff", "medical", "va ", "navy", "personal", "journal", "timeline"])

    # source_drive_defaults: Google Drive backups are PERSONAL by default (per Jeff)
    source_drive_google = "memorycard_backups\\google drive" in full_path or "memorycard_backups/google drive" in full_path

    # Entity keywords
    entity_kws = ["bloom", "spencer", "booksbloom", "jeff", "cowni"]
    is_entity = any(kw in name or kw in full_path for kw in entity_kws)

    # scan_personal_signal
    scan_personal_signal = any(kw in name or kw in full_path for kw in ["navy", "va ", "1099", "dfas", "tax", "irs", "veteran", "military", "va proof", "va form"]) or personal_folder_signals or has_personal_content or is_entity

    size = stats.get("size_bytes", 0)

    # Stubs / low value (Google Drive specific)
    is_export_stub = (size < 1000 and any(x in name for x in [".gsheet", ".gdoc"])) or any(x in name for x in [".gsheet", ".gdoc", "ilovepdf", "export", "stub"]) or "google doc" in name or "google sheet" in name

    protected_signals = any(x in full_path for x in ["windows", "program files", "programdata", "system32", "$recycle.bin"]) or "system" in name

    explicit_orphan = any(x in name for x in ["old", "backup", "temp", "cache", "installer", "setup", ".bak", "archive", "ilovepdf"])
    is_orphan_like = (
        not is_sensitive and not is_companion and not is_knowledge and
        not personal_folder_signals and not has_personal_content and
        size < 500 * 1024 * 1024 and not (source_drive_google or is_entity)
    ) and explicit_orphan

    is_personal = is_sensitive or is_companion or is_knowledge or personal_folder_signals or has_personal_content or scan_personal_signal or source_drive_google or is_entity
    # Genealogy / archive structure signals (first principles: the taxonomy of tools/data types is itself high-signal)
    is_genealogy = any(kw in full_path for kw in ['ancestry', 'gedcom', 'gramps', 'genealogy', 'dna genome', 'family tree'])
    if is_genealogy and not is_export_stub:
        cat = 'PERSONAL / SILO-POPULATION (genealogy/family archive structure + DT-Training)'


    is_hybrid = (is_orphan_like or protected_signals) and (is_personal or has_personal_content)

    if protected_signals and not is_hybrid and not is_export_stub:
        cat = "PROTECTED: System / OS in-use. DO NOT MOVE."
    elif is_hybrid:
        cat = "HYBRID: Personal signal in non-personal location. Flag for model review + manual gate."
    elif is_genealogy and not is_export_stub and not is_orphan_like:
        cat = "PERSONAL / SILO-POPULATION (genealogy/family archive structure + DT-Training)"
    elif is_personal and not is_export_stub and not is_orphan_like:
        cat = "PERSONAL / SILO-POPULATION + DT-Training (full archive in K: once metadata extracted)"
    elif is_orphan_like or is_export_stub:
        cat = "ORPHAN / RELIC: Distill/ingest then remove from source drive to free space."
    else:
        cat = "Needs-Review / Possible Orphan or Low-Value"

    distill_rec = ""
    if "ORPHAN" in cat or "Needs-Review" in cat:
        distill_rec = "Distill actual content if possible (e.g. re-export from source app, extract from subdirs, or manual review). Structure/taxonomy may still be valuable."
    result = {
        "path": path_str,
        "name": p.name,
        "ext": ext,
        "size": size,
        "type": get_file_type(path_str),
        "content_hash": get_full_hash(path_str),
        "partial_hash": get_partial_hash(path_str),
        "category": cat,
        "distill_recommendation": distill_rec,
        "is_sensitive": str(is_sensitive),
        "timestamp": datetime.now().isoformat(),
        "source_folder_path": context.get("source_folder_path"),
        "parent_folders": context.get("parent_folders", []),
        "sibling_files_sample": [s["name"] for s in context.get("sibling_files", [])[:5]],
        "sibling_count": context.get("sibling_count", 0),
        "mtime": stats.get("mtime"),
        "content_preview_snippet": preview[:300] if preview else "",
        "personal_folder_signal": personal_folder_signals,
        "content_personal_signal": has_personal_content,
        "hybrid_flag": is_hybrid,
        "source_drive_google": source_drive_google,
        "is_entity": is_entity,
        "is_export_stub": is_export_stub,
    }

    # Additional footprint linking
    years = re.findall(r"(19[8-9][0-9]|20[0-2][0-9])", path_str + " " + name)
    entities = []
    if any(kw in (path_str + name).lower() for kw in ["va", "veteran"]): entities.append("VA")
    if any(kw in (path_str + name).lower() for kw in ["navy", "usn", "military"]): entities.append("Navy")
    if any(kw in (path_str + name).lower() for kw in ["jeff", "cow", "bloom", "spencer", "booksbloom", "cowni", "family"]): entities.append("Personal_Family")
    if any(kw in name for kw in ["kindroid", "replika", "chat"]): entities.append("AI_Companion")

    footprint_cat = "General"
    if "medical" in name or "va" in name or "health" in name: footprint_cat = "Medical"
    elif "navy" in name or "military" in name: footprint_cat = "Military_Service"
    elif "journal" in name or "timeline" in name or "personal" in name: footprint_cat = "Personal_Narrative"
    elif "photo" in name or "img" in name or ext in [".jpg", ".png", ".heic"]: footprint_cat = "Media_Photo"
    elif "video" in name or ext in [".mp4", ".mov"]: footprint_cat = "Media_Video"
    elif "audio" in name or ext in [".mp3", ".wav", ".m4a"]: footprint_cat = "Media_Audio"
    elif "chat" in name or "companion" in name or "kindroid" in name: footprint_cat = "Communications_Companion"
    elif "project" in name or "code" in name: footprint_cat = "Projects_Code"
    elif "backup" in name or "old" in name: footprint_cat = "Archive_Relic"

    result["entity_links"] = entities
    result["footprint_category"] = footprint_cat
    result["temporal_anchors"] = {"years": years[:5]}

    # Wire L3 DT tagging + relevance stub + skip_reason (per Composer relay 2026-06-26)
    try:
        enhanced = enhance_with_dt_tags(result)
    except Exception as e:
        print(f"enhance_with_dt_tags error: {e}")
        enhanced = result
    
    dt_rel = enhanced.get('dt_training_relevance', 'medium')
    if dt_rel == 'high':
        enhanced['relevance_score'] = 0.85
    elif dt_rel == 'medium':
        enhanced['relevance_score'] = 0.55
    else:
        enhanced['relevance_score'] = 0.25
    
    cat = enhanced.get('category', '')
    if 'PROTECTED' in cat:
        enhanced['skip_reason'] = 'PROTECTED: System / OS in-use. DO NOT MOVE.'
    elif 'ORPHAN' in cat or 'Needs-Review' in cat or 'RELIC' in cat:
        enhanced['skip_reason'] = 'ORPHAN / RELIC / low signal; distill or review recommended.'
    else:
        enhanced['skip_reason'] = None
    
    return enhanced


def scan_dir(dir_path: str, max_files: int = 50) -> List[Dict]:
    results = []
    pdir = Path(dir_path)
    processed = 0
    for root, dirs, files in os.walk(pdir):
        for f in files:
            if processed >= max_files:
                break
            fp = os.path.join(root, f)
            try:
                results.append(classify_file(fp))
            except Exception as e:
                results.append({"path": fp, "error": str(e)})
            processed += 1
        if processed >= max_files:
            break
    return results


def scan_with_es_and_classify(query: str = r'path:"D:\\PhronesisVault\\Digital-Twin"', limit: int = 20) -> List[Dict]:
    if search_structured is None:
        print("es_wrapper not available - falling back to Python scan")
        return scan_dir(r"D:\\PhronesisVault\\Digital-Twin", max_files=limit)
    raw = search_structured(query, limit=limit)
    classified = []
    for item in raw:
        if isinstance(item, dict) and "path" in item and item.get("type") == "file":
            p = item["path"]
            if os.path.exists(p):
                try:
                    classified.append(classify_file(p))
                except Exception as e:
                    classified.append({"path": p, "error": str(e)})
    return classified


def generate_manifest(classified_results, output_path=None):
    from datetime import datetime
    manifest = {
        "timestamp": datetime.now().isoformat(),
        "total_files": len(classified_results),
        "classifications_summary": {},
        "provenance_note": "classify_ingest + rich context + source_drive_defaults (Google Drive = PERSONAL default) + entity keywords + 3-bucket + footprint + full content_hash + schema v2",
        "schema_version": "v2",
        "batch_id": datetime.now().strftime("batch_%Y%m%d_%H%M%S"),
        "approval_status": "pending",
        "errors": [],
        "items": classified_results
    }
    errors = [r for r in classified_results if "error" in r]
    manifest["errors"] = errors
    manifest["error_count"] = len(errors)
    for r in classified_results:
        if "error" not in r:
            cat = r.get("category", "unknown")
            manifest["classifications_summary"][cat] = manifest["classifications_summary"].get(cat, 0) + 1
    if output_path:
        import json
        try:
            with open(output_path, "w", encoding="utf-8") as mf:
                json.dump(manifest, mf, indent=2)
            print("Manifest saved:", output_path)
        except Exception as e:
            print("Manifest error:", e)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan", help="Python scan a directory")
    parser.add_argument("--es-scan", help="Use es_wrapper query")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--manifest", help="Path to write manifest json")
    args = parser.parse_args()

    if args.scan:
        res = scan_dir(args.scan, max_files=args.limit)
    elif args.es_scan:
        res = scan_with_es_and_classify(args.es_scan, limit=args.limit)
    else:
        res = scan_dir(r"D:\\PhronesisVault\\Digital-Twin", max_files=10)

    for r in res[:5]:
        print(r.get("path"), "->", r.get("category"), " | folder:", r.get("source_folder_path"), " | footprint:", r.get("footprint_category"))

    if args.manifest:
        generate_manifest(res, args.manifest)
    else:
        print(f"\nTotal classified in this run: {len(res)}")

# === Sovereign File Tracking / Dedup Ledger (for complete drive coverage + no re-work) ===
def load_known_hashes(manifest_dir="Digital-Twin/manifests"):
    """Build set of already-processed content hashes from all manifests + master ledger.
    This is the core 'database' that tracks every discovered file so we never repeat work."""
    import glob, json, os
    known = set()
    ledger = {}
    paths = glob.glob(f"{manifest_dir}/*.json") + [f"{manifest_dir}/master_file_ledger.json"]
    for mf_path in paths:
        if not os.path.exists(mf_path): continue
        try:
            with open(mf_path, encoding="utf-8") as f:
                m = json.load(f)
            if isinstance(m, dict) and "decision" in next(iter(m.values()), {}):  # rough check for ledger
                ledger.update(m)
                for h in m.keys(): known.add(h)
            else:
                for item in m.get("items", []):
                    if "error" in item: continue
                    h = item.get("content_hash")
                    if not h: continue
                    known.add(h)
                    cat = item.get("category", "unknown")
                    decision = "INGEST" if "PERSONAL" in cat or "DT-Training" in cat else ("SKIP_ORPHAN" if "ORPHAN" in cat or "Needs-Review" in cat else "PROTECTED" if "PROTECTED" in cat else "HYBRID_REVIEW")
                    ledger[h] = {
                        "decision": decision,
                        "category": cat,
                        "batch": m.get("batch_id", "unknown"),
                        "last_seen": item.get("timestamp") or m.get("timestamp"),
                        "source_path": item.get("path")
                    }
        except Exception: pass
    return known, ledger

def update_master_ledger(classified_results, ledger_path="Digital-Twin/manifests/master_file_ledger.json"):
    import json, os
    known, ledger = load_known_hashes()
    for r in classified_results:
        if "error" in r or not r.get("content_hash"): continue
        h = r["content_hash"]
        cat = r.get("category", "")
        decision = "INGEST" if "PERSONAL" in cat or "DT-Training" in cat else ("SKIP_ORPHAN" if "ORPHAN" in cat or "Needs-Review" in cat else "PROTECTED" if "PROTECTED" in cat else "HYBRID_REVIEW")
        ledger[h] = {
            "decision": decision,
            "category": cat,
            "dt_training_score": r.get("dt_training_score", 0),
            "footprint": r.get("footprint_category"),
            "entities": r.get("entity_links"),
            "last_seen": r.get("timestamp"),
            "source_path": r.get("path")
        }
    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2)
    return ledger_path, len(ledger)

def get_file_decision(path_str):
    """Returns the tracked decision for this exact file (by full hash)."""
    h = get_full_hash(path_str)
    known, ledger = load_known_hashes()
    return ledger.get(h, {"decision": "NEW_UNSEEN"})

# === Enhancement for hidden personal data in protected/system areas (2026-06-26) ===
# Addresses user concern: personal data for DT training can hide in "protected" files.
# Steelman/Strawman analysis in Digital-Twin/Steelman-Strawman-Protected-Areas-2026-06-26.md

def is_potential_personal_system_area(full_path: str) -> bool:
    """Returns True for user-system areas that frequently contain personal training data
    even if they look 'protected' (AppData, user Microsoft caches, logs with activity, etc.).
    These should trigger full personal signal evaluation and lean toward HYBRID/PERSONAL.
    """
    p = full_path.lower().replace("\\\\", "/")
    user_system_personal = [
        'appdata/local', 'appdata/roaming', 'appdata/local/microsoft',
        'users/' + os.environ.get('USERNAME', 'cowni').lower(),
        'windows/logs', 'programdata/microsoft',
    ]
    return any(x in p for x in user_system_personal)

# Note: In main classify_file, personal checks already run before final bucket.
# Recommendation from analysis: always force personal signal evaluation for the above areas.
# Current code largely does this via personal_folder_signals and has_personal_content.
# Future: call this function to adjust protected_signals weight.
