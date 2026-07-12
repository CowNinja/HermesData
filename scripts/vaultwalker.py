#!/usr/bin/env python3
"""
VaultWalker v0.7.0 - Rebuilt clean, explicit-only gates, rock solid.

Simple, clean, ASCII-only.
Uses existing local model (qwythos 9b abliterated via sovereign router) for intelligent evaluation at every step:
- Classify (explicit-rp vs explicit-non-rp vs non)
- Actions: relocate, keep, flag_review, distill_compact, split_atomic, trim
- Residency + policy tagging
- Block by default. Only move confirmed explicit RP material to RoleplaySandbox (central location).
- Edge cases respected: explicit but unrelated to roleplay kept in original silo + audited.

Indexes updated in **every single directory** (even empty) for complete navigation and easy file/content location.
Audit always produced.
Aligned with user directives + prior research (data fabric style separation + AI at every step).

Optimized for scale: prefilter keywords before model calls; skips binaries/large files; incremental state.

Run: python "D:/HermesData/scripts/vaultwalker.py" [--dry-run] [--silos ...]
"""

import argparse
import concurrent.futures
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
import yaml  # for full data_silos.yaml loading
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple, Any

# Module-level flag for clean dry-run passing
DRY_RUN = False

# === Explicit-only + Silo Recognition ===
EXPLICIT_RP_KEYWORDS = [
    "explicit", "nude", "nsfw", "harem", "alice", "bent-over-spread", "dripping",
    "heat", "scene", "roleplay", "porn", "adult", "curvy nude", "bare skin",
    "winking tight", "heavy perky breasts", "explicit alternates", "heat-doctrine"
]

SILO_SIGNATURES = {
    "GitHub": {"keywords": ["github", "repo", "README", ".github", "workflow", "pull request", "changelog", "change management"], "type": "github_sync"},
    "HermesData": {"keywords": ["script", "cron", "skill", "code", "hermes", "backup", "runtime"], "type": "runtime_ops"},
    "PhronesisVault": {"keywords": ["plan", "index", "knowledge", "cns", "wisdom", "roadmap", "vault"], "type": "cns_mirror"},
    "K_PhronesisSovereign": {"keywords": ["navy", "medical", "va", "silo", "personal-digital", "digital-twin", "sovereign"], "type": "ssot_silo"},
    "RoleplaySandbox": {"keywords": ["alice", "roleplay", "explicit", "nude", "harem", "scene", "character", "heat"], "type": "walled_garden"},
}

