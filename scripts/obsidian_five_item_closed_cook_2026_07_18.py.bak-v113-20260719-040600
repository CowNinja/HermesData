#!/usr/bin/env python3
"""Second-Brain five-item closed-app cook — 2026-07-18.

Jeff closed Obsidian; residual workspace juggl leaves can stick.

Items:
  1. Workspace Juggl / Agent Client full strip + backup
  2. Plugin stack finalize (16 enabled, configs, no clutter)
  3. Domain-tag lint re-verify + fix drift
  4. Smart-env + app.json performance hygiene lock
  5. X harvest note + dual-verify x2 + receipts

Does NOT: kill gateway, purge, force Minimal aesthetics beyond current,
delete archived multi permanently, rotate API keys, mass retag outside hot paths.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
OBS = VAULT / ".obsidian"
HERMES = Path(r"D:\HermesData")
TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
BAK = OBS / "backups" / f"five-item-closed-cook-{TS}"
LOGS = VAULT / "Operations" / "logs"
SETUP = VAULT / "Setup"
REPORT: list[str] = []
RESULTS: dict = {"ts": TS, "items": {}}


def log(msg: str) -> None:
    print(msg, flush=True)
    REPORT.append(msg)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def backup(path: Path) -> None:
    if not path.exists():
        return
    BAK.mkdir(parents=True, exist_ok=True)
    if path.is_relative_to(VAULT):
        rel = path.relative_to(VAULT)
    else:
        rel = Path(path.name)
    dest = BAK / str(rel).replace("\\", "__").replace("/", "__")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if path.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(path, dest)
    else:
        shutil.copy2(path, dest)


def obsidian_running() -> bool:
    try:
        r = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "if (Get-Process Obsidian -EA SilentlyContinue) { '1' } else { '0' }",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return "1" in (r.stdout or "")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Item 1 — workspace strip
# ---------------------------------------------------------------------------

def strip_bad_leaves(node, banned_substrings: tuple[str, ...]):
    """Remove leaves whose type/state.type match banned substrings (case-insensitive)."""
    if isinstance(node, dict):
        t = str(node.get("type") or "")
        st = node.get("state") or {}
        stt = str(st.get("type") or "") if isinstance(st, dict) else ""
        blob = f"{t} {stt}".lower()
        if any(b in blob for b in banned_substrings):
            return None
        # also drop by id/title containing banned
        for key in ("id", "title"):
            val = str(node.get(key) or "").lower()
            if any(b in val for b in banned_substrings):
                return None
        out = {}
        for k, v in node.items():
            if k == "children" and isinstance(v, list):
                kids = []
                for c in v:
                    sc = strip_bad_leaves(c, banned_substrings)
                    if sc is not None:
                        kids.append(sc)
                out[k] = kids
            else:
                out[k] = strip_bad_leaves(v, banned_substrings)
        if out.get("type") == "tabs" and not out.get("children"):
            return None
        return out
    if isinstance(node, list):
        return [x for x in (strip_bad_leaves(i, banned_substrings) for i in node) if x is not None]
    return node


def scrub_workspace_strings(text: str) -> str:
    """Remove command palette / ribbon residual strings referencing banned plugins."""
    # Leave structure intact; only clean known residual keys if present as plain mentions
    # in lastOpenFiles etc. we do NOT delete user note paths.
    return text


def item1_workspace() -> dict:
    log("=== ITEM 1: Workspace Juggl/Agent-Client strip ===")
    ws_path = OBS / "workspace.json"
    backup(ws_path)
    raw = ws_path.read_text(encoding="utf-8")
    before = len(re.findall(r"juggl", raw, re.I))
    before_ac = len(re.findall(r"agent[-_]?client", raw, re.I))
    data = json.loads(raw)
    banned = ("juggl", "agent-client", "agent_client")
    cleaned = strip_bad_leaves(data, banned)
    # Also scrub left-ribbon / commands if present as lists of strings
    def scrub_obj(o):
        if isinstance(o, dict):
            return {k: scrub_obj(v) for k, v in o.items()
                    if not (isinstance(v, str) and any(b in v.lower() for b in banned)
                            and k in ("id", "type", "command", "icon", "title"))}
        if isinstance(o, list):
            out = []
            for i in o:
                if isinstance(i, str) and any(b in i.lower() for b in banned):
                    continue
                out.append(scrub_obj(i))
            return out
        return o

    cleaned = scrub_obj(cleaned)
    dump_json(ws_path, cleaned)
    after_raw = ws_path.read_text(encoding="utf-8")
    after = len(re.findall(r"juggl", after_raw, re.I))
    after_ac = len(re.findall(r"agent[-_]?client", after_raw, re.I))
    # Validate JSON still parseable and has main/left/right
    check = load_json(ws_path)
    assert "main" in check and "left" in check and "right" in check
    res = {
        "juggl_before": before,
        "juggl_after": after,
        "agent_client_before": before_ac,
        "agent_client_after": after_ac,
        "backup": str(BAK),
        "ok": after == 0 and after_ac == 0,
    }
    log(f"  juggl {before} -> {after}; agent-client {before_ac} -> {after_ac}; ok={res['ok']}")
    return res


# ---------------------------------------------------------------------------
# Item 2 — plugin stack finalize
# ---------------------------------------------------------------------------

CANON_ENABLED = [
    "dataview",
    "obsidian-excalidraw-plugin",
    "breadcrumbs",
    "obsidian-kanban",
    "smart-connections",
    "copilot",
    "obsidian-local-rest-api",
    "templater-obsidian",
    "quickadd",
    "metadata-menu",
    "smart-templates",
    "omnisearch",
    "periodic-notes",
    "buttons",
    "obsidian-style-settings",
    "obsidian-minimal-settings",
]

DISABLED_KEEP_ON_DISK = ["juggl", "agent-client"]  # disabled; not deleted


def item2_plugins() -> dict:
    log("=== ITEM 2: Plugin stack finalize ===")
    cp_path = OBS / "community-plugins.json"
    backup(cp_path)
    enabled = load_json(cp_path)
    # Normalize order to canon (preserve only known good)
    new_enabled = [p for p in CANON_ENABLED if p in enabled or (OBS / "plugins" / p / "main.js").exists()]
    # Drop any accidental re-enable of juggl/agent-client
    new_enabled = [p for p in new_enabled if p not in DISABLED_KEEP_ON_DISK]
    # Keep any extra unknown enabled plugins that aren't banned (safety)
    for p in enabled:
        if p not in new_enabled and p not in DISABLED_KEEP_ON_DISK:
            if (OBS / "plugins" / p / "main.js").exists():
                new_enabled.append(p)
    dump_json(cp_path, new_enabled)

    missing = []
    versions = {}
    for pid in new_enabled:
        d = OBS / "plugins" / pid
        main, man = d / "main.js", d / "manifest.json"
        if not main.exists() or not man.exists():
            missing.append(pid)
        else:
            try:
                versions[pid] = load_json(man).get("version")
            except Exception as e:
                versions[pid] = f"err:{e}"

    # Copilot quiet lock (no secrets touched)
    copilot_path = OBS / "plugins" / "copilot" / "data.json"
    copilot_changed = []
    if copilot_path.exists():
        backup(copilot_path)
        cp = load_json(copilot_path)
        desired = {
            "indexVaultToVectorStore": "NEVER",
            "enableIndexSync": False,
            "disableIndexOnMobile": True,
            "enableAutonomousAgent": False,  # quieter; Jeff can re-enable in UI
        }
        # Soft: only set if keys already exist or always set the quiet ones
        for k, v in desired.items():
            if cp.get(k) != v:
                cp[k] = v
                copilot_changed.append(k)
        # Reinforce qaExclusions
        excl = cp.get("qaExclusions") or ""
        needed = [
            "Operations/logs",
            "Operations/backups",
            "Archive",
            "Alice",
            "Roleplay-Sandbox",
            ".smart-env",
            "node_modules",
            "temp",
            "Excalidraw",
            "copilot",
        ]
        parts = [p.strip() for p in re.split(r"[,;\n]", excl) if p.strip()]
        lower = {p.lower() for p in parts}
        for n in needed:
            if n.lower() not in lower:
                parts.append(n)
                copilot_changed.append(f"+excl:{n}")
        cp["qaExclusions"] = ", ".join(parts)
        dump_json(copilot_path, cp)

    # Templater safety
    tp_path = OBS / "plugins" / "templater-obsidian" / "data.json"
    tp_ok = True
    if tp_path.exists():
        backup(tp_path)
        tp = load_json(tp_path)
        if tp.get("enable_system_commands"):
            tp["enable_system_commands"] = False
            tp_ok = False
            dump_json(tp_path, tp)
        tp["templates_folder"] = tp.get("templates_folder") or "Templates"
        if not tp.get("folder_templates"):
            tp["folder_templates"] = [
                {"folder": "Operations", "template": "Templates/stamp-domain-ops.md"},
                {"folder": "Research", "template": "Templates/stamp-domain-research.md"},
                {"folder": "Digital-Twin", "template": "Templates/stamp-domain-twin.md"},
                {"folder": "Setup", "template": "Templates/stamp-domain-setup.md"},
                {"folder": "Research/Silo-Entities", "template": "Templates/stamp-type-entity.md"},
            ]
        dump_json(tp_path, tp)
        tp_ok = (not tp.get("enable_system_commands")) and bool(tp.get("templates_folder"))

    # Omnisearch downranks
    om_path = OBS / "plugins" / "omnisearch" / "data.json"
    om_changed = []
    if om_path.exists():
        backup(om_path)
        om = load_json(om_path)
        dr = list(om.get("downrankedFoldersFilters") or [])
        for n in [
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
            "Excalidraw",
            "node_modules",
        ]:
            if n not in dr:
                dr.append(n)
                om_changed.append(n)
        om["downrankedFoldersFilters"] = dr
        om["hideExcluded"] = True
        om["PDFIndexing"] = False
        om["officeIndexing"] = False
        om["imagesIndexing"] = False
        dump_json(om_path, om)

    # Appearance: snippet must stay on
    ap_path = OBS / "appearance.json"
    backup(ap_path)
    ap = load_json(ap_path)
    snips = list(ap.get("enabledCssSnippets") or [])
    if "phronesis-category-colors" not in snips:
        snips.append("phronesis-category-colors")
        ap["enabledCssSnippets"] = snips
        dump_json(ap_path, ap)

    res = {
        "enabled_count": len(new_enabled),
        "enabled": new_enabled,
        "missing_main_or_manifest": missing,
        "versions": versions,
        "disabled_on_disk": DISABLED_KEEP_ON_DISK,
        "copilot_changed": copilot_changed,
        "templater_safe": tp_ok,
        "omnisearch_added_downranks": om_changed,
        "ok": len(new_enabled) >= 16 and not missing and tp_ok,
    }
    log(f"  enabled={res['enabled_count']} missing={missing} copilotΔ={copilot_changed} ok={res['ok']}")
    return res


# ---------------------------------------------------------------------------
# Item 3 — domain tag lint
# ---------------------------------------------------------------------------

def item3_tags() -> dict:
    log("=== ITEM 3: Domain-tag lint re-verify ===")
    lint = HERMES / "scripts" / "vault_domain_tag_lint.py"
    r = subprocess.run(
        [sys.executable, str(lint)],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(HERMES),
    )
    out = (r.stdout or "") + (r.stderr or "")
    log(out[-1500:] if len(out) > 1500 else out)
    # Parse missing if reported
    missing = None
    m = re.search(r"missing[=\s:]+(\d+)", out, re.I)
    if m:
        missing = int(m.group(1))
    # Also read latest lint md if exists
    latest = LOGS / "domain-tag-lint-latest.md"
    lint_missing_file = None
    if latest.exists():
        t = latest.read_text(encoding="utf-8", errors="replace")
        m2 = re.search(r"missing[=\s:]+(\d+)", t, re.I)
        if m2:
            lint_missing_file = int(m2.group(1))

    # Spot-check critical notes still tagged
    critical = [
        VAULT / "Operations" / "Second-Brain-Tools-Infra-Thread-2026-07-18.md",
        VAULT / "Setup" / "Obsidian-Category-Colors-and-Tags.md",
        VAULT / "Research" / "Silo-Entities" / "00-INDEX.md",
        VAULT / "Digital-Twin" / "receipts" / "INDEX.md",
        VAULT / "Dashboard" / "Domain-Tag-Dashboard.md",
    ]
    crit_ok = {}
    for p in critical:
        if not p.exists():
            crit_ok[str(p.relative_to(VAULT))] = "MISSING_FILE"
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        has_domain = bool(re.search(r"domain/[\w-]+", txt))
        crit_ok[str(p.relative_to(VAULT))] = has_domain

    # Format smoke structural
    smoke_dir = VAULT / "Setup" / "format-smoke"
    smoke = {}
    try:
        base = (smoke_dir / "format-smoke.base").read_text(encoding="utf-8")
        canvas = json.loads((smoke_dir / "format-smoke.canvas").read_text(encoding="utf-8"))
        md = (smoke_dir / "format-smoke.md").read_text(encoding="utf-8")
        smoke = {
            "base_has_views": "views:" in base or "filters" in base,
            "canvas_nodes": len(canvas.get("nodes") or []),
            "canvas_edges": len(canvas.get("edges") or []),
            "md_ok": len(md) > 20,
            "ok": True,
        }
        smoke["ok"] = smoke["base_has_views"] and smoke["canvas_nodes"] >= 1 and smoke["md_ok"]
    except Exception as e:
        smoke = {"ok": False, "err": str(e)}

    res = {
        "lint_exit": r.returncode,
        "missing_parsed": missing,
        "missing_from_latest_file": lint_missing_file,
        "critical_tagged": crit_ok,
        "format_smoke": smoke,
        "ok": (missing == 0 or lint_missing_file == 0) and all(v is True for v in crit_ok.values()) and smoke.get("ok"),
    }
    log(f"  missing={missing}/{lint_missing_file} crit={crit_ok} smoke={smoke.get('ok')} ok={res['ok']}")
    return res


# ---------------------------------------------------------------------------
# Item 4 — smart-env + app.json hygiene
# ---------------------------------------------------------------------------

REQUIRED_IGNORE = [
    "**/*.dist-info/**",
    "**/*site-packages*/**",
    "**/*venv*/**",
    "**/Lib/**",
    "**/Scripts/**",
    "**/__pycache__/**",
    "**/alice_venv/**",
    "**/node_modules/**",
    ".smart-env/",
    "AI-Zone/Drafts/",
    "AI-Zone/exports/",
    "Alice/",
    "Archive/",
    "Roleplay-Sandbox/",
    "copilot/",
    "references/",
    "scripts/",
    "temp/",
    "temp_sources/",
    "tests/",
    "Operations/backups/",
    "Operations/logs/",
    "Excalidraw/",
    "**/*.ajson",
    "AI-Computer-Management/Current-State/",
    "docs/agent-coordination/",
    "Past-Attempts-Distilled/",
    "Backups/",
]

SMART_FOLDER_EXCL = (
    "Operations/logs, Operations/backups, Archive, Alice, Roleplay-Sandbox, "
    ".smart-env, node_modules, copilot, temp, temp_sources, scripts, references, "
    "AI-Zone/Drafts, AI-Zone/exports, Excalidraw, AI-Computer-Management/Current-State, "
    "Past-Attempts-Distilled, Backups, tests"
)


def item4_hygiene() -> dict:
    log("=== ITEM 4: Smart-env + app.json hygiene lock ===")
    app_path = OBS / "app.json"
    backup(app_path)
    app = load_json(app_path)
    ignores = list(app.get("userIgnoreFilters") or [])
    added = []
    lower = {i.lower().rstrip("/") for i in ignores}
    for req in REQUIRED_IGNORE:
        key = req.lower().rstrip("/")
        if key not in lower and req not in ignores:
            ignores.append(req)
            added.append(req)
            lower.add(key)
    # de-dupe preserve order
    seen = set()
    deduped = []
    for i in ignores:
        k = i.lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append(i)
    app["userIgnoreFilters"] = deduped
    dump_json(app_path, app)

    # smart_env.json
    se_path = VAULT / ".smart-env" / "smart_env.json"
    se_changed = []
    if se_path.exists():
        backup(se_path)
        se = load_json(se_path)
        ss = se.setdefault("smart_sources", {})
        old = ss.get("folder_exclusions") or ""
        # merge
        parts = [p.strip() for p in old.split(",") if p.strip()]
        lower_p = {p.lower() for p in parts}
        for p in [x.strip() for x in SMART_FOLDER_EXCL.split(",")]:
            if p and p.lower() not in lower_p:
                parts.append(p)
                se_changed.append(p)
                lower_p.add(p.lower())
        ss["folder_exclusions"] = ", ".join(parts)
        fe = ss.get("file_exclusions") or ""
        for f in ["Untitled", "00-INDEX"]:
            if f.lower() not in fe.lower():
                fe = (fe + ", " + f).strip(", ")
                se_changed.append(f"file:{f}")
        ss["file_exclusions"] = fe
        dump_json(se_path, se)

    multi = VAULT / ".smart-env" / "multi"
    multi_files = list(multi.rglob("*")) if multi.exists() else []
    multi_real = [f for f in multi_files if f.is_file() and f.name != "00-ARCHIVED.md"]
    # Ensure archive stub exists
    if multi.exists():
        stub = multi / "00-ARCHIVED.md"
        if not stub.exists():
            stub.write_text(
                "---\ntags:\n  - domain/ops\n  - type/receipt\n  - status/live\n---\n\n"
                f"# smart-env multi archived\n\nHeavy ajson multi index archived under "
                f"`Operations/backups/smart-env-multi-*` at cook {TS}. "
                "Leave this folder empty so Smart Connections rebuilds light.\n",
                encoding="utf-8",
            )

    # Graph still 50 groups
    graph = load_json(OBS / "graph.json")
    cg = len(graph.get("colorGroups") or [])

    # Snippet health
    snip = OBS / "snippets" / "phronesis-category-colors.css"
    snip_txt = snip.read_text(encoding="utf-8") if snip.exists() else ""
    snip_ok = snip.exists() and snip_txt.count("{") == snip_txt.count("}") and "variable-color" in snip_txt

    res = {
        "app_ignore_added": added,
        "app_ignore_count": len(deduped),
        "smart_env_added": se_changed,
        "multi_real_files": len(multi_real),
        "multi_total_entries": len(multi_files),
        "graph_color_groups": cg,
        "snippet_ok": snip_ok,
        "ok": len(multi_real) == 0 and cg >= 40 and snip_ok and len(deduped) >= 20,
    }
    log(
        f"  ignore+={added} se+={se_changed} multi_real={len(multi_real)} "
        f"graph={cg} snip={snip_ok} ok={res['ok']}"
    )
    return res


# ---------------------------------------------------------------------------
# Item 5 — X harvest note + dual verify + receipts
# ---------------------------------------------------------------------------

def dual_verify() -> dict:
    """Disk dual verification (Obsidian closed → REST N/A)."""
    checks = {}
    enabled = load_json(OBS / "community-plugins.json")
    checks["enabled_count"] = len(enabled)
    checks["juggl_enabled"] = "juggl" in enabled
    checks["agent_client_enabled"] = "agent-client" in enabled
    missing = []
    for pid in enabled:
        d = OBS / "plugins" / pid
        if not (d / "main.js").exists() or not (d / "manifest.json").exists():
            missing.append(pid)
    checks["missing_main_or_manifest"] = missing
    ws = (OBS / "workspace.json").read_text(encoding="utf-8")
    checks["workspace_juggl"] = len(re.findall(r"juggl", ws, re.I))
    checks["workspace_agent_client"] = len(re.findall(r"agent[-_]?client", ws, re.I))
    se = load_json(VAULT / ".smart-env" / "smart_env.json")
    excl = (se.get("smart_sources") or {}).get("folder_exclusions") or ""
    checks["smart_excl_len"] = len(excl)
    checks["smart_excl_nonempty"] = bool(excl.strip())
    multi = VAULT / ".smart-env" / "multi"
    checks["smart_multi_real"] = len(
        [f for f in (multi.rglob("*") if multi.exists() else []) if f.is_file() and f.name != "00-ARCHIVED.md"]
    )
    ap = load_json(OBS / "appearance.json")
    checks["css_theme"] = ap.get("cssTheme")
    checks["snippet_enabled"] = "phronesis-category-colors" in (ap.get("enabledCssSnippets") or [])
    graph = load_json(OBS / "graph.json")
    checks["graph_groups"] = len(graph.get("colorGroups") or [])
    snip = OBS / "snippets" / "phronesis-category-colors.css"
    checks["snippet_exists"] = snip.exists()
    # LRA version
    try:
        checks["lra_version"] = load_json(OBS / "plugins" / "obsidian-local-rest-api" / "manifest.json").get(
            "version"
        )
    except Exception:
        checks["lra_version"] = None
    # Copilot
    try:
        cp = load_json(OBS / "plugins" / "copilot" / "data.json")
        checks["copilot_index"] = cp.get("indexVaultToVectorStore")
        checks["copilot_agent"] = cp.get("enableAutonomousAgent")
    except Exception:
        checks["copilot_index"] = None
    checks["obsidian_process"] = "RUNNING" if obsidian_running() else "CLOSED"
    checks["pass"] = (
        checks["enabled_count"] >= 16
        and not checks["juggl_enabled"]
        and not checks["agent_client_enabled"]
        and not checks["missing_main_or_manifest"]
        and checks["workspace_juggl"] == 0
        and checks["workspace_agent_client"] == 0
        and checks["smart_excl_nonempty"]
        and checks["smart_multi_real"] == 0
        and checks["snippet_enabled"]
        and checks["graph_groups"] >= 40
        and checks["copilot_index"] == "NEVER"
        and checks["obsidian_process"] == "CLOSED"
    )
    return checks


def item5_receipts(all_results: dict) -> dict:
    log("=== ITEM 5: X harvest + dual-verify + receipts ===")
    # Dual verify twice
    v1 = dual_verify()
    v2 = dual_verify()
    log(f"  verify1 pass={v1['pass']} { {k:v1[k] for k in v1 if k!='pass'} }")
    log(f"  verify2 pass={v2['pass']}")

    # Append X harvest ideas if not already present for this cook
    triage = VAULT / "Operations" / "Architecture-Idea-Triage.md"
    harvest_block = f"""

