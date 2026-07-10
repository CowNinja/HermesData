#!/usr/bin/env python3
"""Wire locked_seed + identity_lock through generate.py and duo compose."""
from __future__ import annotations

from pathlib import Path

# --- generate.py: prefer locked_seed ---
gen = Path(r"D:\HermesData\skills\creative\uncensored-image-generation\scripts\generate.py")
gt = gen.read_text(encoding="utf-8")
old = """    print("[count verification] requested count=" + str(getattr(args, "count", 1)))  # task 4 progress
    if args.seed == -1:
        args.seed = random.randint(0, 2**32 - 1)
"""
new = """    print("[count verification] requested count=" + str(getattr(args, "count", 1)))  # task 4 progress
    # Prefer per-character locked_seed from visual-tags for consistency.
    if args.seed == -1:
        locked = None
        chars = list(args.character or [])
        if getattr(args, "with_character", None):
            chars.append(args.with_character)
        if chars:
            try:
                root = Path(args.registry_root or DEFAULT_REGISTRY_ROOT)
                vr = _load_registry_builder(root)
                if vr:
                    entry = vr.get_cast_entry(chars[0].strip().lower())
                    locked = entry.get("locked_seed")
            except Exception:
                locked = None
        if locked not in (None, "", 0, "0"):
            args.seed = int(locked)
            print(f"[seed] using locked_seed={args.seed} for {chars[0]}")
        else:
            args.seed = random.randint(0, 2**32 - 1)
"""
if old not in gt:
    raise SystemExit("generate.py seed block not found")
gen.write_text(gt.replace(old, new, 1), encoding="utf-8")
print("patched generate.py seed")

# --- prompt_compose duo explicit girl blocks ---
pc = Path(r"D:\PhronesisVault\Roleplay-Sandbox\sandbox\lib\prompt_compose.py")
pt = pc.read_text(encoding="utf-8")

old_duo_ex = """        girl_parts: list[str] = []
        for cid in characters:
            cast = (cfg.get("cast") or {}).get(cid, {})
            prose = str(cast.get("explicit_identity") or cast.get("portrait_prompt") or cast.get("body_tags") or "")
            if prose and not cast.get("explicit_identity") and "full body" in prose.lower():
                prose = prose.split("full body", 1)[0].strip().rstrip(",")
            bust = str(cast.get("bust_emphasis") or "").strip()
            block = ", ".join(x for x in [prose, bust, nude_lock] if x)
            girl_parts.append(block)
"""
new_duo_ex = """        girl_parts: list[str] = []
        for cid in characters:
            cast = (cfg.get("cast") or {}).get(cid, {})
            id_layers = identity_body_layers(cast, cfg, scene=scene_use, explicit=True)
            prose = str(cast.get("explicit_identity") or cast.get("portrait_prompt") or cast.get("body_tags") or "")
            if prose and not cast.get("explicit_identity") and "full body" in prose.lower():
                prose = prose.split("full body", 1)[0].strip().rstrip(",")
            bust = str(cast.get("bust_emphasis") or "").strip()
            block = ", ".join(
                x
                for x in [
                    id_layers.get("identity", ""),
                    prose,
                    id_layers.get("body", "") or bust,
                    id_layers.get("expression", ""),
                    nude_lock,
                ]
                if x
            )
            girl_parts.append(block)
"""
if old_duo_ex not in pt:
    raise SystemExit("duo explicit block not found")
pt = pt.replace(old_duo_ex, new_duo_ex, 1)

old_duo = """    girl_parts: list[str] = []
    for i, cid in enumerate(characters):
        cast = (cfg.get("cast") or {}).get(cid, {})
        body = (
            str(cast.get("body_tags") or cast.get("tags") or "")
            .replace("1girl, solo,", "1girl,")
            .replace(", solo", "")
        )
        bust = str(cast.get("bust_emphasis") or "").strip()
        inv_layers = get_inventory_visual_layers(cid)
"""
new_duo = """    girl_parts: list[str] = []
    for i, cid in enumerate(characters):
        cast = (cfg.get("cast") or {}).get(cid, {})
        id_layers = identity_body_layers(cast, cfg, scene=scene_use, explicit=(mode == "explicit"))
        body = (
            str(cast.get("body_tags") or cast.get("tags") or "")
            .replace("1girl, solo,", "1girl,")
            .replace(", solo", "")
        )
        # Prefer weighted body_lock when present
        if id_layers.get("body"):
            body = id_layers["body"]
        bust = str(cast.get("bust_emphasis") or "").strip()
        inv_layers = get_inventory_visual_layers(cid)
"""
if old_duo not in pt:
    raise SystemExit("duo normal block not found")
pt = pt.replace(old_duo, new_duo, 1)

# Prepend identity to girl block assembly if there's a simple join - search next lines
# After inv_layers, blocks usually build with body, bust - inject identity into block join
# Find first occurrence of block assembly in duo non-explicit after our edit
marker = "        if id_layers.get(\"body\"):\n            body = id_layers[\"body\"]\n        bust = str(cast.get(\"bust_emphasis\") or \"\").strip()\n        inv_layers = get_inventory_visual_layers(cid)\n"
idx = pt.find(marker)
if idx < 0:
    raise SystemExit("marker after duo body inject missing")
# Look ahead 40 lines for `block =` 
tail = pt[idx:idx+1200]
# common pattern: block = ", ".join(x for x in [body, bust, ...
import re
m = re.search(r"(\n\s+block = \", \"\.join\(x for x in \[)([^\]]+)(\] if x\))", tail)
if m:
    inner = m.group(2)
    if "id_layers.get" not in inner and "identity" not in inner:
        new_inner = 'id_layers.get("identity", ""), ' + inner + ', id_layers.get("expression", "")'
        tail2 = tail[:m.start()] + m.group(1) + new_inner + m.group(3) + tail[m.end():]
        pt = pt[:idx] + tail2 + pt[idx+1200:]
        print("injected identity into duo block join")
    else:
        print("duo block already has identity")
else:
    print("WARN: could not find duo block join; manual check needed")
    print(tail[:500])

pc.write_text(pt, encoding="utf-8")
import ast
ast.parse(pt)
ast.parse(gen.read_text(encoding="utf-8"))
print("AST OK both files")
print("done")
