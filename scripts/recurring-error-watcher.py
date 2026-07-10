#!/usr/bin/env python3
"""Recurring error watcher. Scans Hermes logs + grok-inbox, detects compression/tool patterns, writes summary to vault."""
import os, json, re, datetime
from pathlib import Path

HERMES = Path("C:/Users/CowNi/.hermes")
VAULT_OPS = Path("D:/PhronesisVault/Operations")
LOGS = HERMES / "logs"
INBOX = HERMES / "state" / "grok-inbox.json"
OUT = VAULT_OPS / "Recurring-Errors-Scanner.log"

def scan():
    now = datetime.datetime.utcnow().isoformat() + "Z"
    findings = []
    # Recent compressions
    for logp in [LOGS / "agent.log", LOGS / "gateway.log"]:
        if logp.exists():
            txt = logp.read_text(errors="ignore")[-30000:]
            comps = re.findall(r"Session hygiene:.*compressing|compressed \d+ -> \d+ msgs", txt)
            if len(comps) > 2:
                findings.append(f"COMPRESSION ({logp.name}): {len(comps)} recent. Latest: {comps[-2:]}")
    # Inbox failed/low-turns
    if INBOX.exists():
        try:
            data = json.loads(INBOX.read_text())
            failed = [e for e in data.get("entries", [])[-20:] if e.get("status") == "failed" and e.get("error")]
            if failed:
                findings.append(f"GROK-INBOX: {len(failed)} recent failed. Errors: {[f.get('error') for f in failed[-2:]]}")
        except Exception as e: pass
    # Tool loops / arg errors
    errp = LOGS / "errors.log"
    if errp.exists():
        txt = errp.read_text(errors="ignore")[-15000:]
        bad = re.findall(r"(patch|skill_manage).*?(required|old_string|file_path|not found)|tool_loop|hard stop|same_tool_failure", txt, re.I)
        if len(bad) > 4:
            findings.append(f"TOOL_LOOPS: {len(bad)} hits. Patterns: {bad[-3:]}")
    report = f"[{now}] Recurring scan findings:\n" + "\n".join(findings or ["No strong recurring patterns this tick."]) + "\n"
    VAULT_OPS.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(report + "\n")
    print(report)
    return findings

if __name__ == "__main__":
    scan()
