#!/usr/bin/env python3
"""
Multi-Account Ingestion Orchestrator for the Personal Data Silo.

Robust production script for pulling from multiple Google Drive remotes
(old_backup_gdrive, warz_gdrive, primary, etc.) using different accounts.

Features:
- Config-driven (inline defaults + optional JSON config override)
- Per-account, per-path pulls with rclone copy
- Full provenance: source_account, source_drive_path (original), pulled_timestamp, remote_name
- Dry-run support (prints commands, plans provenance without executing)
- Automatic trigger of discovery_walker after successful real copy
- Provenance injected into EVERY entry of the resulting manifest(s)
- Structured target layout under D:/HermesData/data/silo_ingest/<account>/
- Preserves relative Drive structure for accurate source_drive_path computation
- Logging, per-batch summaries, error isolation, retry hints
- Integrates with existing discovery_walker.py + content boost + dt tagging

Usage examples:
  python multi_account_ingest_orchestrator.py --dry-run
  python multi_account_ingest_orchestrator.py --account old_backup_gdrive --paths "MemoryCard_Backups/Google Drive/Medical"
  python multi_account_ingest_orchestrator.py --config configs/silo_remotes.json --session 15

Remotes are user-configured via rclone (see rclone_setup_helper.py and references).
Prepare separate remotes per account for multi-auth scenarios.

After runs: manifests in D:/HermesData/manifests/ will have rich per-file provenance.
"""

from pathlib import Path
import subprocess
import json
import argparse
import logging
from datetime import datetime
import sys
import os
from typing import Dict, List, Optional, Any

# === Paths (D:\HermesData is the silo root) ===
WORK_DIR = Path("D:/HermesData")
DATA_DIR = WORK_DIR / "data"
MANIFEST_DIR = WORK_DIR / "manifests"
RCLONE = WORK_DIR / "rclone_test" / "rclone.exe"
SCRIPTS_DIR = WORK_DIR / "scripts"
INGEST_BASE = DATA_DIR / "silo_ingest" / "multi_account"

# Default configuration - edit or override via --config JSON
# Remotes must be pre-configured in rclone (different logins for different accounts)
DEFAULT_CONFIG = {
    "accounts": {
        "old_backup_gdrive": {
            "remote": "old_backup_gdrive",  # rclone remote name (auth'd with old jeffrey.j.bloom account)
            "description": "Old archived account - primary source of existing MemoryCard_Backups",
            "paths": [
                "MemoryCard_Backups/Google Drive/Medical",
                "MemoryCard_Backups/Google Drive/Navy",
                # Add more high-value paths as discovered
            ],
            "rclone_flags": ["--fast-list", "--transfers", "6", "--checksum"],
        },
        "warz_burner": {
            "remote": "warz_gdrive",
            "description": "Secondary burner account (warz123456789012)",
            "paths": [
                # Populate with paths if data was copied/shared here
            ],
            "rclone_flags": ["--fast-list", "--transfers", "4"],
        },
        "primary_current": {
            "remote": "gdrive",  # or mrjeffrey or whatever current is configured as
            "description": "Primary current account (mr.jeffrey.j.bloom)",
            "paths": [],
            "rclone_flags": ["--fast-list", "--transfers", "4"],
        }
    },
    "defaults": {
        "target_base": str(INGEST_BASE),
        "session": 15,
        "dry_run": False,
        "trigger_walker": True,
        "max_files_per_walker": None,  # None = all; set small for testing
        "rclone_extra": ["--progress", "--stats-one-line", "--log-level", "INFO"],
    }
}

