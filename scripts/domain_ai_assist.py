#!/usr/bin/env python3
"""Optional local-AI domain suggestion for borderline filenames.

Uses grunt_local only — never Grok. Does not move files.
Deterministic domain_route still wins when it matches a non-inbox domain.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\HermesData\scripts")))
from domain_route import domain_for  # noqa: E402

GRUNT = Path(r"D:\HermesData\scripts\grunt_local.py")
DOMAINS = [
    "Medical-Records",
    "Navy-Service",
    "Core-Personal/Finance",
    "Core-Personal/Career",
    "Core-Personal/Spiritual",
    "Core-Personal/Family",
    "Core-Personal/Education",
    "Core-Personal/Projects",
    "Digital-Footprint",
    "Life-Archive",
    "Core-Personal/_Inbox",
]


def local_domain_vote(name: str, context: str = "") -> dict:
    if not GRUNT.exists():
        return {"error": "no_grunt"}
    prompt = (
        "Classify this personal file into ONE domain for a life data silo. "
        "Reply JSON only: {\"domain\":\"...\",\"confidence\":0-1,\"why\":\"...\"}. "
        f"Allowed domains: {DOMAINS}. "
        "Jeff endocrinologist = Medical. Navy/military = Navy-Service. "
        "When unsure use Core-Personal/_Inbox. "
        f"Filename: {name}. Context: {context[:400]}"
    )
    r = subprocess.run(
        [sys.executable, str(GRUNT), "classify", "--text", prompt[:1500]],
        capture_output=True,
        text=True,
        timeout=90,
    )
    out = (r.stdout or "") + (r.stderr or "")
    # best-effort parse
    try:
        start = out.find("{")
        end = out.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(out[start:end])
    except Exception:
        pass
    return {"raw": out[-500:], "vote": None}


def assess(name: str, use_ai: bool = False) -> dict:
    det = domain_for(name)
    row = {"name": name, "deterministic": det, "ai": None, "final": det}
    if use_ai and det.endswith("_Inbox"):
        ai = local_domain_vote(name)
        row["ai"] = ai
        dom = (ai or {}).get("domain")
        if dom in DOMAINS and not str(dom).endswith("_Inbox"):
            row["final"] = dom
            row["source"] = "local_ai"
        else:
            row["source"] = "deterministic_inbox"
    else:
        row["source"] = "deterministic"
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--ai", action="store_true")
    args = ap.parse_args()
    print(json.dumps([assess(n, use_ai=args.ai) for n in args.names], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