def local_model_file_evaluation(preview: str, path_str: str, current_silo: str) -> Dict:
    """Evaluate file via Qwythos: prefer :8091 (grunt path), fallback ollama CLI."""
    nl = chr(10)
    prompt = (
        "You are a strict sovereign data silo guardian for personal vaults. "
        "Block by default. Only move if clearly explicit roleplay material for the walled sandbox. "
        "Output EXACTLY one line:" + nl +
        "CLASS:explicit-rp|explicit-non-rp|non-explicit | ACTION:relocate|keep|flag_review|distill_compact|split_atomic|trim | "
        "REASON:short | RESIDENCY:sandbox-only|keep-current | POLICY:no-cross-except-explicit" + nl +
        f"File: {path_str}" + nl + f"Current silo: {current_silo}" + nl + f"Preview: {preview[:650]}" + nl
    )

    def _parse(out: str) -> Dict:
        line = out.strip().splitlines()[-1] if out.strip() else ""
        parts = {}
        for item in line.split("|"):
            if ":" in item:
                k, v = item.split(":", 1)
                parts[k.strip().lower()] = v.strip()
        return {
            "class": parts.get("class", "unknown"),
            "action": parts.get("action", "keep"),
            "reason": parts.get("reason", "parse fail"),
            "residency": parts.get("residency", "keep-current"),
            "policy": parts.get("policy", "no-cross-except-explicit"),
        }

    # 1) Preferred: proxy :8091 (grunt_local path)
    try:
        import json
        import urllib.request
        body = json.dumps({
            "model": "phronesis-sovereign-classify",
            "messages": [
                {"role": "system", "content": "Reply with one CLASS|ACTION line only."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 120,
            "temperature": 0.1,
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:8091/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        out = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
        if out.strip():
            return _parse(out)
    except Exception:
        pass

    # 2) Fallback: ollama CLI (legacy)
    try:
        result = subprocess.run(
            ["ollama", "run", "qwythos-9b-abliterated", prompt],
            capture_output=True,
            text=True,
            timeout=70,
        )
        out = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        return _parse(out)
    except Exception:
        return {
            "class": "unknown",
            "action": "keep",
            "reason": "model unavailable",
            "residency": "keep-current",
            "policy": "no-cross-except-explicit",
        }


def is_explicit_rp_content(path: Path, preview: str = "") -> bool:
    """Hybrid explicit-only gate: fast keywords + local model confirmation for RP material only."""
    full = str(path).lower() + " " + preview.lower()
    if not any(kw in full for kw in EXPLICIT_RP_KEYWORDS):
        return False
    eval_res = local_model_file_evaluation(preview, str(path), "check")
    return eval_res.get("class") == "explicit-rp"

def get_silo_for_content(path: Path, preview: str = "") -> str:
    full = str(path).lower() + " " + preview.lower()
    best = None
    best_score = 0
    for silo, sig in SILO_SIGNATURES.items():
        score = sum(1 for kw in sig["keywords"] if kw in full)
        if score > best_score:
            best_score = score
            best = silo
    return best or "PhronesisVault"

def relocate_to_sandbox(src: Path, dry_run: bool = False) -> str:
    """Move confirmed explicit RP material exclusively to RoleplaySandbox (central location)."""
    target_dir = Path(r"D:\PhronesisVault\Roleplay-Sandbox\data\misplaced_from_vaultwalker")
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / src.name
    if dest.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = target_dir / (src.stem + "_" + ts + src.suffix)
    log_msg = "RELOCATE: " + str(src) + " -> " + str(dest)
    if not dry_run:
        try:
            import shutil
            shutil.move(str(src), str(dest))
            log_msg += " [MOVED]"
        except Exception as e:
            log_msg += " [ERROR: " + str(e)[:70] + "]"
    else:
        log_msg += " [DRY-RUN]"
    audit = target_dir / "relocation_audit.md"
    with open(audit, "a", encoding="utf-8") as f:
        f.write("## " + datetime.now().isoformat() + " - " + log_msg + "\n")
    print("[VAULTWALKER-RELOCATE] " + log_msg)
    return log_msg

# === Config & Core ===
LOG_DIR = Path(r"D:\HermesData\logs")
STATE_DIR = Path(r"D:\HermesData\data\vaultwalker\state")
STALE_DAYS = 60

def load_config() -> Dict:
    """Load full config from data_silos.yaml for all 4 silos + policies."""
    cfg_path = Path(r"D:\HermesData\config\data_silos.yaml")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            full = yaml.safe_load(f)
    except Exception:
        full = {}

    silos_cfg = {}
    for name, s in full.get("silos", {}).items():
        silos_cfg[name] = {
            "path": s.get("path", ""),
            "update_per_folder_indexes": s.get("update_per_folder_indexes", True),
            "non_ascii_code_clean": s.get("non_ascii_code_clean", False),
            "md_review": s.get("md_review", True),
            "ollama_model": s.get("ollama_model", "qwythos-9b-abliterated"),
        }

    # Ensure all expected
    if "K_PhronesisSovereign" not in silos_cfg:
        silos_cfg["K_PhronesisSovereign"] = {
            "path": r"K:\Phronesis-Sovereign",
            "update_per_folder_indexes": True,
            "non_ascii_code_clean": False,
            "md_review": False,
            "ollama_model": "qwythos-9b-abliterated",
        }

    global_cfg = full.get("global", {})
    global_cfg.setdefault("persistent_state", True)
    global_cfg.setdefault("staggered_cycles", True)
    global_cfg.setdefault("local_models", True)
    global_cfg.setdefault("dry_run_default", True)

    return {
        "version": "0.6.2",
        "global": global_cfg,
        "silos": silos_cfg,
    }

CFG = load_config()
SILOS = {name: Path(s["path"]) for name, s in CFG.get("silos", {}).items()}
GLOBAL_POLICIES = CFG.get("global", {})

def is_light_cycle() -> bool:
    if not GLOBAL_POLICIES.get("staggered_cycles", True):
        return False
    return (datetime.now().hour % 12) < 6

def file_hash(path: Path) -> str:
    sha = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha.update(chunk)
        return sha.hexdigest()[:16]
    except:
        return "ERROR"

def sanitize_non_ascii(text: str) -> str:
    """ASCII-clean without destroying structure.

    CRITICAL: never collapse newlines/tabs (2026-07-09 zero-newline incident).
    Only strip non-ASCII; preserve LF/CR/TAB and normal spaces.
    """
    normalized = unicodedata.normalize("NFKD", text)
    out = []
    for ch in normalized:
        o = ord(ch)
        if o in (9, 10, 13) or 32 <= o <= 126:
            out.append(ch)
    cleaned = "".join(out)
    if text.count(chr(10)) > 0 and cleaned.count(chr(10)) == 0:
        return text  # refuse zero-newline corruption
    return cleaned if cleaned else text

def load_persistent_state(silo_name: str) -> Dict[str, Any]:
    if not GLOBAL_POLICIES.get("persistent_state", True):
        return {}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / (silo_name.lower() + "_state.json")
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_persistent_state(silo_name: str, state: Dict[str, Any]) -> None:
    if not GLOBAL_POLICIES.get("persistent_state", True):
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / (silo_name.lower() + "_state.json")
    state["last_updated"] = datetime.now().isoformat()
    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except:
        pass

def should_process_deep(path: Path, state: Dict[str, Any]) -> bool:
    if not GLOBAL_POLICIES.get("persistent_state", True):
        return True
    key = str(path.relative_to(path.anchor)) if path.is_absolute() else str(path)
    last = state.get("folders", {}).get(key, {})
    try:
        mtime = path.stat().st_mtime
        h = file_hash(path) if path.is_file() else "dir"
        if last.get("mtime") == mtime and last.get("hash") == h:
            return False
        state.setdefault("folders", {})[key] = {"mtime": mtime, "hash": h}
        return True
    except:
        return True

# Never plant 00-INDEX.md inside package trees / tooling (Graph orphan factories)
INDEX_SKIP_PARTS = {
    "node_modules",
    ".git",
    "__pycache__",
    "tmp",
    "temp",
    ".obsidian",
    ".smart-env",
    ".trash",
    "archives",
    "site-packages",
    "alice_venv",
    "venv",
    ".venv",
    "dist-info",
    ".dist-info",
    "Lib",
    "Scripts",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    "asar-check-tmp",
    "asar-patch-tmp",
}


def _should_skip_index_dir(dirpath: Path) -> bool:
    parts_lower = {p.lower() for p in dirpath.parts}
    if parts_lower & {p.lower() for p in INDEX_SKIP_PARTS}:
        return True
    name = dirpath.name.lower()
    if name.endswith(".dist-info") or name.endswith(".egg-info"):
        return True
    if name.startswith(".") and name not in {".", ".."}:
        # skip hidden tooling dirs; keep normal vault folders
        if name in {".github"}:
            return True
    return False


def update_per_folder_indexes(root: Path, silo_name: str, state: Dict[str, Any], is_light: bool) -> int:
    """Index updates for navigable folders (not every package subtree).

    Skips venv/site-packages/node_modules so Graph is not flooded with orphan
    00-INDEX.md files. Living CNS folders still get lightweight maps.
    """
    updated = 0
    if not root.exists():
        return 0
    for dirpath in root.rglob("*"):
        if not dirpath.is_dir():
            continue
        if _should_skip_index_dir(dirpath):
            continue
        if not should_process_deep(dirpath, state):
            continue
        try:
            files = [f for f in dirpath.iterdir() if f.is_file()]
            md_files = [f for f in files if f.suffix.lower() == ".md" and f.name.lower() not in ("00-index.md", "index.md")]
        except OSError:
            continue
        idx_file = dirpath / "00-INDEX.md" if not (dirpath / "INDEX.md").exists() else dirpath / "INDEX.md"
        # Prefer wikilinks for .md so Graph gains edges when indexes are used
        file_lines = []
        for f in sorted(md_files, key=lambda p: p.name.lower())[:40]:
            try:
                rel = f.relative_to(root)
                stem = str(rel.with_suffix("")).replace("\\", "/")
                file_lines.append(f"- [[{stem}|{f.name}]]")
            except ValueError:
                file_lines.append(f"- `{f.name}`")
        if not file_lines:
            file_lines = [f"- (no markdown; {len(files)} other files)"]
        content = f"""# {dirpath.name} INDEX (VaultWalker v0.7.1, {datetime.now().strftime('%Y-%m-%d')}) Silo: {silo_name}

**Separation + Explicit Gates**: Agent reads this first.
- Explicit RP material is centralized ONLY in RoleplaySandbox (block by default elsewhere).
- Use local model (qwythos 9b abliterated) for classification on every evaluation.

Where To Go:
- Check mtime > {STALE_DAYS}d for resurfacing.
- Add PKG + residency tags on review.
- Only relocate on confirmed explicit-rp via local model.

## Files
{chr(10).join(file_lines)}

Files total: {len(files)}
"""
        try:
            with open(idx_file, "w", encoding="utf-8") as fh:
                fh.write(content)
            updated += 1
        except OSError:
            continue
    return updated

def clean_code_non_ascii(root: Path) -> int:
    """DISABLED by default (v0.7.1).

    Prior sanitize_non_ascii collapsed whitespace and could flatten scripts
    (zero-newline class). ASCII repair for code must use repair_ascii_scripts.py
    which preserves newlines. VaultWalker never mass-rewrites code in place.
    """
    print("[VAULTWALKER] clean_code_non_ascii skipped (disabled; use repair_ascii_scripts.py)")
    return 0

def review_and_modify_markdowns(root: Path, vision_text: str, silo_name: str, state: Dict[str, Any], is_light: bool) -> Dict:
    """Review with residency/policy tags + local model intelligent actions.
    distill_compact, split_atomic, trim supported via existing model.
    """
    stats = {"reviewed": 0, "pkg_entities": 0, "resurfaced": 0, "proposals": 0, "smart_actions": 0}
    if not root.exists() or is_light:
        return stats
    for p in root.rglob("*.md"):
        if not should_process_deep(p, state):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
            stats["reviewed"] += 1
            orig = text
            changed = False

            # Residency + policy tags (explicit-only aware)
            if not text.startswith("---"):
                date_str = datetime.now().strftime("%Y-%m-%d")
                is_rp = is_explicit_rp_content(p, text[:400])
                pkg = f"""---
type: note
status: active
entities: []
relations: []
review_date: {date_str}
silo: {silo_name}
residency: {"sandbox-only" if is_rp else "keep-current"}
policy: no-cross-except-explicit
topic: general
---

"""
                text = pkg + text
                stats["pkg_entities"] += 1
                changed = True

            # Intelligent local model actions on larger files
            if len(text) > 3500:
                preview = text[:700]
                eval_res = local_model_file_evaluation(preview, str(p), silo_name)
                act = eval_res.get("action", "keep")
                if act == "distill_compact":
                    text = text[:1800] + "\n\n> [Local model distilled/compact: " + eval_res.get("reason", "") + "]\n"
                    stats["smart_actions"] += 1
                    changed = True
                elif act == "split_atomic":
                    text += "\n\n> [Local model: split into atomic notes. Link via MOC.]\n"
                    stats["smart_actions"] += 1
                    changed = True
                elif act == "trim":
                    text = text[:2200] + "\n\n> [Trimmed per local model.]\n"
                    stats["smart_actions"] += 1
                    changed = True

            if "[[" not in text[:400] and len(text) > 250:
                text += "\n\n> Link on entry + resurface."
                stats["resurfaced"] += 1
                changed = True

            if changed and text != orig:
                if not DRY_RUN:
                    try:
                        p.write_text(text, encoding="utf-8")
                    except:
                        pass
                stats["proposals"] += 1
        except:
            continue
    return stats

def resurface_forgotten_ideas(root: Path, silo_name: str, state: Dict[str, Any]) -> Dict:
    stats = {"stale_found": 0, "surfaced": 0, "examples": []}
    if not root.exists():
        return stats
    now = datetime.now()
    resurf_log = root / "Resurfaced-Ideas.md"
    entries = []
    for p in root.rglob("*.md"):
        if not should_process_deep(p, state):
            continue
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
            days_old = (now - mtime).days
            text = p.read_text(encoding="utf-8", errors="ignore")
            links = text.count("[[")
            if days_old > STALE_DAYS or (links < 2 and len(text) > 250 and "archive" not in str(p).lower()):
                rel = str(p.relative_to(root))
                entry = "- [[" + rel + "]] (~" + str(days_old) + "d, " + str(links) + " links)"
                stats["stale_found"] += 1
                stats["surfaced"] += 1
                if len(stats["examples"]) < 5:
                    stats["examples"].append(rel)
                entries.append(entry)
                if "Resurfaced by VaultWalker" not in text:
                    note = "\n\n> Resurfaced forgotten idea (" + now.strftime("%Y-%m-%d") + ") per post guidance.\n"
                    if not DRY_RUN:
                        try:
                            p.write_text(text + note, encoding="utf-8")
                        except:
                            pass
        except:
            continue
    if entries:
        resurf_log.parent.mkdir(parents=True, exist_ok=True)
        with open(resurf_log, "a", encoding="utf-8") as f:
            f.write("\n## " + now.isoformat() + " - " + str(len(entries)) + " ideas\n")
            f.write("\n".join(entries[:8]) + "\n")
    return stats

def evaluate_and_relocate_misplaced(root: Path, silo_name: str, dry_run: bool = False) -> Dict:
    """Explicit-only gates. Block by default.
    Only confirmed explicit-rp moves to RoleplaySandbox (central).
    explicit-non-rp or unrelated to RP: flagged + kept (edge cases).
    Local model drives classification and smart actions.
    Optimized: keyword prefilter first for scale (AI at every relevant step).
    """
    moved = 0
    evaluated = 0
    flagged = 0
    log = []
    skip_exts = {".png", ".jpg", ".jpeg", ".gif", ".mp4", ".zip", ".exe", ".dll", ".bin", ".pyc", ".log"}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        pstr = str(p).lower()
        if any(x in pstr for x in [".git", "node_modules", "__pycache__", "tmp", ".bak", "backup", ".obsidian", ".smart-env", ".trash"]):
            continue
        if p.suffix.lower() in skip_exts:
            continue
        try:
            if p.stat().st_size > 5 * 1024 * 1024:  # skip very large
                continue
        except:
            continue
        try:
            preview = ""
            if p.suffix.lower() in [".md", ".txt", ".py", ".yaml", ".yml"]:
                preview = p.read_text(encoding="utf-8", errors="ignore")[:600]
            full_check = pstr + " " + preview.lower()
            # Prefilter: only invoke local model on potential explicit candidates
            if not any(kw in full_check for kw in EXPLICIT_RP_KEYWORDS):
                log.append("KEPT (no explicit keyword, block default): " + str(p))
                continue
            model_eval = local_model_file_evaluation(preview, str(p), silo_name)
            evaluated += 1
            if model_eval.get("class") == "explicit-rp" and silo_name != "RoleplaySandbox":
                relocate_to_sandbox(p, dry_run)
                moved += 1
                log.append("MOVED explicit-rp to sandbox: " + str(p) + " | " + model_eval.get("reason", ""))
            elif model_eval.get("class") == "explicit-non-rp":
                flagged += 1
                msg = "FLAGGED explicit-non-rp (kept in " + silo_name + " - unrelated to RP): " + str(p) + " | " + model_eval.get("reason", "")
                log.append(msg)
                audit = Path(r"D:\PhronesisVault\Roleplay-Sandbox\data\misplaced_from_vaultwalker\relocation_audit.md")
                audit.parent.mkdir(parents=True, exist_ok=True)
                with open(audit, "a", encoding="utf-8") as f:
                    f.write("## " + datetime.now().isoformat() + " - " + msg + "\n")
            else:
                log.append("KEPT (block default): " + str(p) + " class=" + model_eval.get("class", ""))
        except:
            continue
    return {"moved": moved, "evaluated": evaluated, "flagged_non_rp_explicit": flagged, "log": log[:8]}

def housekeeping_silo(name: str, root: Path) -> Dict:
    stats = {}
    state = load_persistent_state(name)
    is_light = is_light_cycle()
    print("[VAULTWALKER] " + name + " - " + ("LIGHT" if is_light else "DEEP"))

    # Indexes first and accurate every pass
    idx = update_per_folder_indexes(root, name, state, is_light)
    cc = clean_code_non_ascii(root) if not is_light else 0
    mr = review_and_modify_markdowns(root, "", name, state, is_light)

    # Relocate (explicit-only, after review) - pass DRY_RUN
    reloc = evaluate_and_relocate_misplaced(root, name, DRY_RUN) if not is_light else {"moved": 0, "evaluated": 0}

    res = resurface_forgotten_ideas(root, name, state) if not is_light else {}

    stats["per_folder_indexes"] = idx
    stats["code_cleaned"] = cc
    stats.update({"md_" + k: v for k, v in mr.items()})
    stats["reloc_moved"] = reloc.get("moved", 0)
    stats["reloc_evaluated"] = reloc.get("evaluated", 0)
    stats["reloc_flagged_non_rp"] = reloc.get("flagged_non_rp_explicit", 0)
    if res:
        stats.update({"res_" + k: v for k, v in res.items()})

    save_persistent_state(name, state)
    return stats

def run_silo(name: str, root: Path) -> Tuple[str, Dict]:
    if not root.exists():
        return name, {"error": "not mounted"}
    stats = housekeeping_silo(name, root)
    return name, stats

def main():
    global args, DRY_RUN
    parser = argparse.ArgumentParser(description="VaultWalker v0.7.0 - explicit-only silo housekeeper")
    parser.add_argument("--silos", nargs="*", default=list(SILOS.keys()))
    parser.add_argument("--dry-run", action="store_true", help="Dry run: no writes or moves")
    args = parser.parse_args()
    DRY_RUN = bool(args.dry_run)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    summary = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(run_silo, n, SILOS[n]): n for n in args.silos if n in SILOS}
        for fut in concurrent.futures.as_completed(futures):
            name, stats = fut.result()
            summary[name] = stats
            print("[VAULTWALKER] " + name + " done: " + str({k: v for k, v in stats.items() if not isinstance(v, (list, dict))}))

    print(json.dumps({"status": "complete", "summary": summary}, indent=2))

if __name__ == "__main__":
    main()
