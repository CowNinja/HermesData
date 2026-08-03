#!/usr/bin/env python3
"""Phase 8a SFW gate for T2 offload -- blocks RP/explicit/PII before free compute.

2026-08-03 upgrades:
  - Block swimsuit/lingerie/skimpy free-path tokens (policy gap close)
  - Allowlist corporate/professional headshot even if word 'portrait' appears
  - Expandable via config/image_route_policy.json free_sfw_gate block
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

SCRIPTS = Path(r"D:\HermesData\scripts")
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from proactive_routing_policy import (  # noqa: E402
    contains_sensitive_content,
    is_fleet_safe_for_offload,
    sanitize_for_fleet,
)

POLICY_PATH = Path(r"D:\HermesData\config\image_route_policy.json")

# RP / identity heat — free cloud never owns these (unless headshot allowlist)
RP_MARKERS = (
    "alice",
    "roleplay",
    "ooc:",
    "harem",
    "#alice-roleplay",
    "batch series",
    "millbrook",
    "just_alice",
)

# Clothing / heat tokens that must stay on local Forge
FREE_PATH_BLOCK_MARKERS = (
    "swimsuit",
    "bikini",
    "lingerie",
    "thong",
    "micro skirt",
    "micro shorts",
    "see-through",
    "sheer",
    "underboob",
    "sideboob",
    "cleavage tease",
    "nipple",
    "topless",
    "bottomless",
    "nude",
    "naked",
    "loincloth",
    "micro tube",
    "bodystocking",
    "bondage",
    "dominatrix",
)

# If prompt matches headshot allowlist, 'portrait' alone is OK
HEADSHOT_ALLOW_RE = re.compile(
    r"\b("
    r"professional\s+headshot|corporate\s+headshot|business\s+headshot|"
    r"linkedin\s+headshot|office\s+headshot|executive\s+portrait|"
    r"corporate\s+portrait|professional\s+portrait|id\s+photo|"
    r"passport\s+photo|staff\s+badge\s+photo"
    r")\b",
    re.I,
)

MODEST_FACE_HINTS = (
    "blazer",
    "blouse",
    "suit",
    "office",
    "corporate",
    "linkedin",
    "business attire",
    "fully clothed",
    "modest",
    "shoulders up",
)


def _load_gate_policy() -> Dict[str, Any]:
    try:
        data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        block = data.get("free_sfw_gate") if isinstance(data, dict) else None
        return block if isinstance(block, dict) else {}
    except Exception:
        return {}


def _extra_markers(key: str) -> List[str]:
    pol = _load_gate_policy()
    raw = pol.get(key) or []
    if not isinstance(raw, list):
        return []
    return [str(x).lower() for x in raw if x]


def classify_image_offload(prompt: str) -> Dict[str, Any]:
    """Decide if a generic (non-RP) image prompt may use T2 free provider."""
    raw = prompt or ""
    low = raw.lower()

    sensitive, reason = contains_sensitive_content(raw)
    if sensitive:
        return {"allow_t2": False, "reason": reason, "route": "local_comfy_only"}

    # Clothing / edge heat blocked on free path
    for marker in list(FREE_PATH_BLOCK_MARKERS) + _extra_markers("block_markers_extra"):
        if marker and marker in low:
            return {
                "allow_t2": False,
                "reason": f"free_block:{marker}",
                "route": "local_comfy_only",
            }

    headshot_ok = bool(HEADSHOT_ALLOW_RE.search(raw)) or (
        "headshot" in low and any(h in low for h in MODEST_FACE_HINTS)
    )

    # RP markers (portrait is special-cased)
    for marker in list(RP_MARKERS) + _extra_markers("rp_markers_extra"):
        if marker and marker in low:
            return {
                "allow_t2": False,
                "reason": f"rp_marker:{marker}",
                "route": "local_comfy_only",
            }

    if "portrait" in low and not headshot_ok:
        return {
            "allow_t2": False,
            "reason": "rp_marker:portrait",
            "route": "local_comfy_only",
            "hint": "use 'professional headshot' + blazer/office for free path",
        }

    sanitized = sanitize_for_fleet(raw)
    safe, safe_reason = is_fleet_safe_for_offload(sanitized)
    if not safe:
        return {"allow_t2": False, "reason": safe_reason, "route": "local_comfy_only"}

    if len(sanitized.strip()) < 12:
        return {"allow_t2": False, "reason": "prompt_too_short", "route": "local_first"}

    out: Dict[str, Any] = {
        "allow_t2": True,
        "reason": "sfw_generic" if not headshot_ok else "sfw_headshot_allowlist",
        "route": "t2_image_optional",
        "sanitized_prompt": sanitized,
    }
    if headshot_ok:
        out["headshot_allowlist"] = True
    return out


def main() -> int:
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "landscape mountain sunset"
    result = classify_image_offload(prompt)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
