#!/usr/bin/env python3
"""Disk-side Obsidian plugin streamline for PhronesisVault (2026-07-18)."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
OBS = VAULT / ".obsidian"
TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    print("TS", TS)

    # ---- app.json ignore filters (performance) ----
    app_path = OBS / "app.json"
    app = load_json(app_path)
    ign = list(app.get("userIgnoreFilters") or [])
    add = [
        "Operations/backups/",
        "Operations/logs/",
        ".smart-env/",
        "Excalidraw/",
        "**/*.ajson",
        "AI-Computer-Management/Current-State/",
        "docs/agent-coordination/",
    ]
    seen = set()
    new = []
    for x in ign + add:
        if x not in seen:
            seen.add(x)
            new.append(x)
    app["userIgnoreFilters"] = new
    app.setdefault("alwaysUpdateLinks", True)
    dump_json(app_path, app)
    print("app ignores", len(new))

    # ---- smart_env folder exclusions ----
    se_path = VAULT / ".smart-env" / "smart_env.json"
    se = load_json(se_path)
    excl = (
        "Operations/logs, Operations/backups, Archive, Alice, Roleplay-Sandbox, "
        ".smart-env, node_modules, copilot, temp, temp_sources, scripts, references, "
        "AI-Zone/Drafts, AI-Zone/exports, Excalidraw, AI-Computer-Management/Current-State"
    )
    ss = se.setdefault("smart_sources", {})
    ss["folder_exclusions"] = excl
    ss["file_exclusions"] = "Untitled, 00-INDEX"
    se["new_user"] = False
    se["re_import_wait_time"] = 30
    dump_json(se_path, se)
    print("smart_env exclusions set")

    # ---- copilot: stop bad model/index spam ----
    cp = OBS / "plugins" / "copilot" / "data.json"
    cd = load_json(cp)
    cd["indexVaultToVectorStore"] = "NEVER"
    cd["enableIndexSync"] = False
    cd["qaExclusions"] = (
        "copilot, Operations/logs, Operations/backups, Archive, Alice, "
        "Roleplay-Sandbox, .smart-env, node_modules, temp, temp_sources, scripts"
    )
    dmk = str(cd.get("defaultModelKey", ""))
    if "ollama" in dmk.lower() and "glm" in dmk.lower():
        cd["defaultModelKey"] = "google/gemini-2.5-flash|openrouterai"
        print("copilot defaultModelKey -> openrouter gemini flash")
    dump_json(cp, cd)
    print("copilot index NEVER")

    # ---- metadata-menu quiet ----
    mm = OBS / "plugins" / "metadata-menu" / "data.json"
    md = load_json(mm)
    md["disableDataviewPrompt"] = True
    md["showIndexingStatusInStatusBar"] = False
    md["fileIndexingExcludedFolders"] = [
        "Operations/logs",
        "Operations/backups",
        "Archive",
        "Alice",
        "Roleplay-Sandbox",
        ".smart-env",
        "node_modules",
        "copilot",
        "temp",
        "temp_sources",
        "scripts",
        "Excalidraw",
    ]
    dump_json(mm, md)
    print("metadata-menu quiet")

    # ---- omnisearch hide excluded + downrank heavy ----
    om = OBS / "plugins" / "omnisearch" / "data.json"
    od = load_json(om)
    od["hideExcluded"] = True
    od["downrankedFoldersFilters"] = [
        "Operations/logs",
        "Operations/backups",
        "Archive",
        "Alice",
        "Roleplay-Sandbox",
        "AI-Zone/Drafts",
        "temp",
        "temp_sources",
        "scripts",
        ".smart-env",
    ]
    dump_json(om, od)
    print("omnisearch downrank")

    # ---- dataview data.json sensible defaults (create) ----
    dv = OBS / "plugins" / "dataview" / "data.json"
    if not dv.exists():
        dv_data = {
            "renderNullAs": "\\-",
            "taskCompletionTracking": False,
            "warnOnEmptyResult": False,
            "refreshEnabled": True,
            "refreshInterval": 2500,
            "defaultDateFormat": "yyyy-MM-dd",
            "defaultDateTimeFormat": "yyyy-MM-dd HH:mm",
            "maxRecursiveRenderDepth": 4,
            "tableIdColumnName": "File",
            "tableGroupColumnName": "Group",
            "showResultCount": True,
            "allowHtml": True,
            "inlineQueryPrefix": "=",
            "inlineJsQueryPrefix": "$=",
            "inlineQueriesInCodeblocks": True,
            "enableInlineDataview": True,
            "enableDataviewJs": False,
            "enableInlineDataviewJs": False,
            "prettyRenderInlineFields": True,
            "dataviewJsKeyword": "dataviewjs",
        }
        dump_json(dv, dv_data)
        print("dataview data.json created (JS off for safety/speed)")
    else:
        print("dataview data exists")

    # ---- Excalidraw folder stub ----
    ex = VAULT / "Excalidraw"
    ex.mkdir(exist_ok=True)
    (ex / "Scripts").mkdir(exist_ok=True)
    tpl = ex / "Template.excalidraw.md"
    if not tpl.exists() and not (ex / "Template.excalidraw").exists():
        tpl.write_text(
            "---\n"
            "tags:\n"
            "  - domain/setup\n"
            "excalidraw-plugin: parsed\n"
            "---\n\n"
            "# Excalidraw template stub\n\n"
            "Created by plugin-streamline so Excalidraw folder/template paths resolve. "
            "Open via Excalidraw plugin to replace with a real drawing template if desired.\n",
            encoding="utf-8",
        )
        print("excalidraw stub created")
    else:
        print("excalidraw template exists")

    idx = ex / "00-INDEX.md"
    if not idx.exists():
        idx.write_text(
            "---\n"
            "tags:\n"
            "  - domain/setup\n"
            "  - type/index\n"
            "---\n\n"
            "# Excalidraw\n\n"
            "Drawings folder for Excalidraw plugin. Template stub present.\n",
            encoding="utf-8",
        )

    # ---- workspace: drop heavy juggl side views ----
    ws_path = OBS / "workspace.json"
    ws = load_json(ws_path)

    def strip_juggl(node):
        if isinstance(node, dict):
            if node.get("type") == "leaf":
                st = (node.get("state") or {}).get("type")
                if st in ("juggl_nodes", "juggl_style", "juggl"):
                    return None
            out = {}
            for k, v in node.items():
                nv = strip_juggl(v)
                if nv is not None:
                    out[k] = nv
            if "children" in out and isinstance(out["children"], list):
                out["children"] = [c for c in out["children"] if c is not None]
            return out
        if isinstance(node, list):
            return [x for x in (strip_juggl(i) for i in node) if x is not None]
        return node

    dump_json(ws_path, strip_juggl(ws))
    print("workspace juggl leaves stripped")

    # ---- move plugin .bak main.js out of plugins dir ----
    bak_root = OBS / "backups" / f"plugin-main-bak-{TS}"
    bak_root.mkdir(parents=True, exist_ok=True)
    moved = 0
    for p in (OBS / "plugins").rglob("main.js.*.bak"):
        dest = bak_root / f"{p.parent.name}__{p.name}"
        shutil.move(str(p), str(dest))
        moved += 1
    for p in (OBS / "plugins").rglob("data-backup*.json"):
        dest = bak_root / f"{p.parent.name}__{p.name}"
        shutil.move(str(p), str(dest))
        moved += 1
    print("moved bak files", moved, "->", bak_root)

    # ---- Style Settings empty data if missing (prevents some first-parse nags) ----
    ss_data = OBS / "plugins" / "obsidian-style-settings" / "data.json"
    if not ss_data.exists():
        dump_json(ss_data, {})
        print("style-settings data.json created empty")

    # ---- Minimal Theme Settings data if missing ----
    min_data = OBS / "plugins" / "obsidian-minimal-settings" / "data.json"
    if not min_data.exists():
        dump_json(
            min_data,
            {
                "lightStyle": "minimal-light",
                "darkStyle": "minimal-dark",
                "lightScheme": "minimal-default-light",
                "darkScheme": "minimal-default-dark",
                "editorFont": "",
                "lineHeight": 1.5,
                "lineWidth": 40,
                "lineWidthWide": 50,
                "maxWidth": 88,
                "textNormal": 16,
                "textSmall": 13,
                "underlineInternal": True,
                "underlineExternal": True,
                "frameStyle": "default",
                "frameBackground": False,
                "maximize": False,
                "trim": False,
                "bordersToggle": True,
            },
        )
        print("minimal-settings data.json created")

    # ---- agent-client minimal data if missing ----
    ac = OBS / "plugins" / "agent-client" / "data.json"
    if not ac.exists():
        dump_json(
            ac,
            {
                "agents": [],
                "defaultAgentId": "",
            },
        )
        print("agent-client data.json stub")

    # ---- Validate community-plugins all present with main.js ----
    enabled = load_json(OBS / "community-plugins.json")
    missing = []
    for pid in enabled:
        d = OBS / "plugins" / pid
        if not (d / "main.js").exists() or not (d / "manifest.json").exists():
            missing.append(pid)
    print("enabled plugins", len(enabled), "missing_files", missing)

    # ---- LRA version check ----
    lra = load_json(OBS / "plugins" / "obsidian-local-rest-api" / "manifest.json")
    lra_data = load_json(OBS / "plugins" / "obsidian-local-rest-api" / "data.json")
    print("LRA version", lra.get("version"), "insecure", lra_data.get("enableInsecureServer"))

    print("DONE")


if __name__ == "__main__":
    main()
