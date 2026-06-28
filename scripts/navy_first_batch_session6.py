#!/usr/bin/env python3
"""
Session 6: First real Navy batch ingestion
Location: d:/HermesData
Uses dt_tagging_helper for DT + privacy tags.
"""

import json
import os
from pathlib import Path
from datetime import datetime
import sys

# Add local scripts to path so we can import the helper
sys.path.insert(0, str(Path(__file__).parent))

from dt_tagging_helper import enhance_with_dt_tags

NAVY_DIR = Path("d:/HermesData/data/navy")
MANIFEST_DIR = Path("d:/HermesData/manifests")
MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

def simple_classify(path: Path) -> dict:
    """Minimal classifier for this batch (filename + basic signals)."""
    name = path.name
    size = path.stat().st_size if path.exists() else 0

    # Basic signals
    category = "PERSONAL / SILO-POPULATION + DT-Training"
    footprint_category = "Military_Service"
    is_export_stub = False

    if "1099" in name or "NavyFCU" in name:
        footprint_category = "Military_Service"
    if "VA" in name or "DD2870" in name:
        footprint_category = "Medical"

    return {
        "path": str(path),
        "filename": name,
        "size_bytes": size,
        "category": category,
        "footprint_category": footprint_category,
        "is_export_stub": is_export_stub,
        "entity_links": [],
        "timestamp": datetime.now().isoformat(),
    }

def main():
    files = list(NAVY_DIR.glob("*.pdf")) + list(NAVY_DIR.glob("*.PDF"))
    if not files:
        print("No files found in", NAVY_DIR)
        return

    results = []
    for f in files:
        base = simple_classify(f)
        enhanced = enhance_with_dt_tags(base)
        results.append(enhanced)
        print(f"Processed: {f.name}")
        print(f"  dt_training_relevance: {enhanced['dt_training_relevance']}")
        print(f"  twin_domains: {enhanced['twin_domains']}")
        print(f"  privacy_tier: {enhanced['privacy_tier']}")
        print(f"  sensitivity_tags: {enhanced['sensitivity_tags']}")
        print()

    manifest = {
        "session": 6,
        "timestamp": datetime.now().isoformat(),
        "source": "old Google Drive export (archived)",
        "working_directory": "d:/HermesData",
        "total_files": len(results),
        "files": results,
        "note": "First real Navy batch. Tags are auto-suggested. Review and override as needed.",
    }

    out_path = MANIFEST_DIR / "navy_first_batch_manifest_session6.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\n=== Manifest written to {out_path} ===")
    print(f"Total files: {len(results)}")

if __name__ == "__main__":
    main()
