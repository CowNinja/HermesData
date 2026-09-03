#!/usr/bin/env python3
"""Discord bang macros — zero LLM. Invoke atomic tools / KG directly.

  !telemetry  !status     -> system_telemetry
  !v <query>              -> vault_search (markdown)
  !kg <entity>            -> local KG triples (no generate())

Used by gateway/run.py and agent/conversation_loop.py.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

HERMES = Path(r"D:\HermesData")
SCRIPTS = HERMES / "scripts"
OPS = SCRIPTS / "ops"
TOOLS = SCRIPTS / "tools"
VENV_PY = HERMES / "hermes-agent" / "venv" / "Scripts" / "python.exe"
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Optional mention prefix from Discord mobile: <@id> !status
_MACRO_RE = re.compile(
    r"^(?:<@!?\d+>\s*)?!(telemetry|status|v|kg|models)(?:\s+(.*))?$",
    re.IGNORECASE | re.DOTALL,
)


def _py() -> str:
    return str(VENV_PY if VENV_PY.is_file() else sys.executable)


def _run(script: Path, extra: list[str], timeout: int = 25) -> str:
    if not script.is_file():
        return f"Macro tool missing: {script}"
    try:
        kwargs = dict(
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        if sys.platform == "win32":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            kwargs["startupinfo"] = si
        p = subprocess.run(
            [_py(), str(script), *extra],
            **kwargs,
        )
    except Exception as exc:
        return f"Macro failed: {exc}"
    out = (p.stdout or "").strip() or (p.stderr or "").strip()
    return out[:3500] if out else f"Macro empty (rc={p.returncode})"


def _telemetry() -> str:
    raw = _run(TOOLS / "tool_system_telemetry.py", [], timeout=12)
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:2000]
    cpu = doc.get("cpu") or {}
    ram = doc.get("ram") or {}
    gpu = doc.get("gpu") or {}
    drives = doc.get("drives") or {}
    c = drives.get("C") or {}
    d = drives.get("D") or {}
    k = drives.get("K") or {}
    lines = [
        "**Stack telemetry** (no LLM)",
        f"- CPU {cpu.get('percent')}%  {cpu.get('logical')}c",
        f"- RAM {ram.get('used_gb')}/{ram.get('total_gb')} GB ({ram.get('percent')}%)",
        f"- GPU {gpu.get('name')} VRAM {gpu.get('vram_used_gb')}/{gpu.get('vram_total_gb')} GB  {gpu.get('temp_c')} C",
        f"- C: {c.get('free_gb')} GB free ({c.get('watch')})",
        f"- D: {d.get('free_gb')} GB free · K: {k.get('free_gb')} GB free",
    ]
    return "\n".join(lines)


def _vault(query: str) -> str:
    q = (query or "").strip()
    if len(q) < 2:
        return "Usage: `!v <query>`  e.g. `!v Booksbloom`"
    return _run(
        TOOLS / "tool_vault_search.py",
        ["--query", q, "--roots", "vault", "--max-hits", "8", "--markdown"],
        timeout=20,
    )


def _models() -> str:
    if str(OPS) not in sys.path:
        sys.path.insert(0, str(OPS))
    try:
        import mma_harvester as mma  # type: ignore
        return mma.summary_for_macro()
    except Exception as exc:
        return f"Models macro failed: {exc}"


def _kg(entity: str) -> str:
    q = (entity or "").strip()
    if len(q) < 2:
        return "Usage: `!kg <entity>`  e.g. `!kg ODU`"
    if str(OPS) not in sys.path:
        sys.path.insert(0, str(OPS))
    try:
        import sovereign_query as sq  # type: ignore
    except Exception as exc:
        return f"KG import failed: {exc}"
    needles = sq.toks(q)
    graph = sq.kg_hits(needles, limit=16)
    if not graph:
        return "No sourced data."
    lines = [f"**KG** `{q}` — {len(graph)} triples (local jsonl, no LLM)", ""]
    for rec in graph[:16]:
        s = rec.get("s") or "?"
        r = rec.get("r") or "?"
        o = rec.get("o") or "?"
        lines.append(f"- {s} — {r} — {o}")
    return "\n".join(lines)[:3500]


def extract_text(blob) -> str:
    if blob is None:
        return ""
    if isinstance(blob, str):
        return blob.strip()
    if isinstance(blob, list):
        parts = []
        for p in blob:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                if p.get("type") == "text":
                    parts.append(str(p.get("text") or ""))
                elif "text" in p:
                    parts.append(str(p.get("text") or ""))
        return "\n".join(parts).strip()
    if isinstance(blob, dict):
        return str(blob.get("content") or blob.get("text") or "").strip()
    return str(blob).strip()


def try_macro(text: str) -> Optional[str]:
    raw = extract_text(text)
    if not raw:
        return None
    first = raw.splitlines()[0].strip()
    m = _MACRO_RE.match(first)
    if not m:
        return None
    kind = m.group(1).lower()
    rest = (m.group(2) or "").strip()
    if kind in ("telemetry", "status"):
        return _telemetry()
    if kind == "v":
        return _vault(rest)
    if kind == "kg":
        return _kg(rest)
    if kind == "models":
        return _models()
    return None


if __name__ == "__main__":
    arg = " ".join(sys.argv[1:]) or "!status"
    out = try_macro(arg)
    print(out or "no_macro")
