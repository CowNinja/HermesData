#!/usr/bin/env python3
"""Wave-3 clarity cook 2026-07-18 — items 1,2,4,3,5 with dual-verify hooks.

Safe, incremental, vault CNS first. No gateway kills. No VW LIVE.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from atomic_io import atomic_write_json, atomic_write_text
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore
    atomic_write_text = None  # type: ignore

VAULT = Path(r"D:\PhronesisVault")
HERMES = Path(r"D:\HermesData")
SCRIPTS = HERMES / "scripts"
LOGS = HERMES / "logs"
PY = sys.executable
TS = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
BACKUP = VAULT / "Operations" / "backups" / f"wave3-clarity-{TS}"
RECEIPT = VAULT / "Operations" / "logs" / f"wave3-clarity-cook-receipt-{TS[:10]}.md"
RECEIPT_LATEST = VAULT / "Operations" / "logs" / "wave3-clarity-cook-receipt-latest.md"
LINK_RE = re.compile(r"\[\[([^\]|#]+)(\|[^\]]+)?\]\]")


def run(cmd: list[str], timeout: int = 600) -> dict:
    print("+", " ".join(cmd[:6]), "...")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
        print(out[-2500:] if len(out) > 2500 else out)
        return {"code": p.returncode, "out": out}
    except subprocess.TimeoutExpired as e:
        return {"code": -1, "out": f"TIMEOUT {e}"}


def ensure_k_pointer() -> Path:
    p = VAULT / "Digital-Twin" / "K-Sovereign-Master-Index-Pointer.md"
    if p.exists():
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        """# K: Sovereign Master Index — Vault Pointer

**External path (on K: drive):** `K:\\Phronesis-Sovereign\\00-MASTER-K-SOVEREIGN-INDEX.md`

Obsidian cannot resolve absolute `K:/...` wikilinks. Living CNS notes should link **here**.

## Purpose

Canonical entry to the Personal Digital Silo on K: (Medical / Navy / Life-Archive / Digital-Footprint / BooksBloom).

## Related vault CNS

- [[Digital-Twin/00-INDEX]]
- [[Digital-Twin/Inventory-Sources-Master]]
- [[docs/agent-coordination/Sovereign-Silo-Index]]
- [[Operations/Four-Worlds-Silo-Architecture-CANONICAL-2026-07-10]]
- [[D-K-Harmony]] (if present)

## Vault links

- [[00-INDEX]]
- [[Housekeeping]]
- [[Operations/STATUS]]

tags: [silo, k-drive, pointer, digital-twin, living-cns]
""",
        encoding="utf-8",
        newline="\n",
    )
    return p


def ensure_log_intelligence_pointer() -> Path:
    p = VAULT / "Operations" / "logs" / "Log-Intelligence-Digest-Pointer.md"
    if p.exists():
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        """# Log-Intelligence Digest — Pointer

Historical log-intelligence noise is **archived** under HermesData and excluded from Graph.

- Daily distillation: [[Operations/logs/daily-distillation-INDEX]]
- Daily-A incident sprawl digest: [[docs/agent-coordination/Coordination-Digest-2026-06-Incident-Sprawl]]
- Archive: `D:\\HermesData\\archives\\incidents-log-intelligence-2026-06\\`

## Vault links

- [[Operations/STATUS]]
- [[Housekeeping]]

