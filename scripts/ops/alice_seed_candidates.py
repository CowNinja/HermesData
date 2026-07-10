#!/usr/bin/env python3
"""Generate N Alice portrait candidates with different seeds (no lock)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

RENDER = Path(r"D:\PhronesisVault\Roleplay-Sandbox\sandbox\render-roleplay-image.py")
OUT = Path(r"D:\HermesData\state\alice-seed-candidates-round3.json")
PY = Path(r"D:\HermesData\hermes-agent\venv\Scripts\python.exe")
if not PY.is_file():
    PY = Path(sys.executable)

# Four review seeds for Alice (distinct face lottery tickets)
SEEDS = [9119119119, 9229229229, 9339339339, 9449449449]


def main() -> int:
    count = len(SEEDS)
    results = []
    OUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"Alice candidates: {count} seeds = {SEEDS}", flush=True)

    for i, seed in enumerate(SEEDS, 1):
        print(f"\n=== [{i}/{count}] seed={seed} ===", flush=True)
        cmd = [
            str(PY),
            str(RENDER),
            "--character",
            "alice-al-rashid",
            "--mode",
            "portrait",
            "--fresh",
            "--seed",
            str(seed),
            "--json",
            "--standard",
            "--skip-lock",
        ]
        t0 = time.time()
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        elapsed = time.time() - t0
        print(f"rc={proc.returncode} elapsed={elapsed:.1f}s", flush=True)
        if proc.stderr:
            print("STDERR:", proc.stderr[-1000:], flush=True)
        out = (proc.stdout or "").strip()
        if out:
            print("STDOUT tail:", out[-600:], flush=True)
        data = None
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{") and "success" in line:
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        if not data or not data.get("success"):
            results.append(
                {
                    "index": i,
                    "ok": False,
                    "requested_seed": seed,
                    "stderr_tail": (proc.stderr or "")[-400:],
                    "stdout_tail": out[-400:],
                    "rc": proc.returncode,
                }
            )
            continue
        path = data.get("gallery_image") or data.get("image")
        results.append(
            {
                "index": i,
                "ok": True,
                "requested_seed": seed,
                "seed": data.get("seed", seed),
                "image": path,
                "gallery_image": data.get("gallery_image"),
                "vault_image": data.get("image"),
                "elapsed_s": round(elapsed, 1),
            }
        )
        print(f"OK seed={data.get('seed', seed)} path={path}", flush=True)

    payload = {"character": "alice-al-rashid", "count": count, "results": results}
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("\nWROTE", OUT, flush=True)
    ok_n = sum(1 for r in results if r.get("ok") and r.get("image"))
    print(f"SUCCESS {ok_n}/{count}", flush=True)
    return 0 if ok_n == count else 1


if __name__ == "__main__":
    raise SystemExit(main())
