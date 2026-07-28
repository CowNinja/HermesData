#!/usr/bin/env python3
"""DEPRECATED landmine ? do NOT launch from this file (2026-07-27).

Historical fit-mode launcher for Qwen2.5-Coder-14B on :8090. It:
  - loads the WRONG model (coder, not Qwythos-9B SSOT)
  - uses batch 1024/512 (Phase3 SSOT is 512/256)
  - omits --kv-offload
  - would clobber the live Phase3 Qwythos tenant

SSOT Phase3 profile: D:\\HermesData\\scripts\\qwythos_8090_profile.json
Canonical start:     D:\\HermesData\\scripts\\start_qwythos_8090_hidden.vbs
Heal path:           python D:\\HermesData\\scripts\\ensure_qwythos_8090.py
Compliance:          python D:\\HermesData\\scripts\\qwythos_phase3_compliance.py --json
                     python D:\\HermesData\\scripts\\qwythos_phase3_compliance.py --enforce

If you need a fit experiment, copy this file under a dated lab name and
point at a NON-8090 port. Never bind production :8090 outside Phase3 VBS.
"""
from __future__ import annotations

import sys

print(
    "REFUSED: launch_8090_fit.py is deprecated (2026-07-27). "
    "Use start_qwythos_8090_hidden.vbs / ensure_qwythos_8090.py / "
    "qwythos_phase3_compliance.py --enforce. See qwythos_8090_profile.json.",
    file=sys.stderr,
)
sys.exit(2)