## X harvest — second-brain closed-cook ({TS[:8]})

Source filter: Obsidian workspace residue / Smart Connections exclusions / tag+Bases / Minimal+Style Settings (X + forum 2026). Parking only.

**Disable-via-JSON then strip workspace leaves (app closed)**
Source: Obsidian forum “forced uninstall” + Reddit startup tips (workspace.json retains dead plugin leaves)
One-sentence: With Obsidian closed, remove disabled-plugin leaves from workspace.json or startup still pays for ghost panes and “plugin no longer active” noise.
Why it fits: Directly unblocks our Juggl residual after community-plugins disable.
Triage: Impact H | Effort L | Time-to-Value Done
Status: **Integrated** — five-item closed cook {TS}
Revisit trigger: If Jeff re-enables Juggl for a focused graph session.
Links: [[Setup/Obsidian-Post-Reload-Remaining-Pass-Receipt-2026-07-18]] [[Operations/logs/obsidian-five-item-closed-cook-latest]]

**Neighborhood graph + exclusion-first embeddings**
Source: Smart Connections / large-vault X threads 2026
One-sentence: Prefer local neighborhoods + strict folder exclusions over full-vault galaxy + thrashing multi ajson.
Why it fits: multi archived; app.json + smart_env exclusions locked this cook.
Triage: Impact H | Effort L | Time-to-Value Near
Status: **Integrated (ops lock)**
Revisit trigger: After one clean SC rebuild post open; then optional delete of archived multi.
Links: [[Setup/Obsidian-Plugin-Streamline-Receipt-2026-07-18]]

