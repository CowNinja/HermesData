#!/usr/bin/env python3
"""Lock Four Worlds silo architecture across config + key vault docs."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import yaml

CANON = "Operations/Four-Worlds-Silo-Architecture-CANONICAL-2026-07-10"
CANON_PATH = Path(r"D:\PhronesisVault") / (CANON + ".md")


def main() -> int:
    # --- data_silos.yaml ---
    yp = Path(r"D:\HermesData\config\data_silos.yaml")
    shutil.copy2(yp, yp.with_suffix(yp.suffix + f".bak-fourworlds-{datetime.now():%Y%m%d-%H%M%S}"))
    data = yaml.safe_load(yp.read_text(encoding="utf-8")) or {}
    data["version"] = "1.0.0-four-worlds"
    data["canonical_doc"] = str(CANON_PATH)
    data["description"] = (
        "Four Worlds CANONICAL 2026-07-10: "
        "(1) HermesData runtime_ops (2) PhronesisVault cns_mirror "
        "(3) K Phronesis-Sovereign ssot_silo (4) Roleplay-Sandbox walled_garden. "
        "Expand via new silos.* entries. See canonical_doc."
    )
    g = data.setdefault("global", {})
    g["dry_run_default"] = True
    g["canonical_architecture"] = "four_worlds"
    g["expandability"] = (
        "Add silos.<name> with path, type, world, wall, policies; "
        "types: runtime_ops|cns_mirror|ssot_silo|walled_garden|+future"
    )
    ip = g.setdefault("iteration_policies", {})
    ip["dry_run_default"] = True

    data["silos"] = {
        "HermesData": {
            "path": r"D:\HermesData",
            "type": "runtime_ops",
            "world": 1,
            "label": "Hermes system",
            "local_first": True,
            "update_per_folder_indexes": True,
            "non_ascii_code_clean": False,
            "md_review": True,
            "wall": "no_personal_ssot; no_explicit_rp_store",
            "vision_ref": str(CANON_PATH),
            "policies": "Runtime code/skills/cron. Not life SSOT. Not RP garden.",
        },
        "PhronesisVault": {
            "path": r"D:\PhronesisVault",
            "type": "cns_mirror",
            "world": 2,
            "label": "Second brain / Obsidian CNS",
            "local_first": True,
            "update_per_folder_indexes": True,
            "non_ascii_code_clean": False,
            "md_review": True,
            "wall": "working_wiki; explicit_only_inside_Roleplay-Sandbox_subtree",
            "vision_ref": str(CANON_PATH),
            "policies": "How we work. Roleplay-Sandbox subtree is world 4 rules.",
        },
        "K_PhronesisSovereign": {
            "path": r"K:\Phronesis-Sovereign",
            "type": "ssot_silo",
            "world": 3,
            "label": "Life archive / digital twin",
            "local_first": True,
            "update_per_folder_indexes": True,
            "non_ascii_code_clean": False,
            "md_review": False,
            "wall": "hermes_managed; non_destructive_default; provenance_on_ingest; no_rp",
            "personal_digital_silo": r"K:\Phronesis-Sovereign\Personal-Digital-Silo",
            "vision_ref": str(CANON_PATH),
            "policies": "What lived. Hermes builds silos + twin. No silent deletes. No RP.",
        },
        "RoleplaySandbox": {
            "path": r"D:\PhronesisVault\Roleplay-Sandbox",
            "type": "walled_garden",
            "world": 4,
            "label": "Explicit RP sandbox",
            "local_first": True,
            "update_per_folder_indexes": True,
            "non_ascii_code_clean": False,
            "md_review": True,
            "wall": "inbound_explicit_ok; no_outbound_to_life_or_ops_brain",
            "vision_ref": str(CANON_PATH),
            "policies": "Walled garden. Never leak to K life silo or Operations research.",
        },
    }
    yp.write_text(
        yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    Path(r"D:\HermesData\config\data_silos.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("config ok")

    def link_doc(path: Path, marker: str, block: str) -> None:
        if not path.exists():
            print("skip missing", path)
            return
        t = path.read_text(encoding="utf-8", errors="ignore")
        if marker in t:
            print("already", path.name)
            return
        path.write_text(t.rstrip() + "\n\n" + block + "\n", encoding="utf-8")
        print("linked", path.name)

    link = f"[[{CANON}]]"
    link_doc(
        Path(r"D:\PhronesisVault\Operations\Data-Management-and-Ingestion-Policy.md"),
        "Four-Worlds-Silo-Architecture-CANONICAL",
        f"## Four Worlds (canonical — do not drift)\n\nSee **{link}**.\n\n"
        "| World | Path | Role |\n|-------|------|------|\n"
        "| 1 Hermes | `D:\\\\HermesData` | Runtime |\n"
        "| 2 Vault | `D:\\\\PhronesisVault` | Second brain |\n"
        "| 3 K Sovereign | `K:\\\\Phronesis-Sovereign` | Life/twin SSOT |\n"
        "| 4 RP Sandbox | `D:\\\\PhronesisVault\\\\Roleplay-Sandbox` | Walled explicit |\n",
    )
    for rel in [
        "Grand-Vision-Silo-Gardener-and-Hermes-Continuity-2026-07-10.md",
        "Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10.md",
        "Phronesis-Hermes-Full-Infrastructure-Architecture.md",
        "Vault-Gardener-Automation-System-2026-07-10.md",
        "Lesson-to-Automation-Protocol-2026-07-10.md",
        "Hybrid-Grok-Driver-Qwythos-Grunt-Architecture-2026-07-10.md",
        "Operations-Navigation-Map.md",
    ]:
        link_doc(
            Path(r"D:\PhronesisVault\Operations") / rel,
            "Four-Worlds-Silo-Architecture-CANONICAL",
            f"## Four Worlds (no drift)\n\nCanonical: {link}\n",
        )

    # Root index
    root = Path(r"D:\PhronesisVault\00-INDEX.md")
    if root.exists():
        t = root.read_text(encoding="utf-8")
        if "Four-Worlds-Silo-Architecture-CANONICAL" not in t:
            insert = (
                "## Four Worlds\n"
                "| World | Path |\n|-------|------|\n"
                "| 1 Hermes | `D:\\\\HermesData` |\n"
                "| 2 Vault | `D:\\\\PhronesisVault` |\n"
                "| 3 Life/twin | `K:\\\\Phronesis-Sovereign` |\n"
                "| 4 RP wall | `D:\\\\PhronesisVault\\\\Roleplay-Sandbox` |\n"
                f"Canonical: {link}\n\n"
            )
            if "## Where to go" in t:
                t = t.replace("## Where to go", insert + "## Where to go", 1)
            else:
                t = t.rstrip() + "\n\n" + insert
            root.write_text(t, encoding="utf-8")
            print("root index")

    # K master
    kidx = Path(r"K:\Phronesis-Sovereign\00-MASTER-K-SOVEREIGN-INDEX.md")
    if kidx.exists():
        t = kidx.read_text(encoding="utf-8", errors="ignore")
        if "Four Worlds lock" not in t:
            kidx.write_text(
                t.rstrip()
                + "\n\n---\n\n## Four Worlds lock (2026-07-10)\n\n"
                "This tree is **World 3 — Life / digital twin SSOT**.\n\n"
                "- World 1: `D:\\\\HermesData`\n"
                "- World 2: `D:\\\\PhronesisVault`\n"
                "- World 4: `D:\\\\PhronesisVault\\\\Roleplay-Sandbox` (never store explicit RP on K:)\n\n"
                f"Canonical: `{CANON_PATH}`\n\n"
                "Hermes-managed: organize, index, ingest with provenance; non-destructive default.\n",
                encoding="utf-8",
            )
            print("K master")
    else:
        print("K master missing")

    # RP readme
    rp = Path(r"D:\PhronesisVault\Roleplay-Sandbox\README.md")
    block = (
        "\n\n## Four Worlds — World 4 (walled garden)\n\n"
        "Explicit/roleplay only. Do not put life SSOT here; do not leak explicit into K: or Operations research.\n"
        f"Canonical: {link}\n"
    )
    if rp.exists():
        t = rp.read_text(encoding="utf-8", errors="ignore")
        if "World 4" not in t:
            rp.write_text(t.rstrip() + block, encoding="utf-8")
            print("RP readme")
    else:
        rp.write_text("# Roleplay-Sandbox\n" + block, encoding="utf-8")
        print("RP readme created")

    Path(r"D:\HermesData\FOUR-WORLDS.md").write_text(
        "# Four Worlds — HermesData is World 1\n\n"
        f"Canonical: `{CANON_PATH}`\n\n"
        "Config: `config/data_silos.yaml` + `data_silos.json`\n",
        encoding="utf-8",
    )
    print("HermesData pointer")

    hk = Path(r"D:\PhronesisVault\Housekeeping.md")
    if hk.exists():
        cur = hk.read_text(encoding="utf-8", errors="ignore")
        if "Four Worlds silo architecture CANONICAL" not in cur:
            hk.write_text(
                cur
                + f"\n- 2026-07-10: Four Worlds CANONICAL locked. {link}\n",
                encoding="utf-8",
            )
            print("housekeeping")

    # skill pointer snippet in grok-efficiency if exists
    skill = Path(r"D:\HermesData\skills\ops\grok-efficiency-mode\SKILL.md")
    if skill.exists():
        t = skill.read_text(encoding="utf-8", errors="ignore")
        if "Four-Worlds-Silo-Architecture-CANONICAL" not in t:
            skill.write_text(
                t.rstrip()
                + "\n\n## Four Worlds\n\n"
                "Route all file work by world: HermesData · PhronesisVault · K:Phronesis-Sovereign · Roleplay-Sandbox.\n"
                f"Canonical: `{CANON_PATH}`\n",
                encoding="utf-8",
            )
            print("grok-efficiency skill")

    lesson = Path(r"D:\HermesData\skills\ops\lesson-to-automation\SKILL.md")
    if lesson.exists():
        t = lesson.read_text(encoding="utf-8", errors="ignore")
        if "Four-Worlds" not in t:
            lesson.write_text(
                t.rstrip()
                + f"\n\n## Four Worlds\n\nAlways respect silo walls. Canonical: `{CANON_PATH}`\n",
                encoding="utf-8",
            )
            print("lesson skill")

    # vault-curation brief
    vc = Path(r"D:\HermesData\skills\vault-curation\SKILL.md")
    if vc.exists():
        t = vc.read_text(encoding="utf-8", errors="ignore")
        if "Four-Worlds-Silo-Architecture-CANONICAL" not in t:
            # insert near top after first ---
            vc.write_text(
                t.replace(
                    "# Vault Curation\n",
                    "# Vault Curation\n\n"
                    f"**Four Worlds CANONICAL:** `{CANON_PATH}` "
                    "(HermesData | PhronesisVault | K:Phronesis-Sovereign | Roleplay-Sandbox walls).\n\n",
                    1,
                ),
                encoding="utf-8",
            )
            print("vault-curation skill")

    print("ALL DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
