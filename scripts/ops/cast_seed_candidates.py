#!/usr/bin/env python3
"""Generate N portrait candidates for a cast slug with explicit seeds (no lock)."""
from __future__ import annotations
import json, subprocess, sys, time
from pathlib import Path

RENDER = Path(r"D:\PhronesisVault\Roleplay-Sandbox\sandbox\render-roleplay-image.py")
PY = Path(r"D:\HermesData\hermes-agent\venv\Scripts\python.exe")
if not PY.is_file():
    PY = Path(sys.executable)

def main() -> int:
    if len(sys.argv) < 3:
        print("usage: cast_seed_candidates.py <slug> <seed1,seed2,...> [out.json]")
        return 2
    slug = sys.argv[1]
    seeds = [int(x) for x in sys.argv[2].split(",") if x.strip()]
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(rf"D:\HermesData\state\{slug}-seed-candidates.json")
    results = []
    print(f"{slug} candidates: {seeds}", flush=True)
    for i, seed in enumerate(seeds, 1):
        print(f"\n=== [{i}/{len(seeds)}] seed={seed} ===", flush=True)
        nude = (
            "completely nude, fully naked, bare skin only, exposed nipples, exposed areola, "
            "exposed pussy, visible labia, uncensored, no clothing, no fabric, bare feet, "
            "100 percent nude"
        )
        cmd = [str(PY), str(RENDER), "--character", slug, "--mode", "portrait",
               "--fresh", "--seed", str(seed), "--json", "--standard", "--skip-lock",
               "--outfit", nude, "--scene", nude]
        t0 = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        elapsed = time.time() - t0
        print(f"rc={proc.returncode} elapsed={elapsed:.1f}s", flush=True)
        if proc.stderr:
            print("STDERR:", proc.stderr[-600:], flush=True)
        out_s = (proc.stdout or "").strip()
        if out_s:
            print("STDOUT tail:", out_s[-400:], flush=True)
        data = None
        for line in reversed(out_s.splitlines()):
            line = line.strip()
            if line.startswith("{") and "success" in line:
                try:
                    data = json.loads(line); break
                except json.JSONDecodeError:
                    pass
        if not data or not data.get("success"):
            results.append({"index": i, "ok": False, "requested_seed": seed, "rc": proc.returncode,
                            "stderr_tail": (proc.stderr or "")[-300:], "stdout_tail": out_s[-300:]})
            continue
        path = data.get("gallery_image") or data.get("image")
        results.append({"index": i, "ok": True, "requested_seed": seed, "seed": data.get("seed", seed),
                        "image": path, "elapsed_s": round(elapsed, 1)})
        print(f"OK seed={data.get('seed', seed)} path={path}", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"character": slug, "results": results}, indent=2), encoding="utf-8")
    ok = sum(1 for r in results if r.get("ok"))
    print(f"\nWROTE {out}\nSUCCESS {ok}/{len(seeds)}", flush=True)
    return 0 if ok == len(seeds) else 1

if __name__ == "__main__":
    raise SystemExit(main())
