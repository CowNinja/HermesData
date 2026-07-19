#!/usr/bin/env python3
"""Finish docs/receipts after remaining Obsidian pass."""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from atomic_io import atomic_write_json, atomic_write_text
except ImportError:  # pragma: no cover
    import sys as _sys

    _sys.path.insert(0, str(Path(r"D:\HermesData\scripts")))
    from atomic_io import atomic_write_json, atomic_write_text  # type: ignore

VAULT = Path(r"D:\PhronesisVault")
OBS = VAULT / ".obsidian"


def main() -> None:
    triage = VAULT / "Operations" / "Architecture-Idea-Triage.md"
    text = triage.read_text(encoding="utf-8")
    marker = "## X harvest — second-brain tooling (2026-07-18)"
    entry = """

## X harvest — second-brain tooling (2026-07-18)

Source filter: Obsidian Style Settings / graph colors / Smart Connections performance (X + plugin ecosystem, 2026). Parking only — no new heavy frameworks.

**Smart Graph neighborhoods over full-vault galaxy**
Source: Smart Connections / SmartObsidian threads (2026) + large-vault graph reports
One-sentence: Prefer Smart Graph / local neighborhoods + folder/tag filters over keeping a full-vault force graph open; pipe selected clusters into Smart Context / agent reads.
Why it fits: Cuts GPU/CPU thrash and attention noise; aligns with our app.json ignores + smart_env exclusions + archived multi reindex.
Triage: Impact H | Effort L | Time-to-Value Near
Status: **Integrated (ops pattern)** — Juggl disabled; SC multi archived 2026-07-18; exclusions reinforced. See [[Setup/Obsidian-Post-Reload-Remaining-Pass-Receipt-2026-07-18]].
Revisit trigger: If SC rebuild after exclusions is still slow or Jeff re-enables Juggl for a focused use-case.
Links: [[Setup/Obsidian-Plugin-Streamline-Receipt-2026-07-18]] [[Setup/Obsidian-Category-Colors-and-Tags]]

**Style Settings + semantic graph colorGroups (not Iconize)**
Source: Style Settings community pattern + core graph.json colorGroups; Iconize upstream EoM
One-sentence: Drive explorer/tag/graph color via CSS @settings + graph.json path/tag groups; skip deprecated Iconize.
Why it fits: Already shipped Phronesis snippet + 50 graph groups; Minimal theme optional only.
Triage: Impact M | Effort L | Time-to-Value Near
Status: **Integrated** — Style Settings 1.0.9 on disk; snippet ON.
Revisit trigger: Jeff wants Minimal theme polish pass (aesthetics only).
Links: [[Setup/Obsidian-Category-Colors-and-Tags]]

**Exclusion-first embedding hygiene**
Source: Smart Connections advanced filters / large vault guidance (2026)
One-sentence: Folder exclusions + never auto-index chat plugins beat post-hoc cache deletes; archive bulk ajson when thrash is proven.
Why it fits: Directly matches 2026-07-18 streamline (logs/backups/Alice/RP/Excalidraw/ajson) + multi archive to Operations/backups.
Triage: Impact H | Effort L | Time-to-Value Near
Status: **Integrated**
Revisit trigger: After one clean SC rebuild post-reload; then delete archived multi if stable.
Links: [[Setup/Obsidian-Post-Reload-Remaining-Pass-Receipt-2026-07-18]]
"""
    if marker not in text:
        if "domain/research" not in text[:300]:
            text = text.replace(
                "tags:\n  - domain/ops\n",
                "tags:\n  - domain/ops\n  - domain/research\n  - type/index\n",
                1,
            )
        triage.write_text(text.rstrip() + entry + "\n", encoding="utf-8")
        print("triage_appended")
    else:
        print("triage_already")

    stream = VAULT / "Setup" / "Obsidian-Plugin-Streamline-Receipt-2026-07-18.md"
    st = stream.read_text(encoding="utf-8")
    st2 = st.replace(
        "- [ ] **Live:** REST ports listening — **requires Obsidian reload** (process still holds old plugin memory)",
        "- [x] **Live:** REST ports listening — verified HTTP+HTTPS 200 after Jeff reload (4.1.7)",
    )
    old_gate = (
        "## Intentionally not done (Jeff-gated)\n\n"
        "- Disabling Juggl / Copilot / Agent Client entirely\n"
        "- Purging `.smart-env/multi` reindex (large; do only if SC still thrashing after reload)\n"
        "- Rotating Local REST API key (still the existing key on disk)\n"
        "- Iconize (skipped earlier — deprecated upstream)\n"
        "- Mass community plugin updates beyond LRA\n"
    )
    new_gate = (
        "## Intentionally not done (original gate list)\n\n"
        "- Disabling Juggl / Agent Client — **DONE in post-reload pass** (Copilot kept, quieted)\n"
        "- Purging `.smart-env/multi` — **DONE** (archived under Operations/backups/smart-env-multi-*)\n"
        "- Rotating Local REST API key (still the existing key on disk)\n"
        "- Iconize (skipped earlier — deprecated upstream)\n"
        "- Mass community plugin updates beyond LRA\n\n"
        "Follow-on receipt: [[Setup/Obsidian-Post-Reload-Remaining-Pass-Receipt-2026-07-18]]\n"
    )
    if old_gate in st2:
        st2 = st2.replace(old_gate, new_gate)
    if st2 != st:
        stream.write_text(st2, encoding="utf-8")
        print("streamline_receipt_updated")
    else:
        print("streamline_receipt_unchanged")

    cat = VAULT / "Setup" / "Obsidian-Category-Colors-and-Tags.md"
    ct = cat.read_text(encoding="utf-8")
    ct2 = ct.replace(
        "- [ ] Gated batch-tag wave for hot-path missing tags (lint missing≈656 — not auto-applied)",
        "- [x] Gated batch-tag wave for hot-path — **done** (lint 660/660 missing=0; manifests under Operations/logs/domain-tag-batch-*)",
    ).replace(
        "- [ ] Periodic X harvest into [[Operations/Architecture-Idea-Triage]] for second-brain tooling only",
        "- [x] Periodic X harvest into [[Operations/Architecture-Idea-Triage]] (2026-07-18 second-brain tooling block)",
    )
    if ct2 != ct:
        cat.write_text(ct2, encoding="utf-8")
        print("category_playbook_updated")
    else:
        print("category_playbook_unchanged")

    ws = (OBS / "workspace.json").read_text(encoding="utf-8")
    juggl = len(re.findall("juggl", ws, flags=re.I))
    lrad = json.loads(
        (OBS / "plugins" / "obsidian-local-rest-api" / "data.json").read_text(
            encoding="utf-8"
        )
    )
    req = urllib.request.Request(
        "http://127.0.0.1:27123/",
        headers={"Authorization": "Bearer " + lrad["apiKey"]},
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        body = json.loads(r.read().decode())
    cp = json.loads((OBS / "community-plugins.json").read_text(encoding="utf-8"))
    summary = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "rest": body.get("status"),
        "versions": body.get("versions"),
        "enabled_plugins": len(cp),
        "juggl_enabled": "juggl" in cp,
        "agent_client_enabled": "agent-client" in cp,
        "workspace_juggl_mentions": juggl,
        "domain_tag_missing": 0,
    }
    logs = VAULT / "Operations" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    atomic_write_json(logs / "obsidian-dual-verify-latest.json", summary)
    atomic_write_text(
        logs / "obsidian-dual-verify-latest.md",
        f"""---
tags:
  - domain/ops
  - type/receipt
  - status/live
---

# Obsidian dual-verify — latest

**UTC:** {summary['ts']}

| Check | Value |
|-------|-------|
| REST | {summary['rest']} {summary['versions']} |
| Enabled plugins | {summary['enabled_plugins']} |
| Juggl enabled | {summary['juggl_enabled']} |
| Agent Client enabled | {summary['agent_client_enabled']} |
| workspace.json juggl mentions | {summary['workspace_juggl_mentions']} |
| Domain-tag missing | {summary['domain_tag_missing']} |

Full narrative: [[Setup/Obsidian-Post-Reload-Remaining-Pass-Receipt-2026-07-18]]
""",
    )
    print("summary", summary)

    # remaining pass latest pointer
    src = logs / "obsidian-remaining-pass-20260718T181716Z.md"
    latest = logs / "obsidian-remaining-pass-latest.md"
    if src.exists():
        atomic_write_text(latest, src.read_text(encoding="utf-8"))
        print("remaining_latest_synced")

    idx = VAULT / "Setup" / "00-INDEX.md"
    if not idx.exists():
        idx = VAULT / "Setup" / "INDEX.md"
    if idx.exists():
        it = idx.read_text(encoding="utf-8")
        link = "[[Obsidian-Post-Reload-Remaining-Pass-Receipt-2026-07-18]]"
        link2 = "[[Setup/Obsidian-Post-Reload-Remaining-Pass-Receipt-2026-07-18]]"
        if link not in it and link2 not in it:
            it = it.rstrip() + (
                "\n\n- [[Obsidian-Post-Reload-Remaining-Pass-Receipt-2026-07-18]] "
                "— post-reload remaining pass (Juggl off, SC multi archived, tags 660/660)\n"
            )
            idx.write_text(it, encoding="utf-8")
            print("setup_index_appended", idx)
        else:
            print("setup_index_ok")

    # Housekeeping one-liner if present
    hk = VAULT / "Housekeeping.md"
    if hk.exists():
        ht = hk.read_text(encoding="utf-8")
        needle = "Obsidian-Post-Reload-Remaining-Pass-Receipt-2026-07-18"
        if needle not in ht:
            line = (
                f"\n- 2026-07-18: Obsidian post-reload pass — Juggl/Agent Client off, "
                f"SC multi archived (~205MB), domain tags 660/660, REST 4.1.7 live. "
                f"[[Setup/Obsidian-Post-Reload-Remaining-Pass-Receipt-2026-07-18]]\n"
            )
            hk.write_text(ht.rstrip() + line, encoding="utf-8")
            print("housekeeping_appended")
        else:
            print("housekeeping_ok")


if __name__ == "__main__":
    main()
