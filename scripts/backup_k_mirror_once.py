#!/usr/bin/env python3
"""K: Hermes-Resilience local mirror once (time-boxed).

v2 notes (2026-08-01):
  - hermes backup --quick currently HANGS on this host (45s+ no zip) — default SKIP.
  - Use --with-hermes-quick only after hermes CLI is fixed; still hard-killed on timeout.
  - Selective robocopy only (never MIR whole HermesData — old mirror has 195GB+ fossils).
  - Refreshes K:/Hermes-Resilience/manifests/latest-backup.json for health alarm age.

Usage:
  python D:/HermesData/scripts/backup_k_mirror_once.py
  python D:/HermesData/scripts/backup_k_mirror_once.py --with-hermes-quick
  python D:/HermesData/scripts/backup_k_mirror_once.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERMES = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")
K_ROOT = Path(r"K:\Hermes-Resilience")
K_MIRROR = K_ROOT / "mirrors" / "HermesData-Current"
K_VAULT_MIRROR = K_ROOT / "mirrors" / "PhronesisVault-Critical"
K_BACKUPS = K_ROOT / "backups" / "hermes"
K_MANIFESTS = K_ROOT / "manifests"
K_LOGS = K_ROOT / "logs"
STATE = HERMES / "state" / "backup_k_mirror_last.json"

# Keep lean — exclude media/venvs/caches/node_modules
ROBO_XD = [
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "ComfyUI",
    "models",
    "output",
    "outputs",
    "Backups",
    "tmp",
    "cache",
    ".cache",
    "PackageCache",
    "whatsapp",
    "audio_cache",
    "benchmark-results",
    "lsp",
    "agent-tools",
]

# Critical slices only (not full HermesData MIR)
HERMES_SLICES = [
    (HERMES / "scripts", K_MIRROR / "scripts"),
    (HERMES / "config", K_MIRROR / "config"),
    (HERMES / "cron", K_MIRROR / "cron"),
    (HERMES / "memories", K_MIRROR / "memories"),
    (HERMES / "skills", K_MIRROR / "skills"),
    (HERMES / "plugins", K_MIRROR / "plugins"),
]

VAULT_SLICES = [
    (VAULT / "Operations", K_VAULT_MIRROR / "Operations"),
    (VAULT / "Resilience", K_VAULT_MIRROR / "Resilience"),
    (VAULT / "Housekeeping.md", K_VAULT_MIRROR / "Housekeeping.md"),
]

# Extra XD for vault Operations only (bulk runtime noise)
VAULT_OPS_XD = [
    "logs",
    "backups",
    "diagnostics",
    "asar-patch-tmp",
    "asar-check-tmp",
    "app-asar-extract",
    "node_modules",
    ".git",
]

# Never mirror secrets
XF = ["*.sqlite", "*.sqlite-wal", "*.sqlite-shm", ".env", ".env.*", "auth.json", "*.pem", "*.key"]


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: List[str], timeout: int = 120, cwd: Path | None = None) -> Tuple[int, str, str]:
    try:
        # Windows: kill process tree on timeout via job? use creationflags + kill
        kwargs: Dict[str, Any] = dict(
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
        )
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        r = subprocess.run(cmd, **kwargs)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired as e:
        # best-effort kill
        try:
            if e.process:
                e.process.kill()
        except Exception:
            pass
        return 124, "", f"timeout after {timeout}s"
    except FileNotFoundError as e:
        return 127, "", str(e)
    except Exception as e:
        return 1, "", str(e)


def robocopy(
    src: Path,
    dst: Path,
    timeout: int = 300,
    dry: bool = False,
    extra_xd: List[str] | None = None,
) -> Dict[str, Any]:
    if not src.exists():
        return {"src": str(src), "ok": False, "rc": 2, "error": "missing_src"}
    if src.is_file():
        if dry:
            return {"src": str(src), "ok": True, "dry_run": True, "mode": "file"}
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dst)
            return {"src": str(src), "ok": True, "mode": "file"}
        except Exception as e:
            return {"src": str(src), "ok": False, "error": str(e)[:200]}

    dst.mkdir(parents=True, exist_ok=True)
    cmd = [
        "robocopy",
        str(src),
        str(dst),
        "/E",
        "/XO",
        "/R:1",
        "/W:1",
        "/NFL",
        "/NDL",
        "/NP",
        "/MT:8",
    ]
    xd = list(ROBO_XD) + list(extra_xd or [])
    for d in xd:
        cmd.extend(["/XD", d])
    for f in XF:
        cmd.extend(["/XF", f])
    if dry:
        cmd.append("/L")
    code, out, err = run(cmd, timeout=timeout)
    # robocopy 0-7 = success-ish
    ok = code < 8
    return {
        "src": str(src),
        "dst": str(dst),
        "ok": ok,
        "rc": code,
        "err": (err or out)[-300:] if not ok else "",
        "dry_run": dry,
    }


def hermes_quick(timeout: int = 60) -> Dict[str, Any]:
    """Optional. Known hang on 2026-08-01 — keep timeout low."""
    K_BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # write to D: first (K: large fossil zips nearby can stress explorer)
    local = HERMES / "tmp" / f"quick-{stamp}.zip"
    local.parent.mkdir(parents=True, exist_ok=True)
    dest = K_BACKUPS / f"quick-{stamp}.zip"
    hermes = shutil.which("hermes") or r"C:\Program Files\Python313\Scripts\hermes.exe"
    if not Path(hermes).exists() and not shutil.which("hermes"):
        return {"ok": False, "error": "hermes_cli_missing", "skipped": True}
    cmd = [hermes, "backup", "--quick", "-o", str(local), "-l", f"k-mirror-{stamp}"]
    code, out, err = run(cmd, timeout=timeout)
    if code == 124:
        return {"ok": False, "error": "hermes_quick_timeout", "timeout_s": timeout, "skipped": True}
    if code != 0 or not local.exists():
        return {"ok": False, "error": (err or out or f"rc={code}")[:240], "skipped": True}
    try:
        shutil.copy2(local, dest)
        try:
            local.unlink()
        except OSError:
            pass
        return {"ok": True, "path": str(dest), "bytes": dest.stat().st_size}
    except Exception as e:
        return {"ok": False, "error": f"copy_to_k: {e}"[:200], "local": str(local)}


def write_manifest(results: Dict[str, Any]) -> Path:
    K_MANIFESTS.mkdir(parents=True, exist_ok=True)
    K_LOGS.mkdir(parents=True, exist_ok=True)
    path = K_MANIFESTS / "latest-backup.json"
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    # append short log line
    line = (
        f"{results.get('ts')} ok={results.get('ok')} "
        f"hermes_quick={results.get('hermes_quick', {}).get('ok')} "
        f"slices_ok={results.get('slices_ok')}/{results.get('slices_total')}\n"
    )
    with (K_LOGS / "k-mirror.log").open("a", encoding="utf-8") as fh:
        fh.write(line)
    # keep a small living note
    note = K_ROOT / "phronesis-resilience.md"
    if not note.exists():
        note.write_text(
            "# Phronesis Resilience (K:)\n\n"
            "Updated by `backup_k_mirror_once.py`.\n"
            "GitHub clean vault branch: `github-cns-mirror`.\n"
            "Full vault history rewrite is Jeff-gated.\n",
            encoding="utf-8",
        )
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--with-hermes-quick", action="store_true",
                    help="Attempt hermes backup --quick (may hang; 60s kill)")
    ap.add_argument("--hermes-timeout", type=int, default=60)
    ap.add_argument("--slice-timeout", type=int, default=240)
    args = ap.parse_args()

    ts = datetime.now(timezone.utc).isoformat()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log(f"## backup_k_mirror_once v2 {stamp}")

    if not K_ROOT.exists():
        err = {"ts": ts, "ok": False, "errors": ["K:/Hermes-Resilience missing"]}
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(err, indent=2), encoding="utf-8")
        log("FAIL K: root missing")
        return 2

    errors: List[str] = []
    slice_results: List[Dict[str, Any]] = []

    hq: Dict[str, Any]
    if args.with_hermes_quick:
        log(f"## hermes backup --quick (timeout {args.hermes_timeout}s)")
        hq = hermes_quick(timeout=args.hermes_timeout)
        if not hq.get("ok"):
            errors.append(f"hermes_quick: {hq.get('error')}")
            log(f"WARN hermes_quick failed (non-fatal): {hq.get('error')}")
        else:
            log(f"OK hermes_quick {hq.get('path')}")
    else:
        hq = {"ok": None, "skipped": True, "reason": "default_skip_hanging_hermes_quick"}
        log("## hermes quick SKIPPED (default; pass --with-hermes-quick to try)")

    log("## robocopy Hermes slices")
    for src, dst in HERMES_SLICES:
        r = robocopy(src, dst, timeout=args.slice_timeout, dry=args.dry_run)
        slice_results.append(r)
        flag = "OK" if r.get("ok") else "FAIL"
        log(f"  {flag} {src.name} rc={r.get('rc')}")
        if not r.get("ok"):
            errors.append(f"hermes_slice {src}: {r.get('error') or r.get('err') or r.get('rc')}")

    log("## robocopy Vault critical slices")
    for src, dst in VAULT_SLICES:
        extra = VAULT_OPS_XD if src.name == "Operations" else None
        r = robocopy(src, dst, timeout=args.slice_timeout, dry=args.dry_run, extra_xd=extra)
        slice_results.append(r)
        flag = "OK" if r.get("ok") else "FAIL"
        log(f"  {flag} {src.name} rc={r.get('rc')}")
        if not r.get("ok"):
            errors.append(f"vault_slice {src}: {r.get('error') or r.get('err') or r.get('rc')}")

    # Drop root markers (no secrets)
    if not args.dry_run:
        K_MIRROR.mkdir(parents=True, exist_ok=True)
        for name in ("SOUL.md", "AGENTS.md", "config.yaml"):
            src = HERMES / name
            if src.exists():
                try:
                    shutil.copy2(src, K_MIRROR / name)
                except Exception as e:
                    errors.append(f"copy {name}: {e}")

    slices_ok = sum(1 for r in slice_results if r.get("ok"))
    # ok if majority of slices ok; hermes quick optional
    ok = slices_ok >= max(1, len(slice_results) - 1) and slices_ok > 0

    result = {
        "ts": ts,
        "ok": ok and not args.dry_run,
        "dry_run": args.dry_run,
        "version": 2,
        "hermes_quick": hq,
        "slices_ok": slices_ok,
        "slices_total": len(slice_results),
        "slices": slice_results,
        "errors": errors[:30],
        "k_root": str(K_ROOT),
        "note": "selective slices; hermes --quick default skip due to hang 2026-08-01",
    }

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not args.dry_run:
        man = write_manifest(result)
        log(f"OK manifest {man}")
    log(f"DONE ok={result['ok']} slices={slices_ok}/{len(slice_results)} errors={len(errors)}")
    print(json.dumps({"ok": result["ok"], "slices_ok": slices_ok, "errors": errors[:8]}, indent=2))
    return 0 if result["ok"] or args.dry_run else 1


if __name__ == "__main__":
    raise SystemExit(main())
