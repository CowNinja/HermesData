#!/usr/bin/env python3
"""Phase 8a SFW gate for T2 offload -- blocks RP/explicit/PII before free compute."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

SCRIPTS = Path(r"D:\HermesData\scripts")
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from proactive_routing_policy import contains_sensitive_content, is_fleet_safe_for_offload, sanitize_for_fleet  # noqa: E402

RP_MARKERS = (
    "alice",
    "roleplay",
    "ooc:",
    "portrait",
    "harem",
    "#alice-roleplay",
    "batch series",
)


def classify_image_offload(prompt: str) -> Dict[str, Any]:
    """Decide if a generic (non-RP) image prompt may use T2 free provider."""
    raw = prompt or ""
    low = raw.lower()

    sensitive, reason = contains_sensitive_content(raw)
    if sensitive:
        return {"allow_t2": False, "reason": reason, "route": "local_comfy_only"}

    for marker in RP_MARKERS:
        if marker in low:
            return {"allow_t2": False, "reason": f"rp_marker:{marker}", "route": "local_comfy_only"}

    sanitized = sanitize_for_fleet(raw)
    safe, safe_reason = is_fleet_safe_for_offload(sanitized)
    if not safe:
        return {"allow_t2": False, "reason": safe_reason, "route": "local_comfy_only"}

    if len(sanitized.strip()) < 12:
        return {"allow_t2": False, "reason": "prompt_too_short", "route": "local_first"}

    return {
        "allow_t2": True,
        "reason": "sfw_generic",
        "route": "t2_image_optional",
        "sanitized_prompt": sanitized,
    }


def main() -> int:
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "landscape mountain sunset"
    result = classify_image_offload(prompt)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())