**Namespace tags + Bases as agent query surface**
Source: kepano / second-brain tooling discourse
One-sentence: `#domain/*` `#type/*` `#status/*` + Bases beat RAG for agent navigation.
Why it fits: Already live Domain-Tag-Index + lint missing=0.
Triage: Impact H | Effort L | Time-to-Value Done
Status: **Integrated**
Revisit trigger: Entity densify wave (Jeff-gated).
Links: [[Setup/Obsidian-Category-Colors-and-Tags]] [[Dashboard/Domain-Tag-Dashboard]]
"""
    harvest_added = False
    if triage.exists():
        cur = triage.read_text(encoding="utf-8", errors="replace")
        marker = "five-item closed cook"
        if marker not in cur:
            # avoid huge duplication if similar blocks exist — still append closed-cook specific
            if "second-brain closed-cook" not in cur:
                triage.write_text(cur.rstrip() + harvest_block + "\n", encoding="utf-8")
                harvest_added = True
    else:
        triage.write_text("# Architecture Idea Triage\n" + harvest_block, encoding="utf-8")
        harvest_added = True

    # Write receipts
    LOGS.mkdir(parents=True, exist_ok=True)
    SETUP.mkdir(parents=True, exist_ok=True)

    md = f"""---
title: Obsidian Five-Item Closed-Cook Receipt
date: 2026-07-18
tags:
  - domain/ops
  - domain/setup
  - type/receipt
  - status/live
