#!/usr/bin/env python3
"""Silo segment CLI — list / init / status for World-3 sub-projects.

Codifies Jeff 2026-07-18: four worlds walls + expandable segments inside K silo.
Jeff-first train; rabbit-hole templates on demand; 4D graph stubs in vault.

Usage:
  python silo_segment_cli.py list
  python silo_segment_cli.py status
  python silo_segment_cli.py init --id my_rabbit --title "My rabbit hole"
  python silo_segment_cli.py show jeff_life_twin
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

CFG = Path(r"D:/HermesData/config/silo_segments.yaml")
STATE = Path(r"D:/HermesData/state/segments")
VAULT_OPS = Path(r"D:/PhronesisVault/Operations")
GRAPHS = VAULT_OPS / "graphs"
FOUR_WORLDS = VAULT_OPS / "Four-Worlds-Silo-Architecture-CANONICAL-2026-07-10.md"
STUB_TEMPLATE = VAULT_OPS / "templates" / "SEGMENT-PROJECT-STUB-TEMPLATE.md"
GRAPH_TEMPLATE = VAULT_OPS / "templates" / "SEGMENT-4D-GRAPH-TEMPLATE.md"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_cfg() -> dict:
    if not CFG.is_file():
        raise SystemExit(f"missing {CFG}")
    text = CFG.read_text(encoding="utf-8")
    if yaml:
        return yaml.safe_load(text)
    # minimal fallback: refuse without pyyaml
    raise SystemExit("PyYAML required for silo_segment_cli")


def save_cfg(data: dict) -> None:
    if not yaml:
        raise SystemExit("PyYAML required")
    CFG.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def ensure_templates() -> None:
    VAULT_OPS.mkdir(parents=True, exist_ok=True)
    GRAPHS.mkdir(parents=True, exist_ok=True)
    (VAULT_OPS / "templates").mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    if not STUB_TEMPLATE.is_file():
        STUB_TEMPLATE.write_text(
            """# PROJECT STUB — {title}

**Segment id:** `{id}`  
**Status:** {status} · **Priority:** {priority}  
**World:** 3 (K data silo bulk) · CNS maps stay world 2  
**Four Worlds:** [[Operations/Four-Worlds-Silo-Architecture-CANONICAL-2026-07-10]]  
**Segments:** [[Operations/Silo-Segment-Infrastructure-CANONICAL-2026-07-18]]

## Purpose

{notes}

## Walls

| Layer | Path rule |
|-------|-----------|
| Bulk evidence | `K:/Phronesis-Sovereign/Personal-Digital-Silo/` shelves below |
| CNS / ops | `D:/PhronesisVault/Operations/` this stub + 4D map |
| Runtime | `D:/HermesData/state/segments/{id}/` |
| RP | **Never** — world 4 only |

## Shelves (world 3)

{shelves}

## Twin scopes

`{twin_scopes}`

## 4D graph

Map: [[{graph_4d_link}]]

| Axis | Use |
|------|-----|
| T Time | eras, valid_from/to |
| P Place | addresses, bases |
| W Who | people, aliases |
| A Artifact | paths, hashes, provenance |

## Train policy

- Jeff-first global default: only `jeff_life_twin` has `train_default: true` unless Jeff unparks.
- This segment train_default: **{train_default}**

## Rabbit-hole entry checklist

1. Confirm bulk stays on K (no vault dump)
2. Add/adjust `twin_scopes` in `config/silo_segments.yaml`
3. Grow 4D map with *sourced* edges only
4. Optional: parking lot id link
5. Activate `train_default` only on green light

## Next concrete steps

- [ ] 
""",
            encoding="utf-8",
        )
    if not GRAPH_TEMPLATE.is_file():
        GRAPH_TEMPLATE.write_text(
            """# 4D Graph — {title}

**Segment:** `{id}` · **World 2 CNS map** (not bulk)  
**Axes:** T time · P place · W who · A artifact  
**Rule:** No invented people/dates/books. Evidence = path, registry, or labeled source.

Updated: {updated}

## T — Time nodes

| When | Node | Evidence |
|------|------|----------|
| | | |

## P — Place nodes

