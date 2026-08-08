#!/usr/bin/env python3
"""Backup health alarm - measure layers, color, optional Discord pulse.

YELLOW/RED when:
  - vault origin lag ahead > 0 on stable branch (and no clean mirror branch tip)
  - last resilience job ok=False
  - K latest-backup.json age > 48h
  - K mirror age > 48h
  - WhatsApp not considered here (separate)

Default: write receipt + JSON state. --notify attempts local Discord webhook/file pulse
only when color != GREEN (no spam on green).

Usage:
  python D:/HermesData/scripts/backup_health_alarm.py
  python D:/HermesData/scripts/backup_health_alarm.py --json
  python D:/HermesData/scripts/backup_health_alarm.py --notify
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERMES = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")
STATE = HERMES / "state" / "backup_health_last.json"
RECEIPT = VAULT / "Operations" / "logs" / "backup-health-alarm-latest.md"
RESILIENCE = HERMES / "state" / "backup_resilience_last.json"
K_MIRROR_STATE = HERMES / "state" / "backup_k_mirror_last.json"
K_LATEST = Path(r"K:\Hermes-Resilience\manifests\latest-backup.json")
K_MIRROR = Path(r"K:\Hermes-Resilience\mirrors\HermesData-Current")
CLEAN_MIRROR_STATE = HERMES / "state" / "vault_github_clean_mirror_last.json"

K_STALE_HOURS = 48.0
CLEAN_MIRROR_STALE_HOURS = 36.0  # 2x/day target; warn after 36h
CRITICAL_ZIP_STALE_HOURS = 48.0
CRITICAL_ZIP_STATE = HERMES / "state" / "backup_critical_zip_last.json"
SILO_SIGNAL_STATE = HERMES / "state" / "backup_k_silo_life_mirror_last.json"


def run_git(repo: Path, args: List[str], timeout: int = 20) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:
        return f"err {e}"


def age_hours(path: Path) -> Optional[float]:
    if not path.exists():
        return None
    try:
        return (datetime.now().timestamp() - path.stat().st_mtime) / 3600.0
    except Exception:
        return None


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"_parse_error": True}


def origin_ahead(repo: Path, local_branch_hint: str, origin_branch: str) -> Tuple[Optional[int], str]:
    # Prefer comparing origin/<origin_branch>..HEAD
    for ref in (f"origin/{origin_branch}", "origin/HEAD"):
        out = run_git(repo, ["rev-list", "--count", f"{ref}..HEAD"])
        if out.isdigit():
            return int(out), ref
    return None, "n/a"


def evaluate() -> Dict[str, Any]:
    issues: List[str] = []
    warns: List[str] = []
    layers: Dict[str, Any] = {}

    # HermesData github
    hd_ahead, hd_ref = origin_ahead(Path(r"D:\HermesData"), "main", "main")
    layers["hermesdata_github"] = {"ahead": hd_ahead, "ref": hd_ref}
    if hd_ahead is not None and hd_ahead > 0:
        issues.append(f"HermesData ahead of {hd_ref} by {hd_ahead}")
    elif hd_ahead is None:
        warns.append("HermesData origin lag n/a")

    # Vault github lag vs master (post-purge 2026-08-02: poison removed from origin/master)
    v_ahead, v_ref = origin_ahead(VAULT, "master", "master")
    # Explicit master tip lag (not working-tree HEAD which may be overhaul/*)
    master_ahead_out = run_git(VAULT, ["rev-list", "--count", "origin/master..master"])
    master_ahead = int(master_ahead_out) if master_ahead_out.isdigit() else None
    poison_state = load_json(HERMES / "state" / "vault_poison_guard_last.json")
    origin_big = int(poison_state.get("origin_big_count") or 0) if poison_state else None
    layers["vault_github_master"] = {
        "ahead_head": v_ahead,
        "ahead_master_branch": master_ahead,
        "ref": v_ref,
        "origin_big_blobs": origin_big,
        "poison_guard_ok": poison_state.get("ok") if poison_state else None,
    }
    clean = load_json(CLEAN_MIRROR_STATE)
    clean_ok = bool(clean.get("ok")) and bool(clean.get("remote_branch"))
    clean_age = None
    try:
        cts = clean.get("ts") or ""
        if cts:
            cdt = datetime.fromisoformat(cts.replace("Z", "+00:00"))
            clean_age = (datetime.now(timezone.utc) - cdt).total_seconds() / 3600.0
    except Exception:
        clean_age = None
    layers["vault_clean_mirror"] = {
        "ok": clean_ok,
        "branch": clean.get("remote_branch"),
        "ts": clean.get("ts"),
        "age_h": clean_age,
        "source_sha": (clean.get("source_sha") or "")[:12] or None,
        "skipped": clean.get("skipped"),
    }
    # History poison only if origin still has huge blobs
    if origin_big is not None and origin_big > 0:
        if clean_ok:
            warns.append(
                f"origin/master still has {origin_big} >50MB blobs; clean mirror OK ({clean.get('remote_branch')})"
            )
        else:
            issues.append(f"origin/master has {origin_big} >50MB blobs and no clean mirror")
    elif master_ahead is not None and master_ahead > 20:
        warns.append(f"local master ahead of origin/master by {master_ahead} (push/align when ready)")
    if clean_ok and clean_age is not None and clean_age > CLEAN_MIRROR_STALE_HOURS:
        issues.append(
            f"vault clean mirror stale {clean_age:.1f}h > {CLEAN_MIRROR_STALE_HOURS}h"
        )
    elif not clean_ok and not clean:
        warns.append("vault clean mirror never ran")

    # K free-space governor (soft)
    gov = load_json(HERMES / "state" / "k_free_space_governor_last.json")
    layers["k_governor"] = {
        "color": gov.get("color"),
        "free_tb": (gov.get("usage") or {}).get("free_tb"),
        "ok": gov.get("ok"),
    }
    if gov.get("color") == "RED":
        issues.append("K free-space governor RED")
    elif gov.get("color") == "YELLOW":
        warns.append("K free-space governor YELLOW")

    # K capacity trend (rolling free-TB slope + days-to-80%) - soft unless RED
    cap = load_json(HERMES / "state" / "k_capacity_trend_last.json")
    if cap:
        layers["k_capacity_trend"] = {
            "level": cap.get("level") or cap.get("color"),
            "ok": cap.get("ok"),
            "free_tb": (cap.get("usage") or {}).get("free_tb"),
            "used_pct": (cap.get("usage") or {}).get("used_pct"),
            "slope_free_tb_per_day": cap.get("slope_free_tb_per_day"),
            "days_to_80_used_pct": cap.get("days_to_80_used_pct"),
            "samples": cap.get("samples"),
            "reasons": (cap.get("reasons") or [])[:4],
        }
        cap_level = (cap.get("level") or cap.get("color") or "").upper()
        if cap_level == "RED":
            issues.append(
                "K capacity trend RED free_tb=%s days_to_80=%s reasons=%s"
                % (
                    (cap.get("usage") or {}).get("free_tb"),
                    cap.get("days_to_80_used_pct"),
                    ",".join(cap.get("reasons") or [])[:80],
                )
            )
        elif cap_level == "YELLOW":
            warns.append(
                "K capacity trend YELLOW days_to_80=%s slope=%s"
                % (
                    cap.get("days_to_80_used_pct"),
                    cap.get("slope_free_tb_per_day"),
                )
            )

    # Hung-backup watchdog last action (informational; acted=True is healthy)
    hung = load_json(HERMES / "state" / "backup_hung_watchdog_last.json")
    if hung:
        layers["hung_watchdog"] = {
            "ok": hung.get("ok"),
            "acted": hung.get("acted"),
            "action_count": hung.get("action_count"),
            "ts": hung.get("ts"),
        }
        if hung.get("ok") is False:
            warns.append("hung watchdog last run ok=False")

    # Critical zip
    cz = load_json(CRITICAL_ZIP_STATE)
    layers["critical_zip"] = {
        "ok": cz.get("ok"),
        "ts": cz.get("ts"),
        "bytes": cz.get("bytes"),
        "path": cz.get("path"),
    }
    if cz.get("ok"):
        try:
            zts = cz.get("ts") or ""
            if zts:
                zdt = datetime.fromisoformat(zts.replace("Z", "+00:00"))
                zage = (datetime.now(timezone.utc) - zdt).total_seconds() / 3600.0
                layers["critical_zip"]["age_h"] = zage
                if zage > CRITICAL_ZIP_STALE_HOURS:
                    warns.append(f"critical zip stale {zage:.1f}h")
        except Exception:
            pass
    else:
        warns.append("critical zip missing or failed")

    # Silo signal (soft) - partial/budget_hit still ok if dest populated
    ss = load_json(SILO_SIGNAL_STATE)
    layers["silo_signal"] = {
        "ok": ss.get("ok"),
        "ts": ss.get("ts"),
        "copied": ss.get("copied"),
        "partial": ss.get("partial") or ss.get("budget_hit"),
        "dest_files": ss.get("dest_files"),
        "elapsed_sec": ss.get("elapsed_sec"),
        "version": ss.get("version"),
    }
    if ss and ss.get("ok") is False:
        warns.append("silo signal mirror last run failed")
    elif ss.get("budget_hit") or ss.get("partial"):
        # Healthy dest + ok run: budget_hit is expected on multi-TB silo - not a YELLOW.
        dest_n = int(ss.get("dest_files") or 0)
        if dest_n < 100:
            warns.append(
                f"silo signal thin dest after partial: dest_files={dest_n} "
                f"elapsed={ss.get('elapsed_sec')}"
            )
        # else: informational only (layers already carry partial=true)

    # Fossil reappearance (soft unless RED)
    fossil = load_json(HERMES / "state" / "k_fossil_scan_last.json")
    if fossil:
        layers["fossil_scan"] = {
            "color": fossil.get("color"),
            "live_count": fossil.get("live_count"),
            "live_gb": fossil.get("live_gb"),
        }
        if fossil.get("color") == "RED":
            issues.append(f"fossil scan RED live_gb={fossil.get('live_gb')}")
        elif fossil.get("color") == "YELLOW" and (fossil.get("live_count") or 0) > 0:
            warns.append(
                f"fossil scan YELLOW live={fossil.get('live_count')} gb={fossil.get('live_gb')}"
            )

    # Resilience job (v9: hard vs soft_errors; silo timeout soft when prior fresh)
    res = load_json(RESILIENCE)
    soft_errs = list(res.get("soft_errors") or [])
    hard_errs = list(res.get("errors") or [])
    layers["resilience_job"] = {
        "ok": res.get("ok"),
        "ts": res.get("ts"),
        "error_count": res.get("error_count"),
        "soft_error_count": res.get("soft_error_count") or len(soft_errs),
        "errors": hard_errs[:5],
        "soft_errors": soft_errs[:5],
        "version": res.get("version"),
    }
    if res.get("_parse_error"):
        warns.append("resilience state parse error")
    elif not res:
        warns.append("no resilience state yet")
    else:
        # soft errors always warn-only
        for se in soft_errs[:5]:
            warns.append(f"resilience soft: {se[:140]}")
        if res.get("ok") is False or hard_errs:
            errs = " ".join(hard_errs) if hard_errs else " ".join(res.get("errors") or [])
            err_l = errs.lower()
            # silo-only hard label with fresh silo state -> warn
            silo_only = hard_errs and all("silo_signal" in h.lower() for h in hard_errs)
            ss_ok = bool(ss.get("ok")) if ss else False
            if silo_only and ss_ok:
                warns.append(f"resilience silo soft-demoted: {errs[:120]}")
            elif clean_ok and (
                "push" in err_l
                or "vault_clean_mirror" in err_l
                or "master" in err_l
            ) and not any(
                x in err_l for x in ("k_mirror", "critical_zip", "poison", "k_layout")
            ):
                warns.append(f"resilience soft fail (clean mirror OK): {errs[:120]}")
            elif hard_errs or res.get("ok") is False:
                issues.append(f"resilience job ok=False: {errs[:160]}")
        # fossil scan / governor already layered above

    # K manifest age (file mtime of latest-backup.json)
    kh = age_hours(K_LATEST)
    layers["k_manifest_age_h"] = kh
    if kh is None:
        issues.append("K latest-backup.json missing")
    elif kh > K_STALE_HOURS:
        issues.append(f"K manifest stale {kh:.1f}h > {K_STALE_HOURS}h")

    # K mirror age: prefer job receipt ts (Windows directory mtime often frozen)
    kstate = load_json(K_MIRROR_STATE)
    km_dir = age_hours(K_MIRROR)
    km_stamp = age_hours(K_MIRROR / ".mirror-ok")
    km_job = None
    job_ts = kstate.get("ts") or kstate.get("ts_utc") or kstate.get("last_backup")
    if job_ts and kstate.get("ok") is not False:
        try:
            jdt = datetime.fromisoformat(str(job_ts).replace("Z", "+00:00"))
            if jdt.tzinfo is None:
                jdt = jdt.replace(tzinfo=timezone.utc)
            km_job = max(0.0, (datetime.now(timezone.utc) - jdt).total_seconds() / 3600.0)
        except Exception:
            km_job = None
    ages = [a for a in (km_job, km_stamp, km_dir) if a is not None]
    km = min(ages) if ages else None
    layers["k_mirror_age_h"] = km
    layers["k_mirror_age_sources"] = {
        "job_h": km_job,
        "stamp_h": km_stamp,
        "dir_h": km_dir,
    }
    if km is None:
        issues.append("K HermesData-Current mirror missing")
    elif km > K_STALE_HOURS:
        issues.append(f"K HermesData-Current stale {km:.1f}h > {K_STALE_HOURS}h")

    layers["k_mirror_job"] = {
        "ok": kstate.get("ok"),
        "ts": job_ts,
        "errors": (kstate.get("errors") or [])[:5],
        "slices_ok": kstate.get("slices_ok"),
        "slices_total": kstate.get("slices_total"),
    }

    # Cloud recovery
    od = Path.home() / "OneDrive" / "Phronesis-Recovery"
    layers["onedrive_recovery"] = {"exists": od.exists()}
    if not od.exists():
        warns.append("OneDrive Phronesis-Recovery missing")

    if issues:
        color = "RED" if any("missing" in i or "stale" in i for i in issues) else "YELLOW"
        # refine: any issue => YELLOW unless critical missing K
        if any("K " in i and "missing" in i for i in issues):
            color = "RED"
        else:
            color = "YELLOW"
    elif warns:
        color = "YELLOW"
    else:
        color = "GREEN"

    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "color": color,
        "issues": issues,
        "warns": warns,
        "layers": layers,
        "thresholds": {
            "k_stale_hours": K_STALE_HOURS,
            "clean_mirror_stale_hours": CLEAN_MIRROR_STALE_HOURS,
            "critical_zip_stale_hours": CRITICAL_ZIP_STALE_HOURS,
        },
    }


def write_receipt(report: Dict[str, Any]) -> None:
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Backup health alarm - {report['ts']}",
        "",
        f"**Color:** `{report['color']}`",
        "",
        "## Issues",
    ]
    if report["issues"]:
        lines.extend(f"- {i}" for i in report["issues"])
    else:
        lines.append("- (none)")
    lines += ["", "## Warns"]
    if report["warns"]:
        lines.extend(f"- {w}" for w in report["warns"])
    else:
        lines.append("- (none)")
    lines += [
        "",
        "## Layers",
        "```json",
        json.dumps(report["layers"], indent=2)[:4000],
        "```",
        "",
        "[[Operations/Backup-Architecture-Audit-2026-08-01]]",
        "[[Operations/Catastrophe-Restore-and-Backup-Hardening-2026-07-10]]",
        "",
    ]
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(report, indent=2), encoding="utf-8")


def try_notify(report: Dict[str, Any]) -> str:
    """Best-effort local pulse file; does not taskkill gateway or spam if GREEN."""
    if report["color"] == "GREEN":
        return "skip_green"
    pulse_dir = HERMES / "state" / "pulses"
    pulse_dir.mkdir(parents=True, exist_ok=True)
    pulse = pulse_dir / "backup_health_pulse.json"
    pulse.write_text(json.dumps(report, indent=2), encoding="utf-8")
    # Optional: delivery script if present
    deliver = HERMES / "scripts" / "ops" / "discord_local_pulse.py"
    if deliver.exists():
        try:
            r = subprocess.run(
                [
                    sys.executable,
                    str(deliver),
                    "--title",
                    f"Backup {report['color']}",
                    "--body",
                    "; ".join(report["issues"] or report["warns"])[:500],
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return f"deliver_rc={r.returncode}"
        except Exception as e:
            return f"deliver_err={e}"
    return f"pulse_file={pulse}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--notify", action="store_true")
    args = ap.parse_args()
    report = evaluate()
    write_receipt(report)
    notify_msg = try_notify(report) if args.notify else "no_notify"
    report["notify"] = notify_msg
    # refresh state with notify
    STATE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"BACKUP_HEALTH color={report['color']} issues={len(report['issues'])} "
            f"warns={len(report['warns'])} notify={notify_msg}"
        )
        for i in report["issues"]:
            print(f"  ISSUE: {i}")
        for w in report["warns"]:
            print(f"  WARN: {w}")
    return 0 if report["color"] == "GREEN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