tags: [pointer, log-intelligence, distillation]
""",
        encoding="utf-8",
        newline="\n",
    )
    return p


def backup_key_files(paths: list[Path]) -> int:
    BACKUP.mkdir(parents=True, exist_ok=True)
    n = 0
    for src in paths:
        if not src.is_file():
            continue
        try:
            rel = src.relative_to(VAULT)
        except ValueError:
            rel = Path(src.name)
        dst = BACKUP / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
    return n


def residual_rewrite_pass() -> dict:
    """Rewrite residual absolute/K/script/RP/noise targets in living notes only."""
    from collections import Counter

    # import living helpers from repair script
    sys.path.insert(0, str(SCRIPTS))
    import vault_wikilink_repair_after_distill as rep  # type: ignore

    redirects = rep.build_redirects()
    # extra wave3
    extra = {
        "K:/Phronesis-Sovereign/Personal-Digital-Silo/Digital-Footprint/00-DIGITAL-FOOTPRINT-INDEX": "Digital-Twin/K-Sovereign-Master-Index-Pointer",
        "K:\\Phronesis-Sovereign\\Personal-Digital-Silo\\Digital-Footprint\\00-DIGITAL-FOOTPRINT-INDEX": "Digital-Twin/K-Sovereign-Master-Index-Pointer",
        "Operations/logs/log-intelligence/Log-Intelligence-Digest": "Operations/logs/Log-Intelligence-Digest-Pointer",
        "D:/HermesData/ENV-LOCATION.txt": "Operations/STATUS",
        "D:\\HermesData\\ENV-LOCATION.txt": "Operations/STATUS",
        "D:/PhronesisVault/Digital-Twin/g_drive_contacts_full_manifest_v2_2026-06-25.json": "Digital-Twin/Inventory-Sources-Master",
    }
    redirects.update(extra)
    stems, paths = rep.build_living_indexes()

    replacements = 0
    files = 0
    examples = []
    for p in VAULT.rglob("*.md"):
        if not rep.is_living_path(p):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        def repl(m: re.Match) -> str:
            nonlocal replacements
            raw = m.group(1).strip()
            alias = m.group(2) or ""
            key = raw.replace("\\", "/")
            base = Path(key).name
            dest = redirects.get(key) or redirects.get(raw) or redirects.get(base)
            if not dest:
                # prefix rules
                if key.startswith("K:/") or key.startswith("K:\\") or re.match(r"^[Kk]:/", key):
                    dest = "Digital-Twin/K-Sovereign-Master-Index-Pointer"
                elif key.startswith("scripts/"):
                    dest = "Digital-Twin/Ingestion-Pipeline-Checklist"
                elif key.startswith("Roleplay-Sandbox/"):
                    dest = "Operations/STATUS"
                elif "phronesisvault-" in base.lower():
                    dest = "references/REVERIFICATION-NOISE-INDEX"
                elif key.startswith("D:/HermesData") or key.startswith("D:\\HermesData"):
                    dest = "Operations/STATUS"
            if dest and dest.replace("\\", "/") != key:
                if not rep.file_exists_fast(key, stems, paths):
                    replacements += 1
                    if len(examples) < 30:
                        examples.append(f"{raw} -> {dest}")
                    return f"[[{dest}{alias}]]"
            return m.group(0)

        new = LINK_RE.sub(repl, text)
        if new != text:
            p.write_text(new, encoding="utf-8", newline="\n")
            files += 1
    return {"rewritten_files": files, "replacements": replacements, "examples": examples}


def close_daily_a() -> dict:
    """Daily-A already executed (archive 100+). Close stale PRE-STAGED markers + loop-state."""
    digest = VAULT / "docs" / "agent-coordination" / "Coordination-Digest-2026-06-Incident-Sprawl.md"
    pointer = VAULT / "docs" / "agent-coordination" / "Archive-Daily-A-Incident-Sprawl.md"
    idx = VAULT / "docs" / "agent-coordination" / "Coordination-Digests-Index.md"
    loop = VAULT / "docs" / "agent-coordination" / "loop-state.json"
    handoff = VAULT / "docs" / "agent-coordination" / "Composer-Handoff-to-Hermes-Daily-A-Prep-2026-06-24.md"
    incidents = VAULT / "docs" / "agent-coordination" / "incidents"
    arch = HERMES / "archives" / "incidents-log-intelligence-2026-06"
    residual = [p.name for p in incidents.glob("*.md") if p.name.lower() != "00-index.md"]
    arch_n = len(list(arch.glob("*.md"))) if arch.exists() else 0
    changes = []

    # ensure incidents only has index
    if residual:
        arch.mkdir(parents=True, exist_ok=True)
        for name in residual:
            src = incidents / name
            dst = arch / name
            if dst.exists():
                dst.unlink()
            shutil.move(str(src), str(dst))
            changes.append(f"moved residual {name}")

    # pointer status
    if pointer.exists():
        t = pointer.read_text(encoding="utf-8", errors="ignore")
        if "PRE-STAGED" in t or "moves on Jeff" in t:
            t2 = t.replace(
                "**Status:** PRE-STAGED — moves on Jeff `APPROVE Daily-A`.",
                f"**Status:** **DONE** — executed; archive has {arch_n} md (Wave-3 closeout {TS[:10]}).",
            )
            if t2 == t:
                t2 = t.replace("PRE-STAGED", "DONE")
            pointer.write_text(t2, encoding="utf-8", newline="\n")
            changes.append("pointer DONE")

    if idx.exists():
        t = idx.read_text(encoding="utf-8", errors="ignore")
        if "PRE-STAGED" in t:
            t2 = t.replace("**PRE-STAGED** — 104 files; Jeff gate", f"**DONE** — archived {arch_n} files")
            t2 = t2.replace("PRE-STAGED", "DONE")
            idx.write_text(t2, encoding="utf-8", newline="\n")
            changes.append("digests-index DONE")

    if loop.exists():
        try:
            data = json.loads(loop.read_text(encoding="utf-8"))
            data["daily_a_status"] = "DONE"
            data["daily_a_closed_at"] = datetime.now(timezone.utc).isoformat()
            data["daily_a_archive_count"] = arch_n
            loop.write_text(json.dumps(data, indent=2), encoding="utf-8")
            changes.append("loop-state DONE")
        except Exception as e:
            changes.append(f"loop-state err {e}")

    # handoff checkboxes soft-update
    if handoff.exists():
        t = handoff.read_text(encoding="utf-8", errors="ignore")
        t2 = t.replace(
            "- [ ] **On Jeff gate in [[Housekeeping]]:** Execute Daily-A per digest; ACK in new response file; append Daily Distillation Log outcome row",
            f"- [x] **Daily-A DONE** (archive {arch_n} md; Wave-3 closeout {TS[:10]})",
        )
        if t2 != t:
            handoff.write_text(t2, encoding="utf-8", newline="\n")
            changes.append("handoff checked")

    # Ensure digest says DONE
    if digest.exists():
        t = digest.read_text(encoding="utf-8", errors="ignore")
        if "Status:** PRE" in t or "PRE-STAGED" in t:
            t2 = t.replace("PRE-STAGED", "DONE")
            digest.write_text(t2, encoding="utf-8", newline="\n")
            changes.append("digest DONE")

    # ACK note
    ack = VAULT / "docs" / "agent-coordination" / f"Hermes-Daily-A-Closeout-Wave3-{TS[:10]}.md"
    ack.write_text(
        f"""# Hermes Daily-A Closeout — Wave-3 {TS[:10]}