| Place | Role | Era |
|-------|------|-----|
| | | |

## W — Who nodes

```
(person tree)
```

## A — Artifact anchors (K paths)

| Artifact | Path / hash | Links (W/P/T) |
|----------|-------------|-----------------|
| | | |

## Edges

| From | Type | To | Evidence |
|------|------|-----|----------|
| | | | |

Edge types: authored, about_person, lived_at, valid_during, succeeded_by, related_to, supports_twin, cataloged_as, derived_from, same_as_alias

## Open questions

- 
""",
            encoding="utf-8",
        )


def cmd_list(data: dict) -> int:
    segs = data.get("segments") or {}
    rows = sorted(segs.values(), key=lambda s: -int(s.get("priority") or 0))
    print(f"{'priority':>8}  {'status':<14}  {'id':<22}  title")
    for s in rows:
        print(
            f"{int(s.get('priority') or 0):>8}  {str(s.get('status')):<14}  {s.get('id'):<22}  {s.get('title')}"
        )
    return 0


def cmd_show(data: dict, sid: str) -> int:
    s = (data.get("segments") or {}).get(sid)
    if not s:
        print(json.dumps({"error": "not_found", "id": sid}))
        return 1
    print(json.dumps(s, indent=2))
    return 0


def cmd_status(data: dict) -> int:
    """Lightweight status: config presence + stub/graph files + registry scopes hint."""
    ensure_templates()
    segs = data.get("segments") or {}
    out = {"at": utc(), "segments": []}
    for sid, s in sorted(segs.items(), key=lambda kv: -int(kv[1].get("priority") or 0)):
        stub = Path(s["cns_stub"]) if s.get("cns_stub") else None
        g4 = Path(str(s["graph_4d"])) if s.get("graph_4d") else None
        # normalize graph path if relative wikilink style
        if g4 and not g4.is_absolute():
            g4 = VAULT_OPS / g4.name
        rec = {
            "id": sid,
            "status": s.get("status"),
            "priority": s.get("priority"),
            "train_default": s.get("train_default"),
            "stub_exists": bool(stub and stub.is_file()),
            "graph_exists": bool(g4 and g4.is_file()),
            "twin_scopes": s.get("twin_scopes"),
        }
        out["segments"].append(rec)
    state_path = STATE / "segment_status_latest.json"
    state_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    receipt = VAULT_OPS / "logs" / "silo-segment-status-latest.md"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Silo segment status — {out['at']}",
        "",
        "| id | status | pri | train | stub | 4d | scopes |",
        "|----|--------|----:|:-----:|:----:|:--:|--------|",
    ]
    for r in out["segments"]:
        lines.append(
            f"| {r['id']} | {r['status']} | {r['priority']} | {r['train_default']} | "
            f"{'Y' if r['stub_exists'] else '·'} | {'Y' if r['graph_exists'] else '·'} | "
            f"{','.join(r.get('twin_scopes') or [])} |"
        )
    lines += [
        "",
        f"Config: `{CFG}`",
        "[[Operations/Silo-Segment-Infrastructure-CANONICAL-2026-07-18]]",
        "",
    ]
    receipt.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(out, indent=2))
    print(f"receipt={receipt}")
    return 0


def _fill(tmpl: str, **kw) -> str:
    out = tmpl
    for k, v in kw.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def cmd_init(data: dict, sid: str, title: str, notes: str) -> int:
    ensure_templates()
    sid = re.sub(r"[^a-z0-9_]", "_", sid.lower()).strip("_")
    if not sid:
        print("bad id")
        return 2
    segs = data.setdefault("segments", {})
    if sid in segs:
        print(json.dumps({"error": "exists", "id": sid}))
        return 1
    stub_path = VAULT_OPS / f"PROJECT-STUB-{title.replace(' ', '-')[:60]}-Segment.md"
    graph_path = GRAPHS / f"{sid}-4d.md"
    seg = {
        "id": sid,
        "title": title,
        "status": "infrastructure",
        "priority": 25,
        "twin_scopes": [],
        "shelves": [],
        "land_focus": False,
        "train_default": False,
        "cns_stub": str(stub_path).replace("\\", "/"),
        "graph_4d": str(graph_path).replace("\\", "/"),
        "parking_id": None,
        "notes": notes or "Spawned from silo_segment_cli init",
    }
    segs[sid] = seg
    data["updated"] = utc()[:10]
    # write stub + graph from templates
    stub_t = STUB_TEMPLATE.read_text(encoding="utf-8")
    graph_t = GRAPH_TEMPLATE.read_text(encoding="utf-8")
    shelves = "_TBD — add K shelves_"
    stub_path.write_text(
        _fill(
            stub_t,
            title=title,
            id=sid,
            status="infrastructure",
            priority=25,
            notes=seg["notes"],
            shelves=shelves,
            twin_scopes="[]",
            graph_4d_link=f"Operations/graphs/{sid}-4d",
            train_default=False,
        ),
        encoding="utf-8",
    )
    graph_path.write_text(
        _fill(graph_t, title=title, id=sid, updated=utc()[:10]),
        encoding="utf-8",
    )
    (STATE / sid).mkdir(parents=True, exist_ok=True)
    (STATE / sid / "README.md").write_text(
        f"# segment `{sid}` runtime\n\nWorld 1 state only. Bulk on K. Maps in vault.\n",
        encoding="utf-8",
    )
    save_cfg(data)
    print(
        json.dumps(
            {
                "created": sid,
                "stub": str(stub_path),
                "graph_4d": str(graph_path),
                "config": str(CFG),
            },
            indent=2,
        )
    )
    return 0


def cmd_ensure_core_stubs(data: dict) -> int:
    """Create missing stubs/graphs for configured core segments (idempotent)."""
    ensure_templates()
    stub_t = STUB_TEMPLATE.read_text(encoding="utf-8")
    graph_t = GRAPH_TEMPLATE.read_text(encoding="utf-8")
    created = []
    for sid, s in (data.get("segments") or {}).items():
        stub = Path(s["cns_stub"]) if s.get("cns_stub") else None
        g4 = Path(s["graph_4d"]) if s.get("graph_4d") else None
        if stub and not stub.is_file():
            shelves = "\n".join(f"- `{x}`" for x in (s.get("shelves") or [])) or "_TBD_"
            stub.parent.mkdir(parents=True, exist_ok=True)
            stub.write_text(
                _fill(
                    stub_t,
                    title=s.get("title") or sid,
                    id=sid,
                    status=s.get("status"),
                    priority=s.get("priority"),
                    notes=s.get("notes") or "",
                    shelves=shelves,
                    twin_scopes=json.dumps(s.get("twin_scopes") or []),
                    graph_4d_link=(
                        f"Operations/graphs/{Path(str(g4)).stem}"
                        if g4
                        else "Operations/graphs"
                    ),
                    train_default=s.get("train_default"),
                ),
                encoding="utf-8",
            )
            created.append(str(stub))
        if g4 and not g4.is_file():
            # don't overwrite BooksBloom existing rich graph if path differs
            g4.parent.mkdir(parents=True, exist_ok=True)
            if not g4.is_file():
                g4.write_text(
                    _fill(
                        graph_t,
                        title=s.get("title") or sid,
                        id=sid,
                        updated=utc()[:10],
                    ),
                    encoding="utf-8",
                )
                created.append(str(g4))
        (STATE / sid).mkdir(parents=True, exist_ok=True)
    print(json.dumps({"ensured": created, "count": len(created)}, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_show = sub.add_parser("show")
    p_show.add_argument("id")
    sub.add_parser("status")
    p_init = sub.add_parser("init")
    p_init.add_argument("--id", required=True)
    p_init.add_argument("--title", required=True)
    p_init.add_argument("--notes", default="")
    sub.add_parser("ensure-core")
    args = ap.parse_args()
    data = load_cfg()
    if args.cmd == "list":
        return cmd_list(data)
    if args.cmd == "show":
        return cmd_show(data, args.id)
    if args.cmd == "status":
        return cmd_status(data)
    if args.cmd == "init":
        return cmd_init(data, args.id, args.title, args.notes)
    if args.cmd == "ensure-core":
        return cmd_ensure_core_stubs(data)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
