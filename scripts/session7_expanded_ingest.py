#!/usr/bin/env python3
"""
Session 7: Expanded Navy slice + Medical/Comms samples
Emphasizes maximum flexibility for the silo:
- Multi-domain tagging (lists)
- Extensible schema (easy to add fields/domains)
- Modular design (uses dt_tagging_helper)
- Placeholders for knowledge-graph, versioning, future twins
"""

import json
import os
from pathlib import Path
from datetime import datetime
import sys

sys.path.insert(0, str(Path(__file__).parent))
from dt_tagging_helper import enhance_with_dt_tags

DATA_DIR = Path("d:/HermesData/data/session7")
MANIFEST_DIR = Path("d:/HermesData/manifests")
MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

def simple_classify(path: Path) -> dict:
    name = path.name
    size = path.stat().st_size if path.exists() else 0
    suffix = path.suffix.lower()

    category = "PERSONAL / SILO-POPULATION + DT-Training"
    footprint_category = "General"

    if suffix == ".txt" and "chat" in name.lower():
        footprint_category = "Communications"
    elif "naval" in name.lower() or "navy" in name.lower() or "norfolk" in name.lower():
        footprint_category = "Military_Service"
    elif "dd" in name.lower() or "va " in name.lower() or "endocrinology" in name.lower() or "acth" in name.lower():
        footprint_category = "Medical"

    return {
        "path": str(path),
        "filename": name,
        "size_bytes": size,
        "file_type": suffix,
        "category": category,
        "footprint_category": footprint_category,
        "is_export_stub": False,
        "entity_links": [],
        "timestamp": datetime.now().isoformat(),
    }

def add_flexibility_fields(res: dict) -> dict:
    """Add future-proof extensible fields."""
    res["knowledge_graph_relations"] = []          # For future entity linking / relations
    res["version"] = "1.0"
    res["extensible_tags"] = []                    # Free-form for new projects/tasks
    res["cross_twin_potential"] = True             # Most data can serve multiple twins
    res["added_in_session"] = 7
    return res

def main():
    files = sorted(list(DATA_DIR.glob("*.*")))
    if not files:
        print("No files found.")
        return

    results = []
    for f in files:
        base = simple_classify(f)
        enhanced = enhance_with_dt_tags(base)
        enhanced = add_flexibility_fields(enhanced)
        results.append(enhanced)

        print(f"Processed: {f.name}")
        print(f"  Relevance: {enhanced['dt_training_relevance']}")
        print(f"  Domains: {enhanced['twin_domains']}")
        print(f"  Privacy: {enhanced['privacy_tier']}")
        print(f"  Sensitivity: {enhanced['sensitivity_tags']}")
        print(f"  Cross-twin potential: {enhanced['cross_twin_potential']}")
        print()

    manifest = {
        "session": 7,
        "timestamp": datetime.now().isoformat(),
        "source": "old Google Drive export (archived) + expanded slice",
        "working_directory": "d:/HermesData",
        "total_files": len(results),
        "files": results,
        "flexibility_notes": {
            "design": "Silo is the versatile core. Most data tagged for multi-twin use.",
            "multi_domain": "twin_domains is a list — supports overlapping twins.",
            "extensible": "Fields like extensible_tags, knowledge_graph_relations, version ready for growth.",
            "modular": "Uses dt_tagging_helper + simple_classify — easy to swap/enhance.",
            "future": "New domains, projects, or twins can be added without schema breakage."
        },
        "note": "All items approved as high-relevance from Session 6 carried forward. New items auto-suggested."
    }

    out_path = MANIFEST_DIR / "session7_expanded_navy_medical_manifest.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\n=== Session 7 Manifest written to {out_path} ===")
    print(f"Total files processed: {len(results)}")

if __name__ == "__main__":
    main()
