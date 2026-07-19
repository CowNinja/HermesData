#!/usr/bin/env python3
"""One-shot v1.17 atomic patcher for focus_land + g_to_k. Safe to re-run."""
from __future__ import annotations

import re
import sys
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")


def _nl(t: str) -> str:
    return "\r\n" if "\r\n" in t else "\n"


def ensure_atomic_import(t: str, after: str = "from pathlib import Path") -> str:
    if "from atomic_io import" in t:
        return t
    nl = _nl(t)
    insert = (
        f"{after}{nl}{nl}"
        f"try:{nl}"
        f"    from atomic_io import atomic_write_json, atomic_write_text{nl}"
        f"except ImportError:  # pragma: no cover{nl}"
        f"    atomic_write_json = None  # type: ignore{nl}"
        f"    atomic_write_text = None  # type: ignore"
    )
    if after not in t:
        raise SystemExit(f"anchor missing: {after!r}")
    return t.replace(after, insert, 1)


def replace_once(t: str, old: str, new: str, label: str) -> str:
    if old in t:
        return t.replace(old, new, 1)
    old2 = old.replace("\n", "\r\n")
    new2 = new.replace("\n", "\r\n")
    if old2 in t:
        return t.replace(old2, new2, 1)
    raise SystemExit(f"block not found: {label}")


def patch_focus() -> None:
    p = SCRIPTS / "silo_focus_land.py"
    t = p.read_text(encoding="utf-8")
    t = ensure_atomic_import(t)
    t = replace_once(
        t,
        'def save_cache(c: dict) -> None:\n'
        '    CACHE.parent.mkdir(parents=True, exist_ok=True)\n'
        '    CACHE.write_text(json.dumps(c, indent=2), encoding="utf-8")',
        'def save_cache(c: dict) -> None:\n'
        '    CACHE.parent.mkdir(parents=True, exist_ok=True)\n'
        '    if atomic_write_json is not None:\n'
        '        atomic_write_json(CACHE, c, indent=2)\n'
        '    else:\n'
        '        CACHE.write_text(json.dumps(c, indent=2), encoding="utf-8")',
        "save_cache",
    )
    t = replace_once(
        t,
        'def save_empty_state(d: dict) -> None:\n'
        '    EMPTY_STATE.parent.mkdir(parents=True, exist_ok=True)\n'
        '    EMPTY_STATE.write_text(json.dumps(d, indent=2), encoding="utf-8")',
        'def save_empty_state(d: dict) -> None:\n'
        '    EMPTY_STATE.parent.mkdir(parents=True, exist_ok=True)\n'
        '    if atomic_write_json is not None:\n'
        '        atomic_write_json(EMPTY_STATE, d, indent=2)\n'
        '    else:\n'
        '        EMPTY_STATE.write_text(json.dumps(d, indent=2), encoding="utf-8")',
        "save_empty_state",
    )
    m = re.search(
        r'^([ \t]*)QUEUE\.write_text\(json\.dumps\(data, indent=2\), encoding=["\']utf-8["\']\)$',
        t,
        re.M,
    )
    if not m:
        raise SystemExit("QUEUE write not found")
    indent = m.group(1)
    nl = _nl(t)
    new = (
        f"{indent}if atomic_write_json is not None:{nl}"
        f"{indent}    atomic_write_json(QUEUE, data, indent=2){nl}"
        f"{indent}else:{nl}"
        f'{indent}    QUEUE.write_text(json.dumps(data, indent=2), encoding="utf-8")'
    )
    t = t[: m.start()] + new + t[m.end() :]
    p.write_text(t, encoding="utf-8", newline="")
    print("FOCUS_OK")


def patch_g2k() -> None:
    p = SCRIPTS / "g_to_k_safe_drain.py"
    t = p.read_text(encoding="utf-8")
    t = ensure_atomic_import(t)
    nl = _nl(t)

    m = re.search(
        r'^([ \t]*)lock\.write_text\(payload, encoding=["\']utf-8["\']\)$',
        t,
        re.M,
    )
    if not m:
        raise SystemExit("lock write not found")
    indent = m.group(1)
    new = (
        f"{indent}if atomic_write_text is not None:{nl}"
        f'{indent}    atomic_write_text(lock, payload if payload.endswith("\\n") else payload + "\\n", min_bytes=1){nl}'
        f"{indent}else:{nl}"
        f'{indent}    lock.write_text(payload, encoding="utf-8")'
    )
    t = t[: m.start()] + new + t[m.end() :]

    m = re.search(r'^([ \t]*)\(STAGING / f"batch-\{TS\}\.json"\)\.write_text\(', t, re.M)
    if not m:
        raise SystemExit("batch write not found")
    start = m.start()
    end = t.find("\n", m.end())
    if end < 0:
        end = len(t)
    # drop trailing \r if present before \n was stripped
    indent = m.group(1)
    new = (
        f'{indent}batch_path = STAGING / f"batch-{{TS}}.json"{nl}'
        f"{indent}if atomic_write_json is not None:{nl}"
        f"{indent}    atomic_write_json(batch_path, meta_batch, indent=2){nl}"
        f"{indent}else:{nl}"
        f'{indent}    batch_path.write_text(json.dumps(meta_batch, indent=2), encoding="utf-8")'
    )
    t = t[:start] + new + t[end:]

    m = re.search(r'^([ \t]*)RECEIPT\.write_text\(', t, re.M)
    if not m:
        raise SystemExit("RECEIPT write not found")
    start = m.start()
    end = t.find("\n", m.end())
    if end < 0:
        end = len(t)
    indent = m.group(1)
    new = (
        f"{indent}if atomic_write_text is not None:{nl}"
        f'{indent}    atomic_write_text(RECEIPT, "\\n".join(lines), min_bytes=20){nl}'
        f"{indent}else:{nl}"
        f'{indent}    RECEIPT.write_text("\\n".join(lines), encoding="utf-8")'
    )
    t = t[:start] + new + t[end:]

    p.write_text(t, encoding="utf-8", newline="")
    print("G2K_OK")


def main() -> int:
    patch_focus()
    patch_g2k()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
