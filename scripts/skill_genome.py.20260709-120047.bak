#!/usr/bin/env python3
"""
skill_genome.py — Skill Mutation Tracking & Version Control
Snapshots skill files before mutation, logs changes, supports rollback.

Usage:
    python skill_genome.py snapshot vault-curation
    python skill_genome.py log vault-curation "Added L4 header"
    python skill_genome.py rollback vault-curation evo-3
    python skill_genome.py history vault-curation
    python skill_genome.py diff vault-curation evo-2 evo-3
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from difflib import unified_diff

SCRIPT_DIR = Path(__file__).resolve().parent
HERMESDATA = SCRIPT_DIR.parent
SKILLS_DIR = HERMESDATA / "skills"
GENE_DIR = HERMESDATA / "skill_evo"
SNAPSHOT_DIR = GENE_DIR / "snapshots"
LOG_FILE = GENE_DIR / "episodic.jsonl"

for p in [SNAPSHOT_DIR]:
    p.mkdir(parents=True, exist_ok=True)


def file_hash(path: Path) -> str:
    """SHA-256 hash of file content"""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def next_evo_tag(skill: str) -> str:
    """Determine next evolution tag number for a skill"""
    existing = list(SNAPSHOT_DIR.glob(f"{skill}-evo-*.md"))
    if not existing:
        return "evo-1"
    numbers = []
    for p in existing:
        m = re.search(r'evo-(\d+)\.md$', p.name)
        if m:
            numbers.append(int(m.group(1)))
    return f"evo-{max(numbers) + 1}" if numbers else "evo-1"


def snapshot_skill(skill: str, reason: str = "") -> dict:
    """Create a snapshot of the current skill before mutation"""
    skill_dir = SKILLS_DIR / skill
    if not skill_dir.exists():
        return {"error": f"Skill not found: {skill}"}
    
    tag = next_evo_tag(skill)
    
    # Snapshot the SKILL.md + any linked files
    snapshot_meta = {
        "skill": skill,
        "tag": tag,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "files": [],
    }
    
    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists():
        snapshot_path = SNAPSHOT_DIR / f"{skill}-{tag}.md"
        shutil.copy2(skill_md, snapshot_path)
        snapshot_meta["files"].append({
            "source": str(skill_md),
            "snapshot": str(snapshot_path),
            "size": skill_md.stat().st_size,
            "hash": file_hash(skill_md),
        })
    
    # Snapshot references/ directory if it exists
    ref_dir = skill_dir / "references"
    if ref_dir.exists() and ref_dir.is_dir():
        snapshot_ref_dir = SNAPSHOT_DIR / f"{skill}-{tag}-references"
        if snapshot_ref_dir.exists():
            shutil.rmtree(snapshot_ref_dir)
        shutil.copytree(ref_dir, snapshot_ref_dir)
        snapshot_meta["files"].append({
            "source": str(ref_dir),
            "snapshot": str(snapshot_ref_dir),
            "type": "directory",
        })
    
    # Log the snapshot
    _log_event({
        "type": "snapshot_created",
        "skill": skill,
        "tag": tag,
        "timestamp": snapshot_meta["timestamp"],
        "file_count": len(snapshot_meta["files"]),
    })
    
    print(f"  SNAPSHOT: {skill} -> {tag} ({len(snapshot_meta['files'])} files)")
    return snapshot_meta


def log_mutation(skill: str, tag: str, reason: str, 
                 score_before: float = None, score_after: float = None,
                 notes: str = "") -> dict:
    """Log a mutation event"""
    event = {
        "type": "mutation",
        "skill": skill,
        "tag": tag,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "score_before": score_before,
        "score_after": score_after,
        "score_delta": (score_after - score_before) if (score_before is not None and score_after is not None) else None,
        "notes": notes,
    }
    _log_event(event)
    
    delta = f" ({event['score_delta']:+.3f})" if event['score_delta'] is not None else ""
    print(f"  MUTATION: {skill}/{tag} — {reason}{delta}")
    return event


def rollback_skill(skill: str, tag: str) -> dict:
    """Rollback skill to a specific evolution tag"""
    skill_md = SKILLS_DIR / skill / "SKILL.md"
    snapshot_path = SNAPSHOT_DIR / f"{skill}-{tag}.md"
    
    if not snapshot_path.exists():
        print(f"  ERROR: Snapshot not found: {snapshot_path}")
        return {"error": f"Snapshot not found: {snapshot_path}"}
    
    # Safety: snapshot current before rollback
    if skill_md.exists():
        safety_tag = next_evo_tag(skill)
        safety_path = SNAPSHOT_DIR / f"{skill}-{safety_tag}-rollback-safety.md"
        shutil.copy2(skill_md, safety_path)
        print(f"  SAFETY: Current state saved as {safety_tag}-rollback-safety")
    
    # Perform rollback
    shutil.copy2(snapshot_path, skill_md)
    
    # Rollback references if snapshot exists
    snap_ref_dir = SNAPSHOT_DIR / f"{skill}-{tag}-references"
    current_ref_dir = skill_md.parent / "references"
    if snap_ref_dir.exists():
        if current_ref_dir.exists():
            shutil.rmtree(current_ref_dir)
        shutil.copytree(snap_ref_dir, current_ref_dir)
    
    event = {
        "type": "rollback",
        "skill": skill,
        "to_tag": tag,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "new_hash": file_hash(skill_md),
    }
    _log_event(event)
    print(f"  ROLLBACK: {skill} restored to {tag}")
    return event


def show_history(skill: str, limit: int = 10):
    """Show mutation history for a skill"""
    events = []
    if LOG_FILE.exists():
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if ev.get("skill") == skill:
                        events.append(ev)
                except json.JSONDecodeError:
                    pass
    
    if not events:
        print(f"  No history for skill: {skill}")
        return
    
    print(f"\n  Mutation History for {skill} (last {limit}):")
    print(f"  {'─'*50}")
    for ev in events[-limit:]:
        ts = ev.get("timestamp", "?")[:19]
        etype = ev.get("type", "?")
        if etype == "snapshot_created":
            print(f"  {ts}  SNAPSHOT  {ev.get('tag', '?')}  ({ev.get('file_count', '?')} files)")
        elif etype == "mutation":
            delta = f"  score: {ev.get('score_delta', '?')}" if ev.get('score_delta') is not None else ""
            print(f"  {ts}  MUTATION   {ev.get('tag', '?')}  {ev.get('reason', '?')[:40]}{delta}")
        elif etype == "rollback":
            print(f"  {ts}  ROLLBACK   -> {ev.get('to_tag', '?')}")
        else:
            print(f"  {ts}  {etype}")


def show_diff(skill: str, tag1: str, tag2: str):
    """Show diff between two evolution tags"""
    file1 = SNAPSHOT_DIR / f"{skill}-{tag1}.md"
    file2 = SNAPSHOT_DIR / f"{skill}-{tag2}.md"
    
    if not file1.exists():
        print(f"  ERROR: {file1} not found")
        return
    if not file2.exists():
        print(f"  ERROR: {file2} not found")
        return
    
    lines1 = file1.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    lines2 = file2.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    
    diff = unified_diff(
        lines1, lines2,
        fromfile=f"{skill}/{tag1}",
        tofile=f"{skill}/{tag2}",
    )
    print("".join(diff))


def list_snapshots(skill: str = None):
    """List all snapshots, optionally filtered by skill"""
    if not SNAPSHOT_DIR.exists():
        print("  No snapshots directory.")
        return
    
    snapshots = sorted(SNAPSHOT_DIR.iterdir())
    if skill:
        snapshots = [s for s in snapshots if s.name.startswith(f"{skill}-")]
    
    if not snapshots:
        print(f"  No snapshots found" + (f" for {skill}" if skill else ""))
        return
    
    print(f"\n  Snapshots ({len(snapshots)}):")
    for s in snapshots:
        size = s.stat().st_size if s.is_file() else 0
        ts = datetime.fromtimestamp(s.stat().st_mtime, tz=timezone.utc).strftime("%Y%m%d_%H%M")
        print(f"    {s.name:50s} {size:>6d}B  {ts}")


def _log_event(event: dict):
    """Append event to episodic log"""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Skill Mutation Genome Tracker")
    sub = parser.add_subparsers(dest="command")
    
    snap_parser = sub.add_parser("snapshot", help="Create pre-mutation snapshot")
    snap_parser.add_argument("skill", type=str)
    snap_parser.add_argument("--reason", type=str, default="")
    
    log_parser = sub.add_parser("log", help="Log a mutation event")
    log_parser.add_argument("skill", type=str)
    log_parser.add_argument("tag", type=str)
    log_parser.add_argument("reason", type=str)
    log_parser.add_argument("--score-before", type=float, default=None)
    log_parser.add_argument("--score-after", type=float, default=None)
    log_parser.add_argument("--notes", type=str, default="")
    
    rollback_parser = sub.add_parser("rollback", help="Rollback to tag")
    rollback_parser.add_argument("skill", type=str)
    rollback_parser.add_argument("tag", type=str)
    
    history_parser = sub.add_parser("history", help="Show mutation history")
    history_parser.add_argument("skill", type=str)
    history_parser.add_argument("--limit", type=int, default=10)
    
    diff_parser = sub.add_parser("diff", help="Show diff between tags")
    diff_parser.add_argument("skill", type=str)
    diff_parser.add_argument("tag1", type=str)
    diff_parser.add_argument("tag2", type=str)
    
    list_parser = sub.add_parser("list", help="List snapshots")
    list_parser.add_argument("skill", type=str, nargs="?", default=None)
    
    args = parser.parse_args()
    
    if args.command == "snapshot":
        result = snapshot_skill(args.skill, args.reason)
        if "error" in result:
            print(f"  ERROR: {result['error']}")
    elif args.command == "log":
        log_mutation(args.skill, args.tag, args.reason,
                     args.score_before, args.score_after, args.notes)
    elif args.command == "rollback":
        rollback_skill(args.skill, args.tag)
    elif args.command == "history":
        show_history(args.skill, args.limit)
    elif args.command == "diff":
        show_diff(args.skill, args.tag1, args.tag2)
    elif args.command == "list":
        list_snapshots(args.skill)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