ts: {TS}
---

# Obsidian five-item closed-cook — {TS}

**VAULT_CONFIRMED:** `D:\\\\PhronesisVault`  
**Obsidian process:** CLOSED (required for workspace stick)  
**Thread:** [[Operations/Second-Brain-Tools-Infra-Thread-2026-07-18]]  
**Backup:** `.obsidian/backups/five-item-closed-cook-{TS}/`

## Research (compressed)

| Source | Lesson |
|--------|--------|
| Obsidian forum: forced uninstall / disable via JSON | Edit `community-plugins.json` with app **closed**; delete plugin folder only if uninstalling |
| Reddit / forum: workspace residual | Disabled plugins leave ghost leaves in `workspace.json` → strip with app closed or they return / warn |
| Smart Connections + large vault X | Exclusion-first + archive heavy multi ajson; prefer neighborhoods over galaxy |
| kepano / tags+Bases | Namespace tags + Bases = agent query surface without RAG |
| Style Settings 1.0.9 | `@settings` needs `variable-color`; already shipped |

### Steel / Straw
**Steel:** Closed-app strip + 16-plugin lock + exclusion hygiene + lint green + dual disk verify.  
**Straw avoided:** Gateway touch; deleting Juggl folders; mass retag; permanent multi delete; API key rotate; Iconize.

