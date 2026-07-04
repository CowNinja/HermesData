"""ComfyUI output filename patterns - standard__ and regional__ namespaces."""
from __future__ import annotations

import re
from pathlib import Path

COMFY_OUTPUT = Path(r"D:\ComfyUI\output")
OUTPUT_PNG_GLOBS = ("standard__*.png", "regional__*.png")
OUTPUT_PNG_RE = re.compile(r"(?:standard|regional)__(\d+)_\.png$")
OUTPUT_PREFIXES = ("standard__", "regional__")


def iter_output_pngs(output_dir: Path | None = None):
    root = output_dir or COMFY_OUTPUT
    for pat in OUTPUT_PNG_GLOBS:
        yield from root.glob(pat)


def parse_png_index(name: str) -> int | None:
    m = OUTPUT_PNG_RE.match(name)
    return int(m.group(1)) if m else None


def is_batch_png(name: str) -> bool:
    return bool(OUTPUT_PNG_RE.match(name))


def max_png_index(output_dir: Path | None = None) -> int:
    best = 0
    for path in iter_output_pngs(output_dir):
        idx = parse_png_index(path.name)
        if idx:
            best = max(best, idx)
    return best