# Setup logging (console + file)
LOG_FILE = WORK_DIR / "logs" / f"multi_account_ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8")
    ]
)
logger = logging.getLogger("silo.ingest.orchestrator")


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load config, merging defaults with optional JSON override."""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if config_path and config_path.exists():
        try:
            user_cfg = json.loads(config_path.read_text(encoding="utf-8"))
            # Merge accounts and defaults
            if "accounts" in user_cfg:
                cfg["accounts"].update(user_cfg["accounts"])
            if "defaults" in user_cfg:
                cfg["defaults"].update(user_cfg["defaults"])
            logger.info(f"Loaded user config from {config_path}")
        except Exception as e:
            logger.error(f"Failed to load config {config_path}: {e}")
    return cfg


def run_rclone(cmd: List[str], dry_run: bool = False) -> subprocess.CompletedProcess:
    """Execute rclone command with good hygiene."""
    if dry_run:
        logger.info("DRY-RUN: would run: " + " ".join(cmd))
        # Return simulated success for dry-run planning
        return subprocess.CompletedProcess(cmd, 0, stdout="DRY-RUN simulated", stderr="")
    logger.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if result.stdout:
        logger.debug(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
    if result.stderr:
        logger.warning("STDERR (last 500): " + result.stderr[-500:])
    if result.returncode != 0:
        logger.error(f"rclone exited with code {result.returncode}")
    return result


def sanitize_path_for_dir(p: str) -> str:
    """Make Drive path safe for local dir name (keep structure but safe)."""
    return p.replace(":", "_").replace("/", "_").replace("\\", "_").replace(" ", "_")[:80]


def copy_from_account(account_name: str, account_cfg: Dict, target_base: Path, 
                      dry_run: bool, rclone_bin: Path, extra_flags: List[str]) -> Dict[str, Any]:
    """Pull one or more paths for a single account. Returns summary with provenance info."""
    remote = account_cfg["remote"]
    paths = account_cfg.get("paths", [])
    flags = account_cfg.get("rclone_flags", []) + extra_flags
    summary = {
        "account": account_name,
        "remote": remote,
        "paths_attempted": [],
        "paths_succeeded": [],
        "paths_failed": [],
        "target_dirs": [],
        "pulled_timestamp": datetime.now().isoformat(),
        "dry_run": dry_run,
    }

    if not paths:
        logger.warning(f"No paths configured for {account_name}, skipping.")
        return summary

    for drive_path in paths:
        safe_sub = sanitize_path_for_dir(drive_path)
        dest = target_base / account_name / safe_sub
        dest.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(rclone_bin),
            "copy",
            f"{remote}:{drive_path}",
            str(dest),
        ] + flags

        logger.info(f"\n=== [{account_name}] Copying from {remote}:{drive_path} -> {dest} ===")
        summary["paths_attempted"].append(drive_path)
        summary["target_dirs"].append(str(dest))

        res = run_rclone(cmd, dry_run=dry_run)
        if dry_run or res.returncode == 0:
            summary["paths_succeeded"].append(drive_path)
            logger.info(f"Copy {'(dry-run planned)' if dry_run else 'completed'} for {drive_path}")
        else:
            summary["paths_failed"].append({"path": drive_path, "code": res.returncode})
            logger.error(f"Failed copy for {drive_path}")

    return summary


def trigger_discovery_walker(target_dir: Path, account_name: str, remote: str, 
                             drive_path: str, pulled_ts: str, session: int,
                             max_files: Optional[int], dry_run: bool) -> Optional[Path]:
    """Call discovery_walker on the just-ingested target, passing full provenance.
    This ensures EVERY manifest entry gets source_account + source_drive_path etc.
    """
    if dry_run:
        logger.info(f"[DRY] Would trigger discovery_walker on {target_dir} with provenance for {account_name}")
        return None

    try:
        # Import here to avoid circular at top if needed
        sys.path.insert(0, str(SCRIPTS_DIR))
        from discovery_walker import run_walker

        # Use a dated manifest name incorporating account
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        manifest_name = f"session{session}_ingest_{account_name}_{ts}.json"
        out_manifest = MANIFEST_DIR / manifest_name

        provenance = {
            "source_account": account_name,
            "remote_name": remote,
            "source_drive_path": drive_path,
            "pulled_timestamp": pulled_ts,
            "original_remote_path": f"{remote}:{drive_path}",
            "ingest_orchestrator": "multi_account_ingest_orchestrator.py",
        }

        logger.info(f"Triggering discovery_walker on {target_dir} (provenance: account={account_name})")
        result = run_walker(
            str(target_dir),
            session=session,
            max_files=max_files,
            output_manifest=out_manifest,
            provenance=provenance
        )
        logger.info(f"Walker complete. Manifest: {out_manifest} | New files: {result.get('new_files', 0)}")
        return out_manifest
    except Exception as e:
        logger.exception(f"Failed to trigger walker for {target_dir}: {e}")
        return None


def create_pull_provenance_record(account_name: str, summary: Dict, target_base: Path):
    """Write a dedicated provenance JSON for the pull batch (separate from walker manifests)."""
    prov = {
        "source_account": account_name,
        "pulled_at": summary.get("pulled_timestamp"),
        "remote": summary.get("remote"),
        "paths": summary.get("paths_succeeded", []),
        "failed_paths": summary.get("paths_failed", []),
        "target_base": str(target_base),
        "target_dirs": summary.get("target_dirs", []),
        "dry_run": summary.get("dry_run", False),
        "orchestrator_version": "1.0-multi-account",
    }
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = MANIFEST_DIR / f"provenance_ingest_{account_name}_{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(prov, indent=2), encoding="utf-8")
    logger.info(f"Provenance record written: {out}")
    return out


def main():
    parser = argparse.ArgumentParser(description="Multi-account Google Drive ingestion orchestrator for silo")
    parser.add_argument("--config", type=Path, help="Optional JSON config file to override defaults")
    parser.add_argument("--account", help="Specific account key to process (default: all with paths)")
    parser.add_argument("--dry-run", action="store_true", help="Plan only, no actual copy or walker")
    parser.add_argument("--no-walker", action="store_true", help="Skip auto-trigger of discovery_walker")
    parser.add_argument("--session", type=int, default=None, help="Session number for manifests (default from config)")
    parser.add_argument("--max-files", type=int, default=None, help="Limit files passed to walker (for testing)")
    parser.add_argument("--target-base", type=Path, help="Override base target dir")
    parser.add_argument("--list-accounts", action="store_true", help="List configured accounts and exit")
    args = parser.parse_args()

    cfg = load_config(args.config)
    defaults = cfg["defaults"]
    accounts_cfg = cfg["accounts"]

    if args.list_accounts:
        print("Configured accounts:")
        for name, ac in accounts_cfg.items():
            print(f"  {name}: remote={ac['remote']}, paths={len(ac.get('paths',[]))}")
        return

    dry_run = args.dry_run or defaults.get("dry_run", False)
    trigger_walker = (not args.no_walker) and defaults.get("trigger_walker", True)
    session = args.session or defaults.get("session", 15)
    maxf = args.max_files if args.max_files is not None else defaults.get("max_files_per_walker")
    target_base = args.target_base or Path(defaults.get("target_base", str(INGEST_BASE)))
    target_base.mkdir(parents=True, exist_ok=True)

    extra_rclone = defaults.get("rclone_extra", ["--progress", "--fast-list"])

    logger.info("=== Multi-Account Silo Ingestion Orchestrator ===")
    logger.info(f"Target base: {target_base}")
    logger.info(f"Session: {session} | Dry-run: {dry_run} | Auto-walker: {trigger_walker}")
    logger.info(f"Rclone: {RCLONE}")
    if not RCLONE.exists():
        logger.warning(f"rclone binary not found at {RCLONE} - copies may fail. Run setup first.")

    accounts_to_process = [args.account] if args.account else list(accounts_cfg.keys())

    overall_summary = {
        "start_time": datetime.now().isoformat(),
        "session": session,
        "dry_run": dry_run,
        "accounts_processed": [],
        "total_succeeded_paths": 0,
        "total_failed": 0,
        "manifests_produced": [],
    }

    for acc_name in accounts_to_process:
        if acc_name not in accounts_cfg:
            logger.error(f"Unknown account: {acc_name}")
            continue
        acc_cfg = accounts_cfg[acc_name]
        if not acc_cfg.get("paths"):
            logger.info(f"Skipping {acc_name} (no paths defined)")
            continue

        logger.info(f"\n{'='*60}\nProcessing account: {acc_name} ({acc_cfg['description']})\n{'='*60}")

        copy_summary = copy_from_account(
            acc_name, acc_cfg, target_base, dry_run=dry_run,
            rclone_bin=RCLONE, extra_flags=extra_rclone
        )

        create_pull_provenance_record(acc_name, copy_summary, target_base)

        overall_summary["accounts_processed"].append({
            "account": acc_name,
            "succeeded": len(copy_summary["paths_succeeded"]),
            "failed": len(copy_summary["paths_failed"]),
        })
        overall_summary["total_succeeded_paths"] += len(copy_summary["paths_succeeded"])
        overall_summary["total_failed"] += len(copy_summary["paths_failed"])

        # Auto-trigger walker per successful path (so provenance per logical batch)
        if trigger_walker and copy_summary["paths_succeeded"]:
            pulled_ts = copy_summary["pulled_timestamp"]
            for i, dpath in enumerate(copy_summary["paths_succeeded"]):
                # Find corresponding target dir (order preserved)
                if i < len(copy_summary["target_dirs"]):
                    tdir = Path(copy_summary["target_dirs"][i])
                    remote = acc_cfg["remote"]
                    man = trigger_discovery_walker(
                        tdir, acc_name, remote, dpath, pulled_ts, session, maxf, dry_run
                    )
                    if man:
                        overall_summary["manifests_produced"].append(str(man))

    overall_summary["end_time"] = datetime.now().isoformat()
    # Write master summary
    summary_path = MANIFEST_DIR / f"ingest_orchestrator_summary_session{session}_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    summary_path.write_text(json.dumps(overall_summary, indent=2), encoding="utf-8")
    logger.info(f"\n=== Orchestrator complete ===")
    logger.info(f"Summary: {summary_path}")
    logger.info(f"Accounts: {len(overall_summary['accounts_processed'])} | Succeeded paths: {overall_summary['total_succeeded_paths']} | Failed: {overall_summary['total_failed']}")
    if overall_summary["manifests_produced"]:
        logger.info(f"Walker manifests: {overall_summary['manifests_produced']}")
    logger.info("All main data + manifests under D:/HermesData as required.")
    if dry_run:
        logger.info("This was a dry-run. Re-run without --dry-run to execute copies + walker.")


if __name__ == "__main__":
    main()