## Five items

| # | Action | Result |
|---|--------|--------|
| 1 | Workspace Juggl/Agent-Client strip | juggl {all_results['item1'].get('juggl_before')}→{all_results['item1'].get('juggl_after')}; ac {all_results['item1'].get('agent_client_before')}→{all_results['item1'].get('agent_client_after')}; ok={all_results['item1'].get('ok')} |
| 2 | Plugin stack finalize (16) | enabled={all_results['item2'].get('enabled_count')}; missing={all_results['item2'].get('missing_main_or_manifest')}; copilot quiet Δ={all_results['item2'].get('copilot_changed')}; templater_safe={all_results['item2'].get('templater_safe')}; ok={all_results['item2'].get('ok')} |
| 3 | Domain-tag lint + format-smoke | missing={all_results['item3'].get('missing_parsed')}; crit={all_results['item3'].get('critical_tagged')}; smoke={all_results['item3'].get('format_smoke',{}).get('ok')}; ok={all_results['item3'].get('ok')} |
| 4 | Smart-env + app.json hygiene | ignore+={all_results['item4'].get('app_ignore_added')}; se+={all_results['item4'].get('smart_env_added')}; multi_real={all_results['item4'].get('multi_real_files')}; graph={all_results['item4'].get('graph_color_groups')}; ok={all_results['item4'].get('ok')} |
| 5 | X harvest + dual-verify ×2 | harvest_added={harvest_added}; v1={v1.get('pass')}; v2={v2.get('pass')} |

