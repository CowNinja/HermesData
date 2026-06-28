"""
Base Ingest Utilities (Session 7+)

Shared logic for classification + manifest generation.
Reduces duplication across session scripts.
Supports future scaling (dedup by hash, better provenance).
"""

from pathlib import Path
from datetime import datetime
from typing import List, Dict
import json

from dt_tagging_helper import enhance_with_dt_tags


def classify_file(path: Path, footprint_override: str = None) -> dict:
    """Lightweight classifier. Can be extended with real text extraction later."""
    name = path.name
    size = path.stat().st_size if path.exists() else 0
    suffix = path.suffix.lower()

    category = "PERSONAL / SILO-POPULATION + DT-Training"
    footprint = footprint_override or "General"

    # Basic heuristics (can be replaced by content classifier)
    lowered = name.lower()
    if "chat" in lowered or "whatsapp" in lowered:
        footprint = "Communications"
    elif any(k in lowered for k in ["navy", "military", "norfolk", "naval", "dd11", "dd28"]):
        footprint = "Navy_Service_History"
    elif any(k in lowered for k in ["medical", "va ", "endocrin", "acth", "dd2870"]):
        footprint = "Medical"

    return {
        "path": str(path),
        "filename": name,
        "size_bytes": size,
        "file_type": suffix,
        "category": category,
        "footprint_category": footprint,
        "is_export_stub": False,
        "entity_links": [],
        "timestamp": datetime.now().isoformat(),
    }


def process_files(files: List[Path], session: int, source_note: str = "") -> List[Dict]:
    """Process a list of files and return enhanced records."""
    results = []
    for f in files:
        try:
            base = classify_file(f)
            enhanced = enhance_with_dt_tags(base)
            enhanced["added_in_session"] = session
            results.append(enhanced)
        except Exception as e:
            # Resilient: log and continue
            results.append({
                "path": str(f),
                "filename": f.name,
                "error": str(e),
                "dt_training_relevance": "low",
                "curator_review_status": "needs_discussion",
                "dt_notes": f"Processing error: {e}"
            })
    return results


def write_manifest(results: List[Dict], session: int, working_dir: str, output_path: Path, extra_notes: dict = None):
    """Write a standardized manifest with flexibility metadata."""
    manifest = {
        "session": session,
        "timestamp": datetime.now().isoformat(),
        "working_directory": working_dir,
        "total_files": len(results),
        "files": results,
        "flexibility_notes": {
            "design": "Silo is the versatile core. Most data supports multiple twins.",
            "multi_domain": "twin_domains is a list.",
            "extensible": "extensible_tags, knowledge_graph_relations, version, pii_detected ready for growth.",
            "modular": "Uses base_ingest + dt_tagging_helper.",
        },
        "source_note": extra_notes.get("source", "") if extra_notes else "",
    }
    if extra_notes:
        manifest.update(extra_notes)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return output_path
