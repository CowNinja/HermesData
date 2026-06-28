"""
Discovery Walker (Session 10+)
Lightweight, reusable file discovery + tagging for the Personal Data Silo.

Features:
- Walks local directories or path lists
- Experimental rclone remote support (rclone:remote:path)
- Applies dt_tagging_helper rules (Navy_Service_History + Navy_Related_Medical cross-link)
- Integrates content extraction
- Basic persistent dedup via hash index
- Produces standardized manifests WITH DATA SOURCE PROVENANCE
  (source_account, source_original_path, backup_timestamp, cross_account_notes + legacy)
- Auto-infers account from path (e.g. old_jeffrey_j_bloom) 
  for easy queries like 'show me everything from old jeffrey.j.bloom account'
- Auto records original path, local mtime as backup timestamp
- Cross-account notes support

Designed for sessions, cron, or Composer-orchestrated jobs.
Production-ready integration with multi-account ingestion orchestrator.
"""

from pathlib import Path
from datetime import datetime
import json
from typing import List, Dict, Optional
import sys
import hashlib
import subprocess

sys.path.insert(0, str(Path(__file__).parent))

from dt_tagging_helper import enhance_with_dt_tags
from base_ingest import classify_file
from content_extraction_helper import extract_text

DEDUPE_INDEX = Path("D:/HermesData/manifests/dedup_index.json")


def _load_dedup_index() -> dict:
    if DEDUPE_INDEX.exists():
        try:
            return json.loads(DEDUPE_INDEX.read_text(encoding="utf-8"))
        except:
            return {}
    return {}


def _save_dedup_index(index: dict):
    DEDUPE_INDEX.parent.mkdir(parents=True, exist_ok=True)
    DEDUPE_INDEX.write_text(json.dumps(index, indent=2), encoding="utf-8")


def _get_file_hash(path: Path, block_size=65536) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(block_size), b""):
            h.update(block)
    return h.hexdigest()[:16]


def _infer_account_from_path(p: str) -> str:
    """Auto-detect source account from path or source string for easy cross-account queries."""
    p_lower = p.lower()
    if any(x in p_lower for x in ["old_jeffrey", "jeffrey.j.bloom", "old_backup_gdrive", "memorycard_backups"]):
        return "old_jeffrey_j_bloom"
    if any(x in p_lower for x in ["warz", "burner", "warz_gdrive"]):
        return "warz_burner"
    if "current" in p_lower or "main_gdrive" in p_lower:
        return "current_account"
    return ""


def _get_backup_timestamp(p: Path) -> str:
    """Get mtime as backup timestamp if local file."""
    try:
        if p.exists() and not str(p).startswith("rclone://"):
            return datetime.fromtimestamp(p.stat().st_mtime).isoformat()
    except Exception:
        pass
    return ""