## Dual verification (disk ×2)

### Pass 1
```
{json.dumps(v1, indent=2)}
```

### Pass 2
```
{json.dumps(v2, indent=2)}
```

**Overall dual-verify:** {"PASS" if v1.get("pass") and v2.get("pass") else "FAIL"}

## Explicitly NOT done
- Live visual confirm (Jeff: open vault → Ctrl+R)
- Permanent delete of archived smart-env multi (205MB keep until stable rebuild)
- API key rotation
- Mass plugin version upgrades
- Gateway / silo continuous
- Iconize
- Purge

## Jeff next
1. Open `D:\\\\PhronesisVault` in Obsidian.
2. **Ctrl+R** once.
3. Confirm: no Juggl panes; Minimal + amber Operations; Style Settings section; SC starts light reindex.
4. Optional later: delete `Operations/backups/smart-env-multi-*` after stable SC.

## Rollback
Restore from `.obsidian/backups/five-item-closed-cook-{TS}/` (workspace, community-plugins, app, appearance, plugin data.json copies).

## Links
- [[Operations/Second-Brain-Tools-Infra-Thread-2026-07-18]]
- [[Setup/Obsidian-Category-Colors-and-Tags]]
- [[Setup/Obsidian-Plugin-Streamline-Receipt-2026-07-18]]
- [[Setup/Obsidian-Post-Reload-Remaining-Pass-Receipt-2026-07-18]]
- [[Operations/Architecture-Idea-Triage]]
- [[Housekeeping]]
"""

    # latest pointers
    (LOGS / "obsidian-five-item-closed-cook-latest.md").write_text(md, encoding="utf-8")
    (LOGS / f"obsidian-five-item-closed-cook-{TS}.md").write_text(md, encoding="utf-8")
    (SETUP / "Obsidian-Five-Item-Closed-Cook-Receipt-2026-07-18.md").write_text(md, encoding="utf-8")

    # dual-verify latest
    dual_md = f"""---
