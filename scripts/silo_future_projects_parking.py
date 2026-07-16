#!/usr/bin/env python3
"""Future projects parking lot — list / add / set-status / readiness (unpark check).

Jeff 2026-07-14: single inventory for future silo-powered projects.
Silo focus remains personal gold; products stay parked until green light.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

CFG = Path(r"D:\HermesData\config\future_projects_parking.json")
VAULT_LOT = Path(
    r"D:\PhronesisVault\Operations\Future-Projects-Parking-Lot-CANONICAL-2026-07-14.md"
)
SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\silo-parking-readiness-latest.md")

# Map silo_depends_on tokens → shelf probes under K silo
FUEL_MAP = {
    "Medical-Records": SILO / "Medical-Records",
    "Navy-Service": SILO / "Navy-Service",
    "Core-Personal/Family": SILO / "Core-Personal" / "Family",
    "Digital-Footprint": SILO / "Digital-Footprint",
    "me": SILO / "Core-Personal",
    "Booksbloom": SILO
    / "Core-Personal"
    / "Projects"
    / "from-g-drive"
    / "Booksbloom",
    "WSWTR": SILO / "Core-Personal" / "Projects",
    "Keepers": SILO / "Core-Personal" / "Projects",
    "wpd-text-extract": SILO / "Core-Personal" / "Projects",
    "music_catalog_only": Path(r"D:\HermesData\state"),
    "Takeout": Path(r"D:\Takeout"),
    "D: Documents": Path(r"D:\Documents"),
    "CloudSync": Path(r"D:\CloudSync"),
    "USB": Path(r"E:\\"),
}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load() -> dict:
    return json.loads(CFG.read_text(encoding="utf-8"))


def save(doc: dict) -> None:
    doc["updated"] = utc()
    CFG.parent.mkdir(parents=True, exist_ok=True)
    CFG.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def shelf_ready(token: str) -> dict:
    p = FUEL_MAP.get(token)
    if p is None:
        # try direct under silo
        cand = SILO / token.replace("/", "\\")
        p = cand
    exists = p.exists() if p else False
    n_files = 0
    if exists and p.is_dir():
        try:
            # bounded sample count
            for i, _ in enumerate(p.rglob("*")):
                if i >= 200:
                    n_files = 200
                    break
                if _.is_file():
                    n_files += 1
        except Exception:
            n_files = -1
    elif exists and p.is_file():
        n_files = 1
    ok = exists and (n_files > 0 or (p and p.is_dir() and exists))
    return {
        "token": token,
        "path": str(p) if p else None,
        "exists": exists,
        "sample_files": n_files,
        "ok": bool(ok),
    }


def cmd_list(doc: dict, status: str | None) -> int:
    projects = doc.get("projects") or []
    if status:
        projects = [p for p in projects if p.get("status") == status]
    projects = sorted(projects, key=lambda p: -int(p.get("priority") or 0))
    print(f"doctrine: {doc.get('doctrine', '')[:100]}")
    print(f"focus_now: {', '.join(doc.get('focus_now') or [])}")
    print(f"count: {len(projects)}")
    for p in projects:
        print(
            f"  [{p.get('status'):12}] p={p.get('priority'):3}  {p.get('id'):24}  {p.get('title')}"
        )
        deps = p.get("silo_depends_on") or []
        if deps:
            print(f"             fuel: {', '.join(deps)}")
    print(f"vault: {VAULT_LOT}")
    return 0


def cmd_add(doc: dict, pid: str, title: str, priority: int, notes: str) -> int:
    projects = doc.setdefault("projects", [])
    if any(p.get("id") == pid for p in projects):
        print(json.dumps({"error": "exists", "id": pid}))
        return 1
    projects.append(
        {
            "id": pid,
            "title": title,
            "status": "idea",
            "priority": priority,
            "silo_depends_on": [],
            "stub": None,
            "triggers": [title],
            "notes": notes or "parked via silo_future_projects_parking.py",
        }
    )
    save(doc)
    print(json.dumps({"added": pid, "status": "idea", "config": str(CFG)}))
    print("Also add a row to Future-Projects-Parking-Lot-CANONICAL + optional PROJECT-STUB-*.md")
    return 0


def cmd_status(doc: dict, pid: str, status: str) -> int:
    for p in doc.get("projects") or []:
        if p.get("id") == pid:
            p["status"] = status
            save(doc)
            print(json.dumps({"id": pid, "status": status}))
            return 0
    print(json.dumps({"error": "not_found", "id": pid}))
    return 1


def cmd_readiness(doc: dict, pid: str | None) -> int:
    """Unpark readiness: fuel shelves present on K (or next source paths)."""
    projects = doc.get("projects") or []
    if pid:
        projects = [p for p in projects if p.get("id") == pid]
    rows = []
    for p in sorted(projects, key=lambda x: -int(x.get("priority") or 0)):
        fuels = [shelf_ready(t) for t in (p.get("silo_depends_on") or [])]
        ready_n = sum(1 for f in fuels if f["ok"])
        total = len(fuels) or 1
        pct = round(100.0 * ready_n / total, 1)
        can_unpark = pct >= 80 and p.get("status") in (
            "bookmarked",
            "idea",
            "queued_source",
            "parked",
        )
        # active projects report fuel health only
        if p.get("status") == "active":
            can_unpark = False
        rows.append(
            {
                "id": p.get("id"),
                "status": p.get("status"),
                "priority": p.get("priority"),
                "fuel_ready_pct": pct,
                "can_unpark_suggest": can_unpark and ready_n == total,
                "fuels": fuels,
            }
        )
    # write vault receipt
    lines = [
        f"# Parking lot readiness — {utc()}",
        "",
        "| Project | Status | Fuel % | Unpark suggest |",
        "|---------|--------|-------:|:--------------:|",
    ]
    for r in rows:
        flag = "YES" if r["can_unpark_suggest"] else "no"
        lines.append(
            f"| `{r['id']}` | {r['status']} | {r['fuel_ready_pct']} | {flag} |"
        )
    lines += [
        "",
        "Unpark still requires Jeff green light — readiness is technical fuel only.",
        f"Config: `{CFG}`",
        f"Canon: `{VAULT_LOT}`",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"receipt": str(RECEIPT), "projects": rows}, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Future projects parking lot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list")
    p_list.add_argument("--status", default=None)
    p_add = sub.add_parser("add")
    p_add.add_argument("--id", required=True)
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--priority", type=int, default=50)
    p_add.add_argument("--notes", default="")
    p_st = sub.add_parser("set-status")
    p_st.add_argument("--id", required=True)
    p_st.add_argument("--status", required=True)
    p_rd = sub.add_parser("readiness", help="unpark fuel check (read-only)")
    p_rd.add_argument("--id", default=None)
    args = ap.parse_args()
    doc = load()
    if args.cmd == "list":
        return cmd_list(doc, args.status)
    if args.cmd == "add":
        return cmd_add(doc, args.id, args.title, args.priority, args.notes)
    if args.cmd == "set-status":
        return cmd_status(doc, args.id, args.status)
    if args.cmd == "readiness":
        return cmd_readiness(doc, args.id)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