def discover_files(source: str | Path, max_files: Optional[int] = None, 
                   min_size: int = 500, exclude_exts: tuple = ('.gsheet', '.gdoc')) -> List[Path]:
    """Discover files from directory, list, or rclone:remote:path.
    Enhanced to support richer rclone metadata for provenance (ModTime etc)."""
    files = []
    src_str = str(source)

    if src_str.startswith("rclone:"):
        remote = src_str.replace("rclone:", "", 1)
        try:
            cmd = ["D:/HermesData/rclone_test/rclone.exe", "lsjson", remote, "--fast-list", "--max-depth", "5"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if result.returncode == 0:
                entries = json.loads(result.stdout)
                for e in entries:
                    if e.get("IsDir"): continue
                    size = e.get("Size", 0)
                    if size >= min_size:
                        # For now we record virtual path; real ingestion would rclone copy first
                        virtual = Path(f"rclone://{remote}/{e['Path']}")
                        files.append(virtual)
            else:
                print("[Walker] rclone error:", result.stderr[:300])
        except Exception as ex:
            print("[Walker] rclone discovery failed:", ex)
    elif Path(src_str).is_file() and Path(src_str).suffix == '.txt':
        with open(src_str, encoding='utf-8') as f:
            for line in f:
                p = Path(line.strip())
                if p.exists() and p.is_file():
                    files.append(p)
    else:
        pth = Path(src_str)
        for p in pth.rglob('*'):
            if p.is_file():
                try:
                    if p.stat().st_size >= min_size and p.suffix.lower() not in exclude_exts:
                        files.append(p)
                except:
                    pass
    if max_files:
        files = files[:max_files]
    return files


def process_discovery(files: List[Path], session: int, source_note: str = "", provenance: Optional[Dict] = None) -> List[Dict]:
    """Classify, tag, extract, and dedupe. Enhanced with content-based Navy cross-link boost.
    provenance: optional dict with source_account, source_original_path, backup_timestamp, cross_account_notes etc.
    These fields + legacy are injected into EVERY file entry for multi-account tracking.
    Navy_Related_Medical and other rules run cleanly before provenance attachment.
    """
    results = []
    dedup_index = _load_dedup_index()
    seen_this_run = set()
    provenance = provenance or {}
    navy_content_kws = ["va ", "veteran", "disability", "service connected", "dd2807", "dd2808", "shpe", "separation physical", "navy", "usn", "military", "injury", "retirement physical"]

    for f in files:
        try:
            # For rclone virtual paths we skip real stat/hash for now
            is_virtual = str(f).startswith("rclone://")
            file_hash = ""
            extracted = ""
            extracted_len = 0

            if not is_virtual and f.exists():
                file_hash = _get_file_hash(f)
                extracted = extract_text(f, max_chars=2000)
                extracted_len = len(extracted)

            # Dedup check
            dedup_status = "new"
            if file_hash and file_hash in dedup_index:
                dedup_status = f"duplicate_of_{dedup_index[file_hash]}"
            elif file_hash:
                dedup_index[file_hash] = str(f)
                seen_this_run.add(file_hash)

            base = classify_file(f) if not is_virtual else {"path": str(f), "filename": f.name, "size_bytes": 0, "footprint_category": "Medical"}

            # Pre-populate provenance into base so dt_tagging_helper sees/preserves it
            prov_for_base = {}
            if provenance.get("source_account"):
                prov_for_base["source_account"] = provenance["source_account"]
            if provenance.get("source_original_path") or provenance.get("source_drive_path"):
                prov_for_base["source_original_path"] = provenance.get("source_original_path") or provenance.get("source_drive_path", str(f))
            if provenance.get("backup_timestamp") or provenance.get("pulled_timestamp"):
                prov_for_base["backup_timestamp"] = provenance.get("backup_timestamp") or provenance.get("pulled_timestamp", "")
            if provenance.get("cross_account_notes"):
                prov_for_base["cross_account_notes"] = provenance["cross_account_notes"]
            if prov_for_base:
                base.update(prov_for_base)

            enhanced = enhance_with_dt_tags(base)

            # Content-based boost for Navy_Related_Medical (real extracted text) -- unchanged
            if extracted and ("Medical" in enhanced.get("twin_domains", []) or enhanced.get("footprint_category") == "Medical"):
                extracted_lower = extracted.lower()
                if any(kw in extracted_lower for kw in navy_content_kws):
                    if "Navy_Related_Medical" not in enhanced.get("twin_domains", []):
                        enhanced.setdefault("twin_domains", []).append("Navy_Related_Medical")
                    enhanced["cross_twin_potential"] = True
                    enhanced.setdefault("extensible_tags", []).append("content_boosted_navy_medical")
                    enhanced["dt_notes"] = enhanced.get("dt_notes", "") + " | Content-based Navy cross-link detected"

            enhanced["added_in_session"] = session
            enhanced["discovery_source"] = source_note
            enhanced["file_hash"] = file_hash
            enhanced["dedup_status"] = dedup_status
            enhanced["extracted_chars"] = extracted_len
            enhanced["extracted_text_sample"] = extracted[:600] if extracted else ""

            # === Provenance recording (auto + passed) into EVERY entry ===
            # source_account
            if not enhanced.get("source_account"):
                acc = provenance.get("source_account") or _infer_account_from_path(str(source_note)) or _infer_account_from_path(str(f))
                if acc:
                    enhanced["source_account"] = acc

            # original path in Drive or local mirror
            orig_path = provenance.get("source_original_path") or provenance.get("source_drive_path") or provenance.get("original_remote_path")
            if not enhanced.get("source_original_path"):
                if orig_path:
                    enhanced["source_original_path"] = orig_path
                else:
                    enhanced["source_original_path"] = str(f)

            # backup timestamp (auto from mtime or passed)
            if not enhanced.get("backup_timestamp"):
                bt = provenance.get("backup_timestamp") or provenance.get("pulled_timestamp") or ""
                if not bt and not is_virtual:
                    bt = _get_backup_timestamp(f)
                if bt:
                    enhanced["backup_timestamp"] = bt
                elif provenance.get("pulled_timestamp"):
                    enhanced["backup_timestamp"] = provenance["pulled_timestamp"]

            # cross-account notes
            if provenance.get("cross_account_notes") and not enhanced.get("cross_account_notes"):
                enhanced["cross_account_notes"] = provenance["cross_account_notes"]

            # Legacy support for older field names
            if provenance.get("source_drive_path") and not enhanced.get("source_drive_path"):
                enhanced["source_drive_path"] = provenance.get("source_drive_path")
            if provenance.get("pulled_timestamp") and not enhanced.get("pulled_timestamp"):
                enhanced["pulled_timestamp"] = provenance.get("pulled_timestamp")
            if provenance.get("remote_name") and not enhanced.get("remote_name"):
                enhanced["remote_name"] = provenance.get("remote_name")

            # Full provenance block for query convenience
            if provenance:
                enhanced["provenance"] = {
                    k: v for k, v in provenance.items()
                    if k in ("source_account", "source_original_path", "backup_timestamp", "cross_account_notes",
                             "source_drive_path", "pulled_timestamp", "remote_name", "original_remote_path")
                }
                # also merge auto
                if enhanced.get("source_account"):
                    enhanced["provenance"]["source_account"] = enhanced["source_account"]

            results.append(enhanced)
        except Exception as e:
            err_entry = {
                "path": str(f),
                "filename": getattr(f, "name", str(f)),
                "error": str(e),
                "dt_training_relevance": "low",
                "curator_review_status": "needs_discussion"
            }
            if provenance.get("source_account"):
                err_entry["source_account"] = provenance["source_account"]
            results.append(err_entry)

    _save_dedup_index(dedup_index)
    return results


def run_walker(source_path: str | Path, session: int, max_files: Optional[int] = None,
               output_manifest: Optional[Path] = None,
               provenance: Optional[Dict] = None) -> Dict:
    """Run full discovery + tagging + manifest.
    provenance dict (optional) will be injected into every file record + top-level.
    Supports auto-inference and per-file timestamp.
    """
    print(f"[Walker] Discovering from {source_path} (max={max_files})...")
    files = discover_files(source_path, max_files=max_files)
    print(f"[Walker] Found {len(files)} candidates.")

    prov = provenance or {}
    # Auto fill some if not provided
    if not prov.get("source_account"):
        auto_acc = _infer_account_from_path(str(source_path))
        if auto_acc:
            prov["source_account"] = auto_acc
    if not prov.get("source_original_path"):
        prov["source_original_path"] = str(source_path)
    if not prov.get("backup_timestamp"):
        # will be per-file mostly, but top level now
        prov["backup_timestamp"] = datetime.now().isoformat()

    results = process_discovery(files, session=session, source_note=str(source_path), provenance=prov)

    domains, cross, extracted_total, new_files, dups = {}, 0, 0, 0, 0
    for r in results:
        for d in r.get("twin_domains", []):
            domains[d] = domains.get(d, 0) + 1
        if "Navy_Related_Medical" in r.get("twin_domains", []):
            cross += 1
        extracted_total += r.get("extracted_chars", 0)
        if "new" in r.get("dedup_status", ""):
            new_files += 1
        elif "duplicate" in r.get("dedup_status", ""):
            dups += 1

    manifest_data = {
        "session": session,
        "timestamp": datetime.now().isoformat(),
        "total_files": len(results),
        "cross_links": cross,
        "new_files": new_files,
        "duplicates": dups,
        "total_extracted_chars": extracted_total,
        "domain_counts": domains,
        "files": results,
        # Top-level provenance for the batch (populated if provided or auto)
        "provenance": prov if prov else None,
        "source_account": prov.get("source_account"),
        "source_original_path": prov.get("source_original_path"),
        "backup_timestamp": prov.get("backup_timestamp"),
        "cross_account_notes": prov.get("cross_account_notes"),
        # legacy aliases
        "source_drive_path": prov.get("source_drive_path"),
        "pulled_timestamp": prov.get("pulled_timestamp"),
        "remote_name": prov.get("remote_name"),
    }
    if prov:
        manifest_data["ingest_provenance"] = prov

    if output_manifest:
        output_manifest.parent.mkdir(parents=True, exist_ok=True)
        with open(output_manifest, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2, ensure_ascii=False)
        print(f"[Walker] Manifest written: {output_manifest}")

    print(f"[Walker] Domains: {domains} | Cross-links: {cross} | New: {new_files} | Dups: {dups}")
    if prov.get("source_account"):
        print(f"[Walker] Provenance attached: account={prov.get('source_account')} path={prov.get('source_original_path') or prov.get('source_drive_path')}")
    return manifest_data


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Discovery Walker with multi-account provenance support")
    parser.add_argument("source", help="path | list.txt | rclone:remote:path")
    parser.add_argument("session", type=int, nargs="?", default=12)
    parser.add_argument("max_files", type=int, nargs="?", default=50)
    parser.add_argument("--source-account", help="Source Google account / remote alias for provenance (e.g. old_jeffrey_j_bloom)")
    parser.add_argument("--source-original-path", "--source-drive-path", dest="source_original_path", help="Original Drive path or local mirror root (e.g. MemoryCard_Backups/Google Drive/Medical)")
    parser.add_argument("--remote-name", help="rclone remote name (e.g. old_backup_gdrive)")
    parser.add_argument("--backup-timestamp", "--pulled-timestamp", dest="backup_timestamp", help="ISO timestamp of backup/pull (defaults to now per file)")
    parser.add_argument("--cross-account-notes", help="Notes for cross-account references/merges")
    parser.add_argument("--output", help="Explicit output manifest path")
    args = parser.parse_args()

    out = Path(args.output) if args.output else Path(f"D:/HermesData/manifests/session{args.session}_discovery_manifest.json")
    prov = None
    if any([args.source_account, args.source_original_path, args.backup_timestamp, args.cross_account_notes, args.remote_name]):
        prov = {
            "source_account": args.source_account or _infer_account_from_path(args.source),
            "source_original_path": args.source_original_path,
            "backup_timestamp": args.backup_timestamp or datetime.now().isoformat(),
            "cross_account_notes": args.cross_account_notes or "",
            "remote_name": args.remote_name,
        }
    run_walker(args.source, session=args.session, max_files=args.max_files, output_manifest=out, provenance=prov)
