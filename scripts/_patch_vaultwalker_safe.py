#!/usr/bin/env python3
"""One-shot hardener for vaultwalker.py (v0.7.0 safe gardener)."""
from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

P = Path(r"D:\HermesData\scripts\vaultwalker.py")


def main() -> int:
    bak = P.with_suffix(P.suffix + f".bak-safe-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(P, bak)
    text = P.read_text(encoding="utf-8")

    # --- sanitize_non_ascii: never collapse newlines ---
    new_san = '''def sanitize_non_ascii(text: str) -> str:
    """ASCII-clean without destroying structure.

    CRITICAL: never collapse newlines/tabs (2026-07-09 zero-newline incident).
    Only strip non-ASCII; preserve LF/CR/TAB and normal spaces.
    """
    normalized = unicodedata.normalize("NFKD", text)
    out = []
    for ch in normalized:
        o = ord(ch)
        if ch in ("\\t", "\\n", "\\r") or 32 <= o <= 126:
            out.append(ch)
    cleaned = "".join(out)
    if text.count("\\n") > 0 and cleaned.count("\\n") == 0:
        return text  # refuse zero-newline corruption
    return cleaned if cleaned else text

'''
    # fix double-escaped - write real newlines in function body
    new_san = (
        "def sanitize_non_ascii(text: str) -> str:\n"
        '    """ASCII-clean without destroying structure.\n'
        "\n"
        "    CRITICAL: never collapse newlines/tabs (2026-07-09 zero-newline incident).\n"
        "    Only strip non-ASCII; preserve LF/CR/TAB and normal spaces.\n"
        '    """\n'
        '    normalized = unicodedata.normalize("NFKD", text)\n'
        "    out = []\n"
        "    for ch in normalized:\n"
        "        o = ord(ch)\n"
        '        if ch in ("\\t", "\\n", "\\r") or 32 <= o <= 126:\n'
        "            out.append(ch)\n"
        '    cleaned = "".join(out)\n'
        '    if text.count("\\n") > 0 and cleaned.count("\\n") == 0:\n'
        "        return text  # refuse zero-newline corruption\n"
        "    return cleaned if cleaned else text\n"
        "\n"
    )
    pat = re.compile(r"^def sanitize_non_ascii\(.*?(?=^def )", re.M | re.S)
    m = pat.search(text)
    if not m:
        print("sanitize not found")
        return 1
    text = text[: m.start()] + new_san + text[m.end() :]

    text = text.replace("VaultWalker v0.6.2", "VaultWalker v0.7.0")
    text = text.replace('"version": "0.6.2"', '"version": "0.7.0"')
    text = text.replace("v0.6.2", "v0.7.0")

    # global config defaults
    needle = """    global_cfg = full.get(\"global\", {})
    global_cfg.setdefault(\"persistent_state\", True)
    global_cfg.setdefault(\"staggered_cycles\", True)
    global_cfg.setdefault(\"local_models\", True)
"""
    repl = """    global_cfg = full.get(\"global\", {}) or {}
    ip = global_cfg.get(\"iteration_policies\") or {}
    if isinstance(ip, dict):
        for k, v in ip.items():
            global_cfg.setdefault(k, v)
    global_cfg.setdefault(\"persistent_state\", True)
    global_cfg.setdefault(\"staggered_cycles\", True)
    global_cfg.setdefault(\"local_models\", True)
    global_cfg.setdefault(\"dry_run_default\", True)
"""
    if needle in text:
        text = text.replace(needle, repl)
    else:
        print("WARN: global_cfg block not exact; continuing")

    # Replace main() through end-before if __name__
    new_main = Path(__file__).with_name("_vaultwalker_main_v07.py").read_text(encoding="utf-8")
    pat_main = re.compile(r"^def main\(\):.*?(?=^if __name__)", re.M | re.S)
    m = pat_main.search(text)
    if not m:
        print("main not found")
        return 1
    text = text[: m.start()] + new_main + "\n" + text[m.end() :]

    ast.parse(text)
    P.write_text(text, encoding="utf-8", newline="\n")
    print("OK wrote", P)
    print("backup", bak)

    # smoke dry-run tiny
    r = subprocess.run(
        [sys.executable, str(P), "--silos", "PhronesisVault", "--dry-run", "--max-silos", "1"],
        capture_output=True,
        text=True,
        timeout=240,
    )
    print("smoke_exit", r.returncode)
    print((r.stdout or "")[-1200:])
    if r.stderr:
        print("stderr", r.stderr[-400:])
    return 0 if r.returncode == 0 else r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
