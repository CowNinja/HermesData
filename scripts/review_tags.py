#!/usr/bin/env python3
"""
Simple Review / Override Tool for manifests (Session 7+)

Usage examples:
  python review_tags.py session7_expanded_navy_medical_manifest.json
  python review_tags.py ... --approve-all
  python review_tags.py ... --set-relevance 0 high

This is a stepping stone toward better review UX.
"""

import json
import sys
from pathlib import Path
from datetime import datetime


def load_manifest(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_manifest(manifest: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def main():
    if len(sys.argv) < 2:
        print("Usage: python review_tags.py <manifest.json> [--approve-all]")
        return

    manifest_path = Path(sys.argv[1])
    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        return

    manifest = load_manifest(manifest_path)
    files = manifest.get("files", [])

    if "--approve-all" in sys.argv:
        for item in files:
            if item.get("curator_review_status") == "auto_suggested":
                item["curator_review_status"] = "approved"
                item["dt_notes"] = "Batch approved in review session."
        manifest["last_reviewed"] = datetime.now().isoformat()
        save_manifest(manifest, manifest_path)
        print(f"All auto_suggested items marked approved. Saved to {manifest_path}")
        return

    # Interactive summary
    print(f"=== Review for {manifest_path.name} (Session {manifest.get('session')}) ===")
    print(f"Total files: {len(files)}")
    for i, item in enumerate(files[:10]):  # show first 10
        print(f"{i}: {item.get('filename')}")
        print(f"   Relevance: {item.get('dt_training_relevance')} | Domains: {item.get('twin_domains')}")
        print(f"   Status: {item.get('curator_review_status')} | Sensitivity: {item.get('sensitivity_tags')}")
    if len(files) > 10:
        print(f"... and {len(files)-10} more")

    print("\nFor now use --approve-all or edit the JSON directly.")
    print("Future versions will support interactive overrides and bulk commands.")


if __name__ == "__main__":
    main()