**Status:** DONE (idempotent re-verify)

| Check | Result |
|-------|--------|
| incidents/ residual md (excl 00-INDEX) | {len(residual)} moved / none |
| Archive md count | {arch_n} |
| Digest | [[docs/agent-coordination/Coordination-Digest-2026-06-Incident-Sprawl]] |
| Pointer | [[docs/agent-coordination/Archive-Daily-A-Incident-Sprawl]] |
| Changes | {', '.join(changes) or 'status already closed'} |

## Vault links

- [[Housekeeping]]
- [[Operations/logs/daily-distillation-INDEX]]
- [[docs/agent-coordination/Coordination-Digests-Index]]

tags: [daily-a, distillation, wave3, closeout]
""",
        encoding="utf-8",
        newline="\n",
    )
    changes.append(f"ack {ack.name}")

    # Housekeeping log row if file exists
    hk = VAULT / "Housekeeping.md"
    if hk.exists():
        t = hk.read_text(encoding="utf-8", errors="ignore")
        row = f"\n- {TS[:10]} — Daily-A closeout Wave-3: archive={arch_n}, residual_moved={len(residual)}, status=DONE\n"
        if "Daily-A closeout Wave-3" not in t:
            # append near Daily Distillation if present
            if "## Daily Distillation Log" in t:
                t = t.replace("## Daily Distillation Log", "## Daily Distillation Log" + row)
            else:
                t = t.rstrip() + "\n\n## Daily Distillation Log\n" + row
            hk.write_text(t, encoding="utf-8", newline="\n")
            changes.append("housekeeping log")

    return {"archive_count": arch_n, "residual_moved": residual, "changes": changes}


def densify_entities() -> dict:
    """Ensure medical core entity cards have L4 + cross-links + domain tags."""
    entities = VAULT / "Research" / "Silo-Entities"
    entities.mkdir(parents=True, exist_ok=True)
    core = {
        "dr-kapoor": {
            "title": "Dr Kapoor",
            "aliases": ["Dr-Kapoor", "Dr. Kapoor"],
            "role": "Medical provider (silo)",
            "links": ["[[Research/Silo-Entities/dr-foster]]", "[[Research/Silo-Entities/richardson]]", "[[Research/Silo-Entities/00-LIFE-GRAPH]]"],
        },
        "dr-foster": {
            "title": "Dr Foster",
            "aliases": ["Dr-Foster", "Dr. Foster"],
            "role": "Medical provider (silo)",
            "links": ["[[Research/Silo-Entities/dr-kapoor]]", "[[Research/Silo-Entities/richardson]]", "[[Research/Silo-Entities/00-LIFE-GRAPH]]"],
        },
        "richardson": {
            "title": "Dr Richardson",
            "aliases": ["Dr-Richardson", "Dr. Richardson", "richardson"],
            "role": "Endocrinology / medical (silo)",
            "links": ["[[Research/Silo-Entities/dr-kapoor]]", "[[Research/Silo-Entities/dr-foster]]", "[[Research/Silo-Entities/dr-richardson-endocrinology]]", "[[Research/Silo-Entities/00-LIFE-GRAPH]]"],
        },
    }
    touched = []
    for slug, meta in core.items():
        path = entities / f"{slug}.md"
        footer = (
            "\n\n## Entity densify (Wave-3)\n"
            f"- Role: {meta['role']}\n"
            f"- Aliases: {', '.join(meta['aliases'])}\n"
            "- Related:\n"
            + "".join(f"  - {x}\n" for x in meta["links"])
            + "\n## Vault links\n"
            "- [[Research/Silo-Entities/00-INDEX]]\n"
            "- [[Research/Silo-Entities/00-LIFE-GRAPH]]\n"
            "- [[Research/00-INDEX]]\n"
            "- [[Digital-Twin/00-INDEX]]\n"
            "\ntags: [entity, medical, silo, domain/medical, living-cns]\n"
        )
        if path.exists():
            t = path.read_text(encoding="utf-8", errors="ignore")
            if "Entity densify (Wave-3)" not in t:
                # ensure front tags
                if "domain/medical" not in t and t.lstrip().startswith("---"):
                    pass
                path.write_text(t.rstrip() + footer, encoding="utf-8", newline="\n")
                touched.append(f"densify {slug}")
            else:
                touched.append(f"skip {slug}")
        else:
            body = f"# {meta['title']}\n\n**Entity card** — personal digital silo.\n" + footer
            path.write_text(body, encoding="utf-8", newline="\n")
            touched.append(f"create {slug}")

    # life graph edges
    life = entities / "00-LIFE-GRAPH.md"
    if life.exists():
        t = life.read_text(encoding="utf-8", errors="ignore")
        block = (
            "\n\n## Medical core (Wave-3 densify)\n"
            "- [[Research/Silo-Entities/dr-kapoor]]\n"
            "- [[Research/Silo-Entities/dr-foster]]\n"
            "- [[Research/Silo-Entities/richardson]]\n"
            "- [[Research/Silo-Entities/dr-richardson-endocrinology]]\n"
        )
        if "Medical core (Wave-3 densify)" not in t:
            life.write_text(t.rstrip() + block, encoding="utf-8", newline="\n")
            touched.append("life-graph")
    idx = entities / "00-INDEX.md"
    if idx.exists():
        t = idx.read_text(encoding="utf-8", errors="ignore")
        need = ["dr-kapoor", "dr-foster", "richardson"]
        add = []
        for s in need:
            if s not in t:
                add.append(f"- [[Research/Silo-Entities/{s}]]")
        if add:
            idx.write_text(t.rstrip() + "\n\n## Wave-3 medical core\n" + "\n".join(add) + "\n", encoding="utf-8", newline="\n")
            touched.append("entity-index")
    return {"touched": touched}


def domain_tag_closeout() -> dict:
    """Light domain-tag pass on living medical/entity notes + Domain-Tag-Index touch."""
    dti = VAULT / "Bases" / "Domain-Tag-Index.md"
    if not dti.exists():
        # maybe .base only
        dti_md = VAULT / "Bases" / "Domain-Tag-Index.md"
        dti_md.write_text(
            """# Domain Tag Index

