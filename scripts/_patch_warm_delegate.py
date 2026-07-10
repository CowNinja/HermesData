#!/usr/bin/env python3
"""One-shot: point warm_tier restart action at stack_healing_once (single authority)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

TARGET = Path(r"D:\PhronesisVault\scripts\warm_tier_actions.py")

OLD_PAT = re.compile(
    r"def restart_gateway\(\) -> Dict\[str, Any\]:.*?hint\": \"Hermes gateway restarted on :8642\.\", \*\*result, \}"
)

NEW = (
    "def restart_gateway() -> Dict[str, Any]: "
    "healer = Path(r\"D:\\HermesData\\scripts\\stack_healing_once.py\"); "
    "py = Path(r\"D:\\HermesData\\hermes-agent\\venv\\Scripts\\python.exe\"); "
    "py = py if py.is_file() else Path(sys.executable); "
    "try: "
    "r = subprocess.run([str(py), str(healer), \"--force\", \"--no-watchdog\"], "
    "capture_output=True, text=True, timeout=180, cwd=str(healer.parent)); "
    "parsed = {}; raw = (r.stdout or \"\").strip(); "
    "parsed = (json.loads(raw) if raw.startswith(\"{\") else {\"raw\": raw[-600:]}) if raw else {}; "
    "stack = verify_unified_stack(); "
    "ok = bool((stack.get(\"8642\") or {}).get(\"up\")) or (r.returncode == 0); "
    "return {\"action\": \"restart-gateway\", \"port\": 8642, \"ok\": ok, "
    "\"hint\": \"Delegated to stack_healing_once (single authority).\", "
    "\"code\": r.returncode, \"healer\": parsed} "
    "except Exception as exc: "
    "stack = verify_unified_stack(); "
    "return {\"action\": \"restart-gateway\", \"port\": 8642, "
    "\"ok\": bool((stack.get(\"8642\") or {}).get(\"up\")), \"error\": str(exc), "
    "\"hint\": \"stack_healing_once failed\"} "
)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    m = OLD_PAT.search(text)
    if not m:
        if "Delegated to stack_healing_once" in text:
            print("already_delegated")
            return 0
        print("NO_MATCH", file=sys.stderr)
        return 1
    out = text[: m.start()] + NEW + text[m.end() :]
    compile(out, str(TARGET), "exec")
    TARGET.write_text(out, encoding="utf-8")
    print("patched", m.start(), m.end(), "->", len(NEW))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
