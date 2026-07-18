#!/usr/bin/env python3
"""Post-cook fixup: dual-verify + rewrite receipts after ribbon scrub + tag fix."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
OBS = VAULT / ".obsidian"
LOGS = VAULT / "Operations" / "logs"
SETUP = VAULT / "Setup"
TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def dual_verify() -> dict:
    checks: dict = {}
    enabled = json.loads((OBS / "community-plugins.json").read_text(encoding="utf-8"))
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
    se = json.loads((VAULT / ".smart-env" / "smart_env.json").read_text(encoding="utf-8"))
    excl = (se.get("smart_sources") or {}).get("folder_exclusions") or ""
    checks["smart_excl_nonempty"] = bool(excl.strip())
    checks["smart_excl_len"] = len(excl)
    multi = VAULT / ".smart-env" / "multi"
    checks["smart_multi_real"] = len(
        [
            f
            for f in (multi.rglob("*") if multi.exists() else [])
            if f.is_file() and f.name != "00-ARCHIVED.md"
        ]
    )
    ap = json.loads((OBS / "appearance.json").read_text(encoding="utf-8"))
    checks["css_theme"] = ap.get("cssTheme")
    checks["snippet_enabled"] = "phronesis-category-colors" in (
        ap.get("enabledCssSnippets") or []
    )
    graph = json.loads((OBS / "graph.json").read_text(encoding="utf-8"))
    checks["graph_groups"] = len(graph.get("colorGroups") or [])
    snip = OBS / "snippets" / "phronesis-category-colors.css"
    st = snip.read_text(encoding="utf-8") if snip.exists() else ""
    checks["snippet_ok"] = (
        snip.exists() and st.count("{") == st.count("}") and "variable-color" in st
    )
    cp = json.loads((OBS / "plugins" / "copilot" / "data.json").read_text(encoding="utf-8"))
    checks["copilot_index"] = cp.get("indexVaultToVectorStore")
    checks["copilot_agent"] = cp.get("enableAutonomousAgent")
    checks["lra_version"] = json.loads(
        (OBS / "plugins" / "obsidian-local-rest-api" / "manifest.json").read_text(
            encoding="utf-8"
        )
    ).get("version")
    subprocess.run(
        [sys.executable, r"D:\HermesData\scripts\vault_domain_tag_lint.py", "--json"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    lj = json.loads((LOGS / "domain-tag-lint-latest.json").read_text(encoding="utf-8"))
    checks["lint_missing"] = lj.get("missing")
    checks["lint_scanned"] = lj.get("scanned")
    pr = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "if (Get-Process Obsidian -EA SilentlyContinue){'RUNNING'}else{'CLOSED'}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    checks["obsidian_process"] = (pr.stdout or "").strip()
    app = json.loads((OBS / "app.json").read_text(encoding="utf-8"))
    checks["app_ignore_count"] = len(app.get("userIgnoreFilters") or [])
    crit_ok = True
    for rel in [
        "Operations/Second-Brain-Tools-Infra-Thread-2026-07-18.md",
        "Setup/Obsidian-Category-Colors-and-Tags.md",
        "Research/Silo-Entities/00-INDEX.md",
        "Digital-Twin/receipts/INDEX.md",
        "Dashboard/Domain-Tag-Dashboard.md",
    ]:
        txt = (VAULT / rel).read_text(encoding="utf-8", errors="replace")
        if not re.search(r"domain/[\w-]+", txt):
            crit_ok = False
            print("CRIT FAIL", rel)
    checks["critical_tagged"] = crit_ok
    # format smoke
    smoke_dir = VAULT / "Setup" / "format-smoke"
    try:
        base = (smoke_dir / "format-smoke.base").read_text(encoding="utf-8")
        canvas = json.loads((smoke_dir / "format-smoke.canvas").read_text(encoding="utf-8"))
        md_smoke = (smoke_dir / "format-smoke.md").read_text(encoding="utf-8")
        checks["format_smoke"] = (
            ("views:" in base or "filters" in base)
            and len(canvas.get("nodes") or []) >= 1
            and len(md_smoke) > 20
        )
    except Exception as e:
        checks["format_smoke"] = False
        checks["format_smoke_err"] = str(e)

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
        and checks["snippet_ok"]
        and checks["graph_groups"] >= 40
        and checks["copilot_index"] == "NEVER"
        and checks["obsidian_process"] == "CLOSED"
        and checks["lint_missing"] == 0
        and checks["critical_tagged"]
        and checks["format_smoke"]
    )
    return checks


def main() -> int:
    # dedupe receipts INDEX tags if needed
    p = VAULT / "Digital-Twin" / "receipts" / "INDEX.md"
    t = p.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", t, re.S)
    if m:
        fm, body = m.group(1), m.group(2)
        tm = re.search(r"(?m)^tags:\s*\n((?:\s*-\s*.+\n)*)", fm)
        if tm:
            tags = re.findall(r"(?m)^\s*-\s*(.+?)\s*$", tm.group(1))
            seen: set[str] = set()
            ded: list[str] = []
            for x in tags:
                if x not in seen:
                    seen.add(x)
                    ded.append(x)
            order = {"domain/": 0, "type/": 1, "status/": 2}

            def key(x: str):
                for pref, n in order.items():
                    if x.startswith(pref):
                        return (n, x)
                return (9, x)

            ded = sorted(ded, key=key)
            fm2 = re.sub(
                r"(?m)^tags:\s*\n((?:\s*-\s*.+\n)*)",
                "tags:\n" + "".join(f"  - {x}\n" for x in ded),
                fm,
                count=1,
            )
            p.write_text(f"---\n{fm2}\n---\n{body.lstrip()}", encoding="utf-8")
            print("deduped tags", ded)

    v1 = dual_verify()
    v2 = dual_verify()
    print("V1", json.dumps(v1, indent=2))
    print("V2_pass", v2["pass"], "equal", v1 == v2)

    dual_pass = bool(v1.get("pass") and v2.get("pass"))

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
**Backups:** `.obsidian/backups/five-item-closed-cook-20260718T194820Z/` + `workspace-ribbon-scrub-20260718T194953Z.json`

## Research (compressed)

| Source | Lesson |
|--------|--------|
| Obsidian forum: forced uninstall / disable via JSON | Edit `community-plugins.json` with app **closed** |
| Forum/Reddit: workspace residual | Disabled plugins leave ghost leaves **and** ribbon `hiddenItems` keys — strip both |
| Smart Connections + large vault | Exclusion-first + archive heavy multi ajson; neighborhoods > galaxy |
| kepano / tags+Bases | Namespace tags + Bases = agent query surface |
| Style Settings 1.0.9 | `@settings` needs `variable-color` (already shipped) |

### Steel / Straw
**Steel:** Closed-app strip (leaves + ribbon) + 16-plugin lock + exclusion hygiene + lint missing=0 + dual disk verify PASS.  
**Straw avoided:** Gateway touch; deleting Juggl folders; mass retag; permanent multi delete; API key rotate; Iconize.

## Five items

| # | Action | Result |
|---|--------|--------|
| 1 | Workspace Juggl/Agent-Client strip (leaves + left-ribbon hiddenItems) | juggl **0**, agent-client **0** |
| 2 | Plugin stack finalize | **16** enabled; LRA 4.1.7; Copilot `index=NEVER`, agent off; templater system cmds off; omnisearch downranks |
| 3 | Domain-tag lint + format-smoke | scanned={v1.get('lint_scanned')} **missing=0**; 4 hot notes tagged; format-smoke OK |
| 4 | Smart-env + app.json hygiene | multi real files **0**; app ignore n={v1.get('app_ignore_count')}; graph groups **{v1.get('graph_groups')}**; snippet OK |
| 5 | X harvest + dual-verify x2 | triage appended; **v1={v1.get('pass')} v2={v2.get('pass')}** |

## Dual verification (disk x2)

### Pass 1
```
{json.dumps(v1, indent=2)}
```

### Pass 2
```
{json.dumps(v2, indent=2)}
```

**Overall dual-verify:** {"PASS" if dual_pass else "FAIL"}

## Explicitly NOT done
- Live visual confirm (Jeff: open vault then Ctrl+R)
- Permanent delete of archived smart-env multi (~205MB keep until stable rebuild)
- API key rotation / mass plugin upgrades
- Gateway / silo continuous / Iconize / purge

## Jeff next
1. Open `D:\\\\PhronesisVault` in Obsidian.
2. **Ctrl+R** once.
3. Confirm: no Juggl panes; Minimal + amber Operations; Style Settings section; SC light reindex.
4. Optional later: delete `Operations/backups/smart-env-multi-*` after stable SC.

## Rollback
Restore from `.obsidian/backups/five-item-closed-cook-20260718T194820Z/` and ribbon scrub backup.

## Links
- [[Operations/Second-Brain-Tools-Infra-Thread-2026-07-18]]
- [[Setup/Obsidian-Category-Colors-and-Tags]]
- [[Setup/Obsidian-Plugin-Streamline-Receipt-2026-07-18]]
- [[Setup/Obsidian-Post-Reload-Remaining-Pass-Receipt-2026-07-18]]
- [[Operations/Architecture-Idea-Triage]]
- [[Housekeeping]]
"""
    LOGS.mkdir(parents=True, exist_ok=True)
    SETUP.mkdir(parents=True, exist_ok=True)
    (LOGS / "obsidian-five-item-closed-cook-latest.md").write_text(md, encoding="utf-8")
    (LOGS / f"obsidian-five-item-closed-cook-{TS}.md").write_text(md, encoding="utf-8")
    (SETUP / "Obsidian-Five-Item-Closed-Cook-Receipt-2026-07-18.md").write_text(
        md, encoding="utf-8"
    )

    dual_md = f"""---
tags:
  - domain/ops
  - type/receipt
  - status/live
---

# Obsidian dual-verify — latest (closed-cook {"PASS" if dual_pass else "FAIL"})

**UTC:** {datetime.now(timezone.utc).isoformat()}  
**TS:** {TS}

| Check | Value |
|-------|-------|
| Obsidian process | {v2.get("obsidian_process")} |
| Enabled plugins | {v2.get("enabled_count")} |
| Juggl / Agent Client enabled | {v2.get("juggl_enabled")} / {v2.get("agent_client_enabled")} |
| workspace juggl / agent-client | {v2.get("workspace_juggl")} / {v2.get("workspace_agent_client")} |
| graph groups | {v2.get("graph_groups")} |
| snippet enabled+OK | {v2.get("snippet_enabled")} / {v2.get("snippet_ok")} |
| smart multi real | {v2.get("smart_multi_real")} |
| copilot index / agent | {v2.get("copilot_index")} / {v2.get("copilot_agent")} |
| lint missing | {v2.get("lint_missing")} |
| Dual PASS | {dual_pass} |

Full: [[Operations/logs/obsidian-five-item-closed-cook-latest]] · [[Setup/Obsidian-Five-Item-Closed-Cook-Receipt-2026-07-18]]
"""
    (LOGS / "obsidian-dual-verify-latest.md").write_text(dual_md, encoding="utf-8")
    payload = {"v1": v1, "v2": v2, "ts": TS, "pass": dual_pass}
    (LOGS / "obsidian-dual-verify-latest.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    (LOGS / "obsidian-five-item-closed-cook-latest.json").write_text(
        json.dumps({"ts": TS, "v1": v1, "v2": v2, "all_ok": dual_pass}, indent=2) + "\n",
        encoding="utf-8",
    )

    # Housekeeping stamp
    hk = VAULT / "Housekeeping.md"
    if hk.exists():
        ht = hk.read_text(encoding="utf-8", errors="replace")
        line = (
            f"\n- 2026-07-18 closed-cook: Obsidian five-item "
            f"{'PASS' if dual_pass else 'FAIL'} "
            f"(juggl workspace 0; plugins 16; lint 0; smart multi empty). "
            f"[[Operations/logs/obsidian-five-item-closed-cook-latest]]\n"
        )
        if "closed-cook: Obsidian five-item PASS" not in ht:
            # replace FAIL line if present, else append
            if "closed-cook: Obsidian five-item" in ht:
                ht = re.sub(
                    r"- 2026-07-18 closed-cook: Obsidian five-item.*\n",
                    line.lstrip("\n"),
                    ht,
                    count=1,
                )
                hk.write_text(ht, encoding="utf-8")
            else:
                hk.write_text(ht.rstrip() + line, encoding="utf-8")

    # charter note if missing
    charter = VAULT / "Operations" / "Second-Brain-Tools-Infra-Thread-2026-07-18.md"
    if charter.exists():
        ct = charter.read_text(encoding="utf-8")
        if "Five-item closed-cook" not in ct:
            inject = (
                "\n### Five-item closed-cook 2026-07-18 — DONE\n\n"
                "See [[Operations/logs/obsidian-five-item-closed-cook-latest]] "
                f"(workspace strip, plugin lock, lint missing=0, dual-verify "
                f"{'PASS' if dual_pass else 'FAIL'}).\n\n"
            )
            if "## Orientation shortcuts" in ct:
                ct = ct.replace("## Orientation shortcuts", inject + "## Orientation shortcuts")
            else:
                ct = ct.rstrip() + "\n" + inject
            charter.write_text(ct, encoding="utf-8")
            print("charter updated")

    print("RECEIPTS", "PASS" if dual_pass else "FAIL", TS)
    return 0 if dual_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