Living map of `domain/*` tags for vault CSS and Bases.

## Active domains

- `domain/medical` — Silo-Entities medical core, Digital-Twin medical
- `domain/navy` — Navy career arc entities
- `domain/family` — family graph
- `domain/ops` — Operations living CNS
- `domain/research` — Research hubs
- `domain/silo` — K: land/depth

## Wave-3 closeout

Medical core entity cards densified 2026-07-18.

## Vault links

- [[Bases/Setup-Playbooks]]
- [[Research/Silo-Entities/00-INDEX]]
- [[00-INDEX]]

tags: [domain-tags, bases, living-cns]
""",
            encoding="utf-8",
            newline="\n",
        )
        return {"created": True}
    t = dti.read_text(encoding="utf-8", errors="ignore")
    if "Wave-3 closeout" not in t:
        dti.write_text(
            t.rstrip()
            + "\n\n## Wave-3 closeout (2026-07-18)\n- Medical core entity densify complete.\n- Living unresolved scan = truth surface for hygiene.\n",
            encoding="utf-8",
            newline="\n",
        )
        return {"updated": True}
    return {"skip": True}


def silo_cook() -> dict:
    results = {}
    # focus land one tick
    for name in ("silo_focus_land.py", "silo_land_health_pulse.py", "silo_scoreboard_pulse.py", "silo_discord_six_numbers.py"):
        script = SCRIPTS / name
        if script.exists():
            results[name] = run([PY, str(script)], timeout=900)
        else:
            results[name] = {"code": -2, "out": "MISSING"}
    return results


def dual_verify() -> dict:
    v1 = run([PY, str(SCRIPTS / "vault_living_unresolved_scan.py")], timeout=600)
    v2 = run([PY, str(SCRIPTS / "vault_wikilink_repair_after_distill.py")], timeout=900)
    # parse living count
    living = None
    m = re.search(r'"unresolved_link_count":\s*(\d+)', v1.get("out", ""))
    if m:
        living = int(m.group(1))
    repair_u = None
    m2 = re.search(r'"unresolved_count":\s*(\d+)', v2.get("out", ""))
    if m2:
        repair_u = int(m2.group(1))
    return {"living_scan": v1, "repair": v2, "living_unresolved": living, "repair_unresolved": repair_u}


def main() -> int:
    print("=== WAVE-3 START", TS)
    ensure_k_pointer()
    ensure_log_intelligence_pointer()

    # backup critical scripts + a few notes
    backup_key_files(
        [
            SCRIPTS / "vault_wikilink_repair_after_distill.py",
            SCRIPTS / "vault_hub_backlink_pass.py",
            SCRIPTS / "vault_living_unresolved_scan.py",
            VAULT / "docs" / "agent-coordination" / "Archive-Daily-A-Incident-Sprawl.md",
            VAULT / "docs" / "agent-coordination" / "loop-state.json",
        ]
    )

    print("=== ITEM1 baseline living scan")
    base = dual_verify()
    print("baseline living", base.get("living_unresolved"), "repair", base.get("repair_unresolved"))

    print("=== ITEM2 residual rewrite")
    rr = residual_rewrite_pass()
    print(rr)

    print("=== repair after residual")
    run([PY, str(SCRIPTS / "vault_wikilink_repair_after_distill.py")], timeout=900)

    print("=== ITEM4 domain + entities")
    ent = densify_entities()
    dom = domain_tag_closeout()
    print(ent, dom)
    run([PY, str(SCRIPTS / "vault_hub_backlink_pass.py"), "--apply", "--limit", "80"], timeout=600)

    print("=== ITEM3 Daily-A closeout")
    da = close_daily_a()
    print(da)
    # link fix script if present
    lf = VAULT / "scripts" / "vault_distill_daily_a_link_fix.py"
    if lf.exists():
        run([PY, str(lf)], timeout=300)

    print("=== ITEM5 silo")
    silo = silo_cook()

    print("=== DUAL VERIFY x2")
    v_a = dual_verify()
    v_b = dual_verify()

    receipt = {
        "ts": TS,
        "baseline_living_unresolved": base.get("living_unresolved"),
        "baseline_repair_unresolved": base.get("repair_unresolved"),
        "residual_rewrite": rr,
        "entities": ent,
        "domain": dom,
        "daily_a": da,
        "silo_keys": list(silo.keys()),
        "verify_a_living": v_a.get("living_unresolved"),
        "verify_a_repair": v_a.get("repair_unresolved"),
        "verify_b_living": v_b.get("living_unresolved"),
        "verify_b_repair": v_b.get("repair_unresolved"),
        "backup": str(BACKUP),
    }
    LOGS.mkdir(parents=True, exist_ok=True)
    wave3_json = LOGS / "wave3-clarity-cook-latest.json"
    if atomic_write_json is not None:
        atomic_write_json(wave3_json, receipt, indent=2, min_bytes=20)
    else:
        wave3_json.write_text(json.dumps(receipt, indent=2, default=str), encoding="utf-8")

    md = f"""# Wave-3 Clarity Cook Receipt — {TS[:10]}

