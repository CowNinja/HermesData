#!/usr/bin/env python3
"""Four Worlds placement audit — REPORT ONLY (no moves).

Worlds:
  1 D:\\HermesData          runtime_ops
  2 D:\\PhronesisVault      cns (working wiki)
  3 K:\\Phronesis-Sovereign ssot life/twin
  4 D:\\PhronesisVault\\Roleplay-Sandbox  walled RP

Flags:
  - explicit/RP-like outside world 4
  - personal-life keywords in HermesData / RP (possible misplace)
  - large personal archives under Vault root (not K:)
  - code/runtime trees under K: that look like Hermes clones
  - RP paths under K:
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
HERMES = Path(r"D:\HermesData")
K_ROOT = Path(r"K:\Phronesis-Sovereign")
RP = VAULT / "Roleplay-Sandbox"

OUT_JSON = HERMES / "logs" / "four-worlds-placement-audit-latest.json"
OUT_MD = VAULT / "Operations" / "logs" / "four-worlds-placement-audit-latest.md"

SKIP_DIR_PARTS = {
    ".git", "node_modules", "__pycache__", ".obsidian", ".smart-env",
    "site-packages", "alice_venv", "venv", ".venv",
    "Distillations-2026-07-10", "$RECYCLE.BIN", "System Volume Information",
    "ComfyUI", "models", "checkpoints", "loras", "output", "outputs",
    "Backups", "archives", "archive", "llama.cpp", ".cache", "hf_cache",
    "Audio", "videos", "_corrupt_oneline", "cache", "terminal",
    "purged-non-roleplay", "wisdomvault",
}

# Explicit / RP signals (path + light content)
EXPLICIT_PATH_RE = re.compile(
    r"(nude|nsfw|porn|harem|explicit|erotica|xxx|onlyfans|"
    r"roleplay-sandbox|rp-scene|creampie|bent-over|spread-pussy|"
    r"\\bporn\\b|adult-content|heat-doctrine)",
    re.I,
)
# Avoid false positives on clinical/medical if only "sexual" in medical context — still flag path
EXPLICIT_CONTENT_RE = re.compile(
    r"\b(nsfw|onlyfans|pornHub|hentai|creampie|gangbang|"
    r"explicit\s+roleplay|nude\s+spread|barely.?covered\s+nipples)\b",
    re.I,
)

# Life / PII-ish signals that should prefer K: (flag if under Hermes or deep RP)
LIFE_PATH_RE = re.compile(
    r"(ssn|social.security|dd-214|medical.record|va.claim|"
    r"bank.statement|tax.return|passport|driver.?license|"
    r"navy.service|personal-digital-silo)",
    re.I,
)

# Runtime signals under K (Hermes clone risk)
RUNTIME_PATH_RE = re.compile(
    r"(node_modules|\\\\.git\\\\|hermes-agent|llama\.cpp|ComfyUI\\\\models)",
    re.I,
)

TEXT_EXT = {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".csv"}


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIR_PARTS for part in path.parts)


def world_of(path: Path) -> str:
    s = str(path)
    try:
        if path == RP or RP in path.parents or path == RP:
            return "4_rp"
    except Exception:
        pass
    sp = str(path).lower().replace("/", "\\")
    if sp.startswith(str(RP).lower().replace("/", "\\")):
        return "4_rp"
    if sp.startswith(r"d:\hermesdata") or sp.startswith("d:/hermesdata"):
        return "1_hermes"
    if sp.startswith(r"k:\phronesis-sovereign") or sp.startswith("k:/phronesis-sovereign"):
        return "3_k"
    if sp.startswith(r"d:\phronesisvault") or sp.startswith("d:/phronesisvault"):
        return "2_vault"
    if sp.startswith("k:\\") or sp.startswith("k:/"):
        return "3_k_other"
    return "other"


def iter_files(root: Path, max_files: int = 25000):
    n = 0
    if not root.exists():
        return
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if should_skip(p):
            continue
        yield p
        n += 1
        if n >= max_files:
            return


def preview_text(p: Path, limit: int = 400) -> str:
    try:
        if p.suffix.lower() not in TEXT_EXT:
            return ""
        if p.stat().st_size > 2_000_000:
            return ""
        return p.read_text(encoding="utf-8", errors="ignore")[:limit]
    except OSError:
        return ""


def main() -> int:
    findings = defaultdict(list)
    stats = {
        "scanned_files": 0,
        "roots": {},
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    roots = {
        "hermes": HERMES,
        "vault": VAULT,
        "k": K_ROOT,
    }
    for name, root in roots.items():
        stats["roots"][name] = root.exists()

    # 1) Explicit outside RP
    for name, root in roots.items():
        for p in iter_files(root):
            stats["scanned_files"] += 1
            w = world_of(p)
            if w == "4_rp":
                continue
            path_s = str(p)
            hit_path = bool(EXPLICIT_PATH_RE.search(path_s))
            hit_content = False
            # Content scan only if path suspicious or small note in heat-ish folders
            lowp = path_s.lower()
            maybe = hit_path or (
                p.suffix.lower() in {".md", ".txt"}
                and p.stat().st_size < 80_000
                and any(x in lowp for x in ("alice", "harem", "gallery", "explicit", "nsfw", "sandbox", "scene"))
            )
            if maybe:
                prev = preview_text(p)
                if prev and EXPLICIT_CONTENT_RE.search(prev):
                    hit_content = True
            if hit_path or hit_content:
                # ignore known false positives
                low = path_s.lower()
                if "code-scripts-ascii" in low:
                    continue
                if "four-worlds" in low:
                    continue
                if "rp_garden_wall" in low or "garden wall" in low:
                    continue
                if "vaultwalker" in low and "roleplay" in low and p.suffix == ".md":
                    # policy docs mentioning RP — still note lightly
                    findings["explicit_mentions_in_policy_docs"].append(
                        {"path": path_s, "world": w, "via": "path" if hit_path else "content"}
                    )
                    continue
                findings["explicit_outside_rp"].append(
                    {
                        "path": path_s,
                        "world": w,
                        "via": "+".join(
                            x for x, h in [("path", hit_path), ("content", hit_content)] if h
                        ),
                        "size": p.stat().st_size if p.exists() else 0,
                    }
                )

    # 2) Life signals in Hermes or Vault (not K)
    for root in (HERMES, VAULT):
        for p in iter_files(root, max_files=15000):
            w = world_of(p)
            if w in ("3_k", "3_k_other", "4_rp"):
                continue
            if LIFE_PATH_RE.search(str(p)):
                findings["life_signals_off_k"].append(
                    {"path": str(p), "world": w, "size": p.stat().st_size}
                )

    # 3) RP content under K
    if K_ROOT.exists():
        for p in iter_files(K_ROOT, max_files=15000):
            if EXPLICIT_PATH_RE.search(str(p)) or (
                p.suffix.lower() in TEXT_EXT and EXPLICIT_CONTENT_RE.search(preview_text(p))
            ):
                findings["explicit_on_k"].append({"path": str(p), "size": p.stat().st_size})

    # 4) Hermes-like trees on K
    if K_ROOT.exists():
        for p in K_ROOT.rglob("*"):
            if not p.is_dir():
                continue
            if should_skip(p):
                continue
            name = p.name.lower()
            if name in {"hermesdata", "hermes-agent", "comfyui", ".hermes"}:
                findings["runtime_trees_on_k"].append(str(p))
            # path contains HermesData clone
            if "hermesdata" in str(p).lower() and p.is_dir():
                if str(p) not in findings["runtime_trees_on_k"]:
                    findings["runtime_trees_on_k"].append(str(p))

    # 5) Large media folders under vault outside RP (possible misplace)
    for p in VAULT.rglob("*"):
        if not p.is_dir() or should_skip(p):
            continue
        if world_of(p) == "4_rp":
            continue
        low = p.name.lower()
        if low in {"gallery", "nsfw", "explicit", "harem", "comfy_output", "outputs"}:
            findings["suspicious_media_dirs_outside_rp"].append(str(p))

    # 6) Sample: Roleplay-Sandbox path string leaks into K index files only — already covered

    # Cap lists for readability
    for k, v in list(findings.items()):
        if isinstance(v, list) and len(v) > 80:
            findings[k] = v[:80]
            findings[k + "_truncated"] = True
            findings[k + "_total"] = len(v)

    # Severity summary
    summary = {
        "explicit_outside_rp": len(findings.get("explicit_outside_rp") or []),
        "explicit_on_k": len(findings.get("explicit_on_k") or []),
        "life_signals_off_k": len(findings.get("life_signals_off_k") or []),
        "runtime_trees_on_k": len(findings.get("runtime_trees_on_k") or []),
        "suspicious_media_dirs_outside_rp": len(
            findings.get("suspicious_media_dirs_outside_rp") or []
        ),
        "policy_docs_mentioning_rp": len(findings.get("explicit_mentions_in_policy_docs") or []),
    }

    # Recommendations
    recs = []
    if summary["explicit_outside_rp"]:
        recs.append(
            "Review explicit_outside_rp list; relocate confirmed RP media/notes into Roleplay-Sandbox (dry-run first)."
        )
    if summary["explicit_on_k"]:
        recs.append("HIGH: explicit material on K: — move to Roleplay-Sandbox; scrub K copies after verify.")
    if summary["life_signals_off_k"]:
        recs.append(
            "Life/PII-like paths under D: — consider copy-to-K with provenance (not blind delete)."
        )
    if summary["runtime_trees_on_k"]:
        recs.append(
            "Hermes/runtime-like trees on K: — confirm backup vs active; prefer D:\\HermesData as SSOT for code."
        )
    if summary["suspicious_media_dirs_outside_rp"]:
        recs.append("Inspect media dirs outside RP; archive or move if heat/gallery content.")
    if not recs:
        recs.append("No high-severity placement issues found by heuristics; re-run after big ingests.")

    payload = {
        "stats": stats,
        "summary": summary,
        "findings": findings,
        "recommendations": recs,
        "mode": "audit_only_no_moves",
        "canonical": str(
            VAULT / "Operations" / "Four-Worlds-Silo-Architecture-CANONICAL-2026-07-10.md"
        ),
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    # Markdown report
    lines = [
        f"# Four Worlds Placement Audit — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "**Mode:** audit only — **no files moved**",
        f"**Files scanned (capped walks):** {stats['scanned_files']}",
        f"**Canonical:** [[Operations/Four-Worlds-Silo-Architecture-CANONICAL-2026-07-10]]",
        "",
        "## Summary counts",
        "",
        "| Issue | Count |",
        "|-------|------:|",
    ]
    for k, v in summary.items():
        lines.append(f"| `{k}` | {v} |")
    lines += ["", "## Recommendations", ""]
    for r in recs:
        lines.append(f"- {r}")

    def section(title: str, key: str, limit: int = 40) -> None:
        lines.append("")
        lines.append(f"## {title}")
        items = findings.get(key) or []
        if not items:
            lines.append("_None flagged._")
            return
        for it in items[:limit]:
            if isinstance(it, dict):
                lines.append(f"- `{it.get('path')}` · world={it.get('world')} · {it.get('via', '')}")
            else:
                lines.append(f"- `{it}`")
        if len(items) > limit:
            lines.append(f"- … +{len(items) - limit} more (see JSON)")

    section("Explicit / RP-like OUTSIDE Roleplay-Sandbox", "explicit_outside_rp")
    section("Explicit ON K: (should not happen)", "explicit_on_k")
    section("Life/PII-like signals off K:", "life_signals_off_k")
    section("Runtime/Hermes-like trees on K:", "runtime_trees_on_k")
    section("Suspicious media dirs outside RP", "suspicious_media_dirs_outside_rp")
    section("Policy docs that mention RP (usually OK)", "explicit_mentions_in_policy_docs", 15)

    lines += [
        "",
        "## Next steps (gated)",
        "1. You review HIGH lists.",
        "2. Green-light batch relocate script for confirmed RP-only items.",
        "3. Life data: copy-to-K with provenance, then optional D: cleanup.",
        "",
        "## Vault links",
        "- [[Operations/Four-Worlds-Silo-Architecture-CANONICAL-2026-07-10]]",
        "- [[Operations/Data-Management-and-Ingestion-Policy]]",
        "",
        f"JSON: `{OUT_JSON}`",
        "",
    ]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({"summary": summary, "scanned": stats["scanned_files"], "md": str(OUT_MD)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
