#!/usr/bin/env python3
"""
extract_wisdom.py — Episodic Memory Extractor
Scans session logs and error patterns to build structured wisdom entries
for the evolution loop's Orient phase.

Usage:
    python extract_wisdom.py --scan-sessions
    python extract_wisdom.py --scan-errors
    python extract_wisdom.py --list
    python extract_wisdom.py --stats
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
HERMESDATA = SCRIPT_DIR.parent
GENE_DIR = HERMESDATA / "skill_evo"
EPISODIC_FILE = GENE_DIR / "episodic.jsonl"
LOG_DIR = GENE_DIR / "logs"

for p in [GENE_DIR, LOG_DIR]:
    p.mkdir(parents=True, exist_ok=True)

# Patterns that indicate problem/solution pairs
PATTERNS = {
    "fix": [
        re.compile(r"(?:fixed|resolved|patched|repaired)\s+(.+?)(?:\.|$)", re.IGNORECASE),
        re.compile(r"(?:fix|patch|resolve)\s+(?:for|to)\s+(.+?)(?:\.|$)", re.IGNORECASE),
    ],
    "error": [
        re.compile(r"(?:error|bug|issue|failure|traceback)\s*[:]\s*(.+?)(?:\.|$)", re.IGNORECASE),
        re.compile(r"(?:ERROR|FAILED|Exception)\s*[:]\s*(.+?)(?:\.|$)"),
    ],
    "lesson": [
        re.compile(r"(?:lesson|learned|key insight|takeaway)\s*[:]\s*(.+?)(?:\.|$)", re.IGNORECASE),
        re.compile(r"(?:remember|note)\s*[:]\s+(.+?)(?:\.|$)", re.IGNORECASE),
    ],
    "solution": [
        re.compile(r"(?:solution|workaround|hack)\s*[:]\s*(.+?)(?:\.|$)", re.IGNORECASE),
        re.compile(r"(?:use|try|apply)\s+(.+?)\s+(?:to|for)\s+(.+?)(?:\.|$)", re.IGNORECASE),
    ],
}


def scan_log_file(log_path: Path) -> list:
    """Extract wisdom entries from a single log file"""
    entries = []
    try:
        content = log_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return entries
    
    lines = content.split("\n")
    for i, line in enumerate(lines):
        for category, patterns in PATTERNS.items():
            for pattern in patterns:
                match = pattern.search(line)
                if match:
                    # Get context: surrounding 2 lines
                    context_start = max(0, i - 1)
                    context_end = min(len(lines), i + 2)
                    context = " ".join(lines[context_start:context_end]).strip()
                    
                    entry = {
                        "type": "episodic_memory",
                        "category": category,
                        "source": str(log_path.name),
                        "line": i + 1,
                        "extracted": match.group(1).strip() if match.lastindex else match.group(0).strip(),
                        "context": context[:200],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "verified": False,
                    }
                    entries.append(entry)
                    break  # One match per line per category
    
    return entries


def scan_sessions(limit: int = 20) -> list:
    """Scan recent session-related logs for wisdom"""
    entries = []
    
    # Scan skill_evo logs
    log_sources = [
        (LOG_DIR, "*.log"),
        (LOG_DIR, "*.jsonl"),
        (GENE_DIR, "*.jsonl"),
    ]
    
    for source_dir, pattern in log_sources:
        if not source_dir.exists():
            continue
        for log_file in sorted(source_dir.glob(pattern)):
            entries.extend(scan_log_file(log_file))
    
    # Scan recent benchmark results for failure patterns
    bench_dir = GENE_DIR / "benchmarks"
    if bench_dir.exists():
        for bench_file in sorted(bench_dir.glob("bench_*.jsonl"))[-3:]:  # last 3
            try:
                with open(bench_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        record = json.loads(line)
                        if not record.get("passed"):
                            entry = {
                                "type": "episodic_memory",
                                "category": "benchmark_failure",
                                "source": bench_file.name,
                                "extracted": f"Benchmark '{record.get('id')}' failed: {record.get('notes', '')}",
                                "context": json.dumps(record.get("details", {}))[:200],
                                "timestamp": record.get("timestamp", datetime.now(timezone.utc).isoformat()),
                                "verified": False,
                                "benchmark_id": record.get("id"),
                            }
                            entries.append(entry)
            except Exception:
                pass
    
    # Deduplicate by extracted text
    seen = set()
    unique = []
    for e in entries:
        key = e["extracted"][:80]
        if key not in seen:
            seen.add(key)
            unique.append(e)
    
    return unique[:limit]


def scan_error_logs() -> list:
    """Scan system error patterns"""
    entries = []
    
    # Check Windows Event Log for recent errors (if accessible)
    # Check hermes logs
    hermes_log = HERMESDATA / "hermes-workspace" / "server.log"
    if hermes_log.exists():
        entries.extend(scan_log_file(hermes_log))
    
    # Check for Python traceback patterns in all .log files
    for log_file in LOG_DIR.glob("*.log"):
        entries.extend(scan_log_file(log_file))
    
    return entries


def save_entries(entries: list) -> int:
    """Append entries to episodic JSONL, skip duplicates"""
    existing = set()
    if EPISODIC_FILE.exists():
        with open(EPISODIC_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        ev = json.loads(line)
                        existing.add(ev.get("extracted", "")[:80])
                    except json.JSONDecodeError:
                        pass
    
    new_count = 0
    with open(EPISODIC_FILE, "a", encoding="utf-8") as f:
        for entry in entries:
            key = entry["extracted"][:80]
            if key not in existing:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                existing.add(key)
                new_count += 1
    
    return new_count


def list_entries(limit: int = 20, category: str = None):
    """List recent episodic memory entries"""
    if not EPISODIC_FILE.exists():
        print("  No episodic memory yet.")
        return
    
    entries = []
    with open(EPISODIC_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    
    if category:
        entries = [e for e in entries if e.get("category") == category]
    
    # Show most recent
    print(f"\n  Episodic Memory ({len(entries)} total, showing last {limit}):")
    print(f"  {'─'*70}")
    for e in entries[-limit:]:
        ts = e.get("timestamp", "?")[:19]
        cat = e.get("category", "?")
        ext = e.get("extracted", "")[:60]
        print(f"  {ts}  [{cat:18s}]  {ext}")


def show_stats():
    """Show episodic memory statistics"""
    if not EPISODIC_FILE.exists():
        print("  No episodic memory yet.")
        return
    
    entries = []
    with open(EPISODIC_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    
    categories = {}
    sources = {}
    for e in entries:
        cat = e.get("category", "unknown")
        src = e.get("source", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
        sources[src] = sources.get(src, 0) + 1
    
    print(f"\n  Episodic Memory Stats:")
    print(f"  {'─'*40}")
    print(f"  Total entries: {len(entries)}")
    print(f"\n  By category:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"    {cat:25s} {count}")
    print(f"\n  By source:")
    for src, count in sorted(sources.items(), key=lambda x: -x[1])[:10]:
        print(f"    {src:30s} {count}")


def main():
    parser = argparse.ArgumentParser(description="Episodic Memory Extractor")
    parser.add_argument("--scan-sessions", action="store_true", help="Scan logs for wisdom")
    parser.add_argument("--scan-errors", action="store_true", help="Scan for error patterns")
    parser.add_argument("--list", action="store_true", help="List recent entries")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--limit", type=int, default=20, help="Limit results")
    parser.add_argument("--category", type=str, help="Filter by category")
    args = parser.parse_args()
    
    if args.scan_sessions:
        print("  Scanning sessions for wisdom...")
        entries = scan_sessions(limit=args.limit)
        new_count = save_entries(entries)
        print(f"  Found {len(entries)} entries, {new_count} new saved to episodic memory")
    elif args.scan_errors:
        print("  Scanning for error patterns...")
        entries = scan_error_logs()
        new_count = save_entries(entries)
        print(f"  Found {len(entries)} error patterns, {new_count} new saved")
    elif args.list:
        list_entries(limit=args.limit, category=args.category)
    elif args.stats:
        show_stats()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