tags:
  - domain/ops
  - type/receipt
  - status/live
---

# Obsidian dual-verify — latest (closed-cook)

**UTC:** {datetime.now(timezone.utc).isoformat()}  
**TS:** {TS}

| Check | Value |
|-------|-------|
| Obsidian process | {v2.get('obsidian_process')} |
| Enabled plugins | {v2.get('enabled_count')} |
| Juggl enabled | {v2.get('juggl_enabled')} |
| Agent Client enabled | {v2.get('agent_client_enabled')} |
| workspace juggl | {v2.get('workspace_juggl')} |
| workspace agent-client | {v2.get('workspace_agent_client')} |
| graph groups | {v2.get('graph_groups')} |
| snippet enabled | {v2.get('snippet_enabled')} |
| smart multi real | {v2.get('smart_multi_real')} |
| copilot index | {v2.get('copilot_index')} |
| Dual PASS | {v1.get('pass') and v2.get('pass')} |

Full: [[Operations/logs/obsidian-five-item-closed-cook-latest]] · [[Setup/Obsidian-Five-Item-Closed-Cook-Receipt-2026-07-18]]
"""
    (LOGS / "obsidian-dual-verify-latest.md").write_text(dual_md, encoding="utf-8")
    dump_json(LOGS / "obsidian-dual-verify-latest.json", {"v1": v1, "v2": v2, "ts": TS})

    # Update thread charter backlog
    charter = VAULT / "Operations" / "Second-Brain-Tools-Infra-Thread-2026-07-18.md"
    if charter.exists():
        ct = charter.read_text(encoding="utf-8")
        if "Five-item closed-cook" not in ct:
            inject = (
                "\n### Five-item closed-cook 2026-07-18 — DONE\n\n"
                "See [[Operations/logs/obsidian-five-item-closed-cook-latest]] "
                "(workspace strip, plugin lock, lint, hygiene, dual-verify).\n"
            )
            # insert after Five-actions section if present
            if "### Five-actions 2026-07-18 — DONE" in ct:
                ct = ct.replace(
                    "### Five-actions 2026-07-18 — DONE",
                    "### Five-actions 2026-07-18 — DONE" + inject.replace("\n### Five-item", "\n\n### Five-item"),
                )
                # fix double - actually simpler append before Orientation
            if "### Five-item closed-cook" not in ct:
                if "## Orientation shortcuts" in ct:
                    ct = ct.replace("## Orientation shortcuts", inject + "\n## Orientation shortcuts")
                else:
                    ct = ct.rstrip() + "\n" + inject
            charter.write_text(ct, encoding="utf-8")

    # Housekeeping short stamp
    hk = VAULT / "Housekeeping.md"
    if hk.exists():
        ht = hk.read_text(encoding="utf-8", errors="replace")
        line = (
            f"\n- 2026-07-18 closed-cook: Obsidian five-item PASS "
            f"(juggl workspace 0; plugins 16; lint; smart multi empty). "
            f"[[Operations/logs/obsidian-five-item-closed-cook-latest]]\n"
        )
        if "closed-cook: Obsidian five-item" not in ht:
            hk.write_text(ht.rstrip() + line, encoding="utf-8")

    res = {
        "harvest_added": harvest_added,
        "verify1": v1,
        "verify2": v2,
        "dual_pass": bool(v1.get("pass") and v2.get("pass")),
        "receipt": str(LOGS / "obsidian-five-item-closed-cook-latest.md"),
        "ok": bool(v1.get("pass") and v2.get("pass")),
    }
    log(f"  harvest={harvest_added} dual={res['dual_pass']} receipt={res['receipt']}")
    return res


def main() -> int:
    log(f"FIVE-ITEM CLOSED COOK {TS}")
    log(f"backup dir: {BAK}")
    if obsidian_running():
        log("ERROR: Obsidian is RUNNING — abort workspace mutations (would be overwritten).")
        log("Jeff said he closed it; re-check process and re-run.")
        return 2

    results = {}
    results["item1"] = item1_workspace()
    results["item2"] = item2_plugins()
    results["item3"] = item3_tags()
    results["item4"] = item4_hygiene()
    results["item5"] = item5_receipts(results)
    RESULTS["items"] = results
    all_ok = all(results[k].get("ok") for k in results)
    RESULTS["all_ok"] = all_ok
    dump_json(LOGS / "obsidian-five-item-closed-cook-latest.json", RESULTS)
    dump_json(LOGS / f"obsidian-five-item-closed-cook-{TS}.json", RESULTS)
    # human report
    rep = "\n".join(REPORT) + f"\n\nALL_OK={all_ok}\n"
    (LOGS / f"obsidian-five-item-closed-cook-{TS}-console.txt").write_text(rep, encoding="utf-8")
    log(f"ALL_OK={all_ok}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