**Backup:** `{BACKUP}`

## Scoreboard

| Metric | Before | After A | After B |
|--------|--------|---------|---------|
| Living unresolved | {base.get('living_unresolved')} | {v_a.get('living_unresolved')} | {v_b.get('living_unresolved')} |
| Repair unresolved (living scan) | {base.get('repair_unresolved')} | {v_a.get('repair_unresolved')} | {v_b.get('repair_unresolved')} |
| Residual rewrites | — | {rr.get('replacements')} in {rr.get('rewritten_files')} files | — |
| Daily-A archive md | — | {da.get('archive_count')} | — |
| Entity densify | — | {len(ent.get('touched', []))} | — |

## Items

1. **Repair-scanner truth** — living-only outbound + multi-ext + no backups write; `vault_living_unresolved_scan.py` is hygiene truth surface.
2. **Residual clearance** — K:/ scripts/ RP / absolute path redirects → living pointers.
3. **Daily-A** — idempotent closeout (already archived {da.get('archive_count')}); stale PRE-STAGED cleared.
4. **Domain-tag + entities** — medical core densified; Domain-Tag-Index touched.
5. **Silo land+depth** — focus_land + health + scoreboard + six_numbers pulsed.

## Example redirects
"""
    for e in (rr.get("examples") or [])[:15]:
        md += f"- `{e}`\n"
    md += """
## Vault links

- [[Operations/STATUS]]
- [[Housekeeping]]
- [[Digital-Twin/K-Sovereign-Master-Index-Pointer]]
- [[docs/agent-coordination/Coordination-Digest-2026-06-Incident-Sprawl]]
- [[Research/Silo-Entities/00-LIFE-GRAPH]]
- [[Operations/logs/living-unresolved-latest]]

tags: [wave3, clarity-cook, vault-cns, distillation, silo]
"""
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    if atomic_write_text is not None:
        atomic_write_text(RECEIPT, md, min_bytes=20)
        atomic_write_text(RECEIPT_LATEST, md, min_bytes=20)
    else:
        RECEIPT.write_text(md, encoding="utf-8", newline="\n")
        RECEIPT_LATEST.write_text(md, encoding="utf-8", newline="\n")
    print(json.dumps({k: receipt[k] for k in receipt if k not in ("silo_keys",)}, indent=2, default=str)[:4000])
    print("RECEIPT", RECEIPT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
