#!/usr/bin/env python3
"""
VaultWalker v0.8.0 — PhronesisVault (second-brain / Obsidian CNS) primary.

Focus (2026-07-17 streamlining):
- Default silo = PhronesisVault only (world 2 second brain). Other silos opt-in via --silos.
- Living hub indexes owned by refresh_folder_indexes.py — NEVER clobber rich 00-INDEX.
- Lean missing-folder maps only; skip Roleplay-Sandbox / Alice / package trees for index plant.
- True dry-run: no file writes (indexes, notes, moves).
- Explicit-only relocate still deep-only; block-by-default.
- Research basis: Karpathy LLM-Wiki lint; Zoottelkeeper per-folder maps; BASB light organize;
  vault failure-modes note (refresh wiping hubs); Obsidian graph = wikilinks not folder spam.

Run:
  python D:/HermesData/scripts/vaultwalker.py --dry-run --cycle resurface
  python D:/HermesData/scripts/vaultwalker.py --silos PhronesisVault --cycle light
  VAULTWALKER_LIVE=1 via vaultwalker_cron.py --live  # intentional only
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
import yaml  # for full data_silos.yaml loading
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple, Any, List, Set

# Module-level flag for clean dry-run passing
DRY_RUN = False
VAULTWALKER_VERSION = "0.8.0"
# five-item cook 2026-07-18 — never plant indexes in junk trees
SKIP_INDEX_PARTS = {
    "site-packages", "alice_venv", "node_modules", ".git", ".smart-env",
    "__pycache__", "venv", ".venv", "Lib", "Scripts", "dist-info",
}


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
    dest = target_dir / src.name
    log_msg = "RELOCATE: " + str(src) + " -> " + str(dest)
    if not dry_run:
        try:
            import shutil
            target_dir.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                dest = target_dir / (src.stem + "_" + ts + src.suffix)
                log_msg = "RELOCATE: " + str(src) + " -> " + str(dest)
            shutil.move(str(src), str(dest))
            log_msg += " [MOVED]"
            audit = target_dir / "relocation_audit.md"
            with open(audit, "a", encoding="utf-8") as f:
                f.write("## " + datetime.now().isoformat() + " - " + log_msg + "\n")
        except Exception as e:
            log_msg += " [ERROR: " + str(e)[:70] + "]"
    else:
        log_msg += " [DRY-RUN]"
    print("[VAULTWALKER-RELOCATE] " + log_msg)
    return log_msg

# === Config & Core ===
LOG_DIR = Path(r"D:\HermesData\logs")
STATE_DIR = Path(r"D:\HermesData\data\vaultwalker\state")
STALE_DAYS = 60
# Primary second-brain (Obsidian CNS). Other worlds remain opt-in.
PRIMARY_SILO = "PhronesisVault"
DEFAULT_SILOS = [PRIMARY_SILO]

# Subtrees inside PhronesisVault that are NOT living second-brain index targets
CNS_INDEX_SKIP_PARTS: Set[str] = {
    "Roleplay-Sandbox",
    "Alice",  # character assets / not ops CNS
    "alice_venv",
    "Archive",  # shelf; don't thrash distill wave indexes every cycle
    "Distillations-2026-07-10",
    "gallery",
    "ComfyUI",
}

# Markers that mean refresh_folder_indexes (or human) owns this map — do not clobber
RICH_INDEX_MARKERS = (
    "**Path:**",
    "Hot path",
    "Hot paths",
    "## Purpose",
    "**Purpose:**",
    "Agent instructions",
    "Living CNS",
    "HOT_PATH",
)


def load_config() -> Dict:
    """Load full config from data_silos.yaml for silos + policies.

    v0.8: primary focus PhronesisVault; max_depth; preserve_rich_indexes.
    """
    cfg_path = Path(r"D:\HermesData\config\data_silos.yaml")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            full = yaml.safe_load(f) or {}
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
            "type": s.get("type", ""),
        }

    # Ensure expected silos exist for opt-in multi-world runs
    if "PhronesisVault" not in silos_cfg:
        silos_cfg["PhronesisVault"] = {
            "path": r"D:\PhronesisVault",
            "update_per_folder_indexes": True,
            "non_ascii_code_clean": False,
            "md_review": True,
            "ollama_model": "qwythos-9b-abliterated",
            "type": "cns_mirror",
        }
    if "K_PhronesisSovereign" not in silos_cfg:
        silos_cfg["K_PhronesisSovereign"] = {
            "path": r"K:\Phronesis-Sovereign",
            "update_per_folder_indexes": True,
            "non_ascii_code_clean": False,
            "md_review": False,
            "ollama_model": "qwythos-9b-abliterated",
            "type": "ssot_silo",
        }

    global_cfg = full.get("global", {})
    # Flatten nested iteration_policies if present
    iter_pol = global_cfg.get("iteration_policies") or {}
    for k, v in iter_pol.items():
        global_cfg.setdefault(k, v)
    global_cfg.setdefault("persistent_state", True)
    global_cfg.setdefault("staggered_cycles", True)
    global_cfg.setdefault("local_models", True)
    global_cfg.setdefault("dry_run_default", True)
    global_cfg.setdefault("max_depth", 6)
    global_cfg.setdefault("preserve_rich_indexes", True)
    global_cfg.setdefault("primary_silo", PRIMARY_SILO)
    global_cfg.setdefault("vaultwalker_default_silos", list(DEFAULT_SILOS))
    # Cap folders processed per cycle (cron/travel safety)
    global_cfg.setdefault("max_index_updates_per_cycle", 200)
    global_cfg.setdefault("max_resurface_per_cycle", 80)

    return {
        "version": VAULTWALKER_VERSION,
        "global": global_cfg,
        "silos": silos_cfg,
    }

CFG = load_config()
SILOS = {name: Path(s["path"]) for name, s in CFG.get("silos", {}).items() if s.get("path")}
GLOBAL_POLICIES = CFG.get("global", {})
STALE_DAYS = int(GLOBAL_POLICIES.get("stale_days", STALE_DAYS) or STALE_DAYS)
MAX_DEPTH = int(GLOBAL_POLICIES.get("max_depth", 6) or 6)

# Set by main() from --cycle; None = auto staggered
FORCE_CYCLE: str | None = None


def is_light_cycle() -> bool:
    """LIGHT = indexes only; DEEP = model review+relocate; RESURFACE = indexes+stale surface.

    --cycle light|deep|resurface|auto overrides hour-based stagger.
    auto: hour%12 < 6 → light else resurface (never auto-deep — model path is weekly/manual).
    """
    if FORCE_CYCLE == "light":
        return True
    if FORCE_CYCLE in ("deep", "resurface"):
        return False
    if not GLOBAL_POLICIES.get("staggered_cycles", True):
        return False
    return (datetime.now().hour % 12) < 6


def is_resurface_only() -> bool:
    """True when deep-ish but no local-model mass calls (cron-safe)."""
    if FORCE_CYCLE == "resurface":
        return True
    if FORCE_CYCLE == "deep":
        return False
    if FORCE_CYCLE == "light":
        return False
    # auto deep window → resurface-only (safe); full model deep is explicit --cycle deep
    return not is_light_cycle()

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
    if DRY_RUN:
        return  # dry-run must not advance mtime/hash cache
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / (silo_name.lower() + "_state.json")
    state["last_updated"] = datetime.now().isoformat()
    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
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
        # Only mutate in-memory state; disk write gated by save_persistent_state (skips dry-run)
        state.setdefault("folders", {})[key] = {"mtime": mtime, "hash": h}
        return True
    except Exception:
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


def _should_skip_index_dir(dirpath: Path, root: Path | None = None) -> bool:
    parts_lower = {p.lower() for p in dirpath.parts}
    if parts_lower & {p.lower() for p in INDEX_SKIP_PARTS}:
        return True
    # Second-brain focus: skip walled garden + character asset trees for index plant
    if parts_lower & {p.lower() for p in CNS_INDEX_SKIP_PARTS}:
        return True
    name = dirpath.name.lower()
    if name.endswith(".dist-info") or name.endswith(".egg-info"):
        return True
    if name.startswith(".") and name not in {".", ".."}:
        # skip hidden tooling dirs; keep normal vault folders
        if name not in {".github"}:
            return True
    # Depth cap relative to silo root
    if root is not None:
        try:
            rel = dirpath.relative_to(root)
            if len(rel.parts) > MAX_DEPTH:
                return True
        except ValueError:
            pass
    return False


def _is_rich_index(text: str) -> bool:
    """True if owned by refresh_folder_indexes / human hub — never overwrite."""
    if not GLOBAL_POLICIES.get("preserve_rich_indexes", True):
        return False
    head = text[:1200]
    return any(m in head for m in RICH_INDEX_MARKERS)


def _atomic_write_text(path: Path, content: str) -> bool:
    """Atomic-ish write; respects DRY_RUN. Returns True if wrote (or would write)."""
    if DRY_RUN:
        return True
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write temp then replace for resilience on Windows
        fd, tmp_name = tempfile.mkstemp(prefix=".vw_", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.replace(tmp_name, str(path))
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            # Fallback non-atomic
            path.write_text(content, encoding="utf-8")
        return True
    except OSError:
        return False


def update_per_folder_indexes(root: Path, silo_name: str, state: Dict[str, Any], is_light: bool) -> int:
    """Sparse second-brain maps: fill gaps only; never clobber rich hubs.

    Living CNS hubs: refresh_folder_indexes.py (Hot paths + Purpose).
    VaultWalker: create lean 00-INDEX only when missing or when an old
    VaultWalker-stamped generic map is present (safe refresh of our own stamp).
    """
    updated = 0
    skipped_rich = 0
    skipped_budget = 0
    if not root.exists():
        return 0
    max_updates = int(GLOBAL_POLICIES.get("max_index_updates_per_cycle", 200) or 200)
    for dirpath in root.rglob("*"):
        if updated >= max_updates:
            skipped_budget += 1
            break
        if not dirpath.is_dir():
            continue
        if _should_skip_index_dir(dirpath, root):
            continue
        if not should_process_deep(dirpath, state):
            continue
        try:
            files = [f for f in dirpath.iterdir() if f.is_file()]
            md_files = [
                f
                for f in files
                if f.suffix.lower() == ".md"
                and f.name.lower() not in ("00-index.md", "index.md")
            ]
        except OSError:
            continue

        # Prefer existing INDEX.md if present (human/legacy)
        if (dirpath / "INDEX.md").exists():
            idx_file = dirpath / "INDEX.md"
        else:
            idx_file = dirpath / "00-INDEX.md"

        if idx_file.exists():
            try:
                existing = idx_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if _is_rich_index(existing):
                skipped_rich += 1
                continue
            # Only rewrite our own generic stamps (or empty stubs)
            if "VaultWalker" not in existing[:200] and len(existing.strip()) > 80:
                # Unknown hand-written index — preserve
                skipped_rich += 1
                continue

        # Prefer wikilinks for .md so Graph gains edges
        file_lines = []
        for f in sorted(md_files, key=lambda p: p.name.lower())[:30]:
            try:
                rel = f.relative_to(root)
                stem = str(rel.with_suffix("")).replace("\\", "/")
                file_lines.append(f"- [[{stem}|{f.name}]]")
            except ValueError:
                file_lines.append(f"- `{f.name}`")
        if not file_lines:
            if not md_files and len(files) == 0:
                # empty dir — skip planting noise
                continue
            file_lines = [f"- (no markdown; {len(files)} other files)"]

        try:
            rel_dir = str(dirpath.relative_to(root)).replace("\\", "/")
        except ValueError:
            rel_dir = dirpath.name

        content = (
            f"# {dirpath.name} — INDEX\n\n"
            f"**Path:** `{rel_dir}`  \n"
            f"**Updated:** {datetime.now().strftime('%Y-%m-%d')}  \n"
            f"**Silo:** {silo_name} (VaultWalker {VAULTWALKER_VERSION})  \n"
            f"**Role:** second-brain map — agent reads this before deep scan.\n\n"
            f"## Files\n"
            f"{chr(10).join(file_lines)}\n\n"
            f"Files total: {len(files)} · md: {len(md_files)}\n"
            f"\n> Living hubs with Hot paths are owned by `refresh_folder_indexes.py` "
            f"— do not clobber.\n"
        )

        if _atomic_write_text(idx_file, content):
            updated += 1
    if skipped_rich:
        print(f"[VAULTWALKER] {silo_name} preserved rich indexes: {skipped_rich}")
    if skipped_budget:
        print(f"[VAULTWALKER] {silo_name} index budget cap hit ({max_updates})")
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
    """Surface stale/low-link notes into a CNS log. True dry-run: no writes."""
    stats = {"stale_found": 0, "surfaced": 0, "examples": []}
    if not root.exists():
        return stats
    now = datetime.now()
    # Keep resurface log under Operations/logs for second-brain focus
    if silo_name == PRIMARY_SILO:
        resurf_log = root / "Operations" / "logs" / "vaultwalker-resurfaced-latest.md"
    else:
        resurf_log = root / "Resurfaced-Ideas.md"
    entries = []
    skip_parts = {
        ".git", "node_modules", "__pycache__", ".obsidian", ".smart-env",
        "Roleplay-Sandbox", "Alice", "alice_venv", "Archive", "site-packages",
        "venv", ".venv", "Distillations-2026-07-10", "00-INDEX.md",
    }
    max_surface = int(GLOBAL_POLICIES.get("max_resurface_per_cycle", 80) or 80)
    for p in root.rglob("*.md"):
        if stats["surfaced"] >= max_surface:
            break
        try:
            parts = set(p.parts)
            if parts & skip_parts:
                continue
            # Skip index maps themselves
            if p.name.lower() in ("00-index.md", "index.md"):
                continue
        except Exception:
            continue
        if not should_process_deep(p, state):
            continue
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
            days_old = (now - mtime).days
            text = p.read_text(encoding="utf-8", errors="ignore")
            links = text.count("[[")
            if days_old > STALE_DAYS or (links < 2 and len(text) > 250 and "archive" not in str(p).lower()):
                rel = str(p.relative_to(root)).replace("\\", "/")
                entry = "- [[" + rel.replace(".md", "") + "]] (~" + str(days_old) + "d, " + str(links) + " links)"
                stats["stale_found"] += 1
                stats["surfaced"] += 1
                if len(stats["examples"]) < 5:
                    stats["examples"].append(rel)
                entries.append(entry)
                # Do NOT append inline notes to every stale file (noise). Log only.
        except Exception:
            continue
    if entries:
        header = (
            f"# VaultWalker Resurface — {now.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"**Silo:** {silo_name} · **Version:** {VAULTWALKER_VERSION} · "
            f"**Mode:** {'DRY-RUN' if DRY_RUN else 'LIVE'}\n\n"
            f"Stale/low-link candidates (cap {max_surface}). "
            f"Living CNS focus: D:\\PhronesisVault only by default.\n\n"
        )
        body = header + "\n".join(entries[:max_surface]) + "\n"
        if DRY_RUN:
            print(f"[VAULTWALKER] resurface dry-run candidates={len(entries)} (no write)")
        else:
            try:
                resurf_log.parent.mkdir(parents=True, exist_ok=True)
                resurf_log.write_text(body, encoding="utf-8")
            except OSError as e:
                print(f"[VAULTWALKER] resurface log write fail: {e}")
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
                continue
            model_eval = local_model_file_evaluation(preview, str(p), silo_name)
            evaluated += 1
            if evaluated > 40:
                log.append("BUDGET: stop after 40 model evals this silo")
                break
            if model_eval.get("class") == "explicit-rp" and silo_name != "RoleplaySandbox":
                relocate_to_sandbox(p, dry_run)
                moved += 1
                log.append("MOVED explicit-rp to sandbox: " + str(p) + " | " + model_eval.get("reason", ""))
            elif model_eval.get("class") == "explicit-non-rp":
                flagged += 1
                msg = "FLAGGED explicit-non-rp (kept in " + silo_name + " - unrelated to RP): " + str(p) + " | " + model_eval.get("reason", "")
                log.append(msg)
                if not dry_run:
                    audit = Path(r"D:\PhronesisVault\Roleplay-Sandbox\data\misplaced_from_vaultwalker\relocation_audit.md")
                    try:
                        audit.parent.mkdir(parents=True, exist_ok=True)
                        with open(audit, "a", encoding="utf-8") as f:
                            f.write("## " + datetime.now().isoformat() + " - " + msg + "\n")
                    except OSError:
                        pass
            else:
                log.append("KEPT (block default): " + str(p) + " class=" + model_eval.get("class", ""))
        except Exception:
            continue
    return {"moved": moved, "evaluated": evaluated, "flagged_non_rp_explicit": flagged, "log": log[:8]}


def housekeeping_silo(name: str, root: Path) -> Dict:
    stats = {}
    state = load_persistent_state(name)
    is_light = is_light_cycle()
    resurface_only = is_resurface_only()
    mode = "LIGHT" if is_light else ("RESURFACE" if resurface_only else "DEEP")
    print("[VAULTWALKER] " + name + " - " + mode + " v" + VAULTWALKER_VERSION + (" DRY-RUN" if DRY_RUN else " LIVE"))
    sys.stdout.flush()

    # Indexes first and accurate every pass
    idx = update_per_folder_indexes(root, name, state, is_light or resurface_only)
    cc = clean_code_non_ascii(root) if mode == "DEEP" else 0
    # Model MD review only on explicit deep (not cron default)
    mr = review_and_modify_markdowns(root, "", name, state, is_light or resurface_only)

    # Explicit relocate only on full deep
    if mode == "DEEP":
        reloc = evaluate_and_relocate_misplaced(root, name, DRY_RUN)
    else:
        reloc = {"moved": 0, "evaluated": 0, "flagged_non_rp_explicit": 0}

    # Resurface forgotten ideas on resurface + deep
    res = resurface_forgotten_ideas(root, name, state) if not is_light else {}

    stats["per_folder_indexes"] = idx
    stats["code_cleaned"] = cc
    stats["cycle_mode"] = mode
    stats["vaultwalker_version"] = VAULTWALKER_VERSION
    stats["dry_run"] = DRY_RUN
    stats.update({"md_" + k: v for k, v in mr.items()})
    stats["reloc_moved"] = reloc.get("moved", 0)
    stats["reloc_evaluated"] = reloc.get("evaluated", 0)
    stats["reloc_flagged_non_rp"] = reloc.get("flagged_non_rp_explicit", 0)
    if res:
        stats.update({"res_" + k: v for k, v in res.items()})

    # State always may update mtime cache (local HermesData only — not vault content)
    save_persistent_state(name, state)
    return stats

def run_silo(name: str, root: Path) -> Tuple[str, Dict]:
    if not root.exists():
        return name, {"error": "not mounted"}
    try:
        stats = housekeeping_silo(name, root)
    except Exception as e:
        print(f"[VAULTWALKER] ERROR {name}: {type(e).__name__}: {e}")
        return name, {"error": f"{type(e).__name__}: {e}"}
    return name, stats

def main():
    global args, DRY_RUN, FORCE_CYCLE
    parser = argparse.ArgumentParser(
        description=f"VaultWalker v{VAULTWALKER_VERSION} — PhronesisVault second-brain housekeeper"
    )
    # v0.8 default: PhronesisVault only (other silos opt-in)
    parser.add_argument(
        "--silos",
        nargs="*",
        default=list(DEFAULT_SILOS),
        help=f"Silos to walk (default: {DEFAULT_SILOS}). Opt-in multi-world via names.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Dry run: no writes or moves")
    parser.add_argument(
        "--cycle",
        choices=["auto", "light", "deep", "resurface"],
        default="auto",
        help="light=indexes; resurface=indexes+stale surface (cron-safe); deep=model review+relocate; auto=stagger light/resurface",
    )
    args = parser.parse_args()
    DRY_RUN = bool(args.dry_run)
    FORCE_CYCLE = None if args.cycle == "auto" else args.cycle

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    silo_list = [n for n in args.silos if n in SILOS]
    unknown = [n for n in args.silos if n not in SILOS]
    if unknown:
        print(f"[VAULTWALKER] unknown silos skipped: {unknown}")
    if not silo_list:
        print("[VAULTWALKER] no valid silos; defaulting to PhronesisVault")
        silo_list = [PRIMARY_SILO] if PRIMARY_SILO in SILOS else []

    print(
        f"[VAULTWALKER] v{VAULTWALKER_VERSION} focus={PRIMARY_SILO} "
        f"silos={silo_list} cycle={args.cycle} dry_run={DRY_RUN}"
    )
    summary = {}
    # Single-silo default: no need for heavy thread pool; keep pool for multi opt-in
    workers = min(3, max(1, len(silo_list)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(run_silo, n, SILOS[n]): n for n in silo_list}
        for fut in concurrent.futures.as_completed(futures):
            try:
                name, stats = fut.result()
            except Exception as e:
                name = futures[fut]
                stats = {"error": f"{type(e).__name__}: {e}"}
            summary[name] = stats
            print(
                "[VAULTWALKER] "
                + name
                + " done: "
                + str({k: v for k, v in stats.items() if not isinstance(v, (list, dict))})
            )

    print(
        json.dumps(
            {
                "status": "complete",
                "meta": {
                    "version": VAULTWALKER_VERSION,
                    "primary_silo": PRIMARY_SILO,
                    "dry_run": DRY_RUN,
                    "cycle": args.cycle,
                },
                "summary": summary,
            },
            indent=2,
            default=str,
        )
    )

if __name__ == "__main__":
    main()
