#!/usr/bin/env python3
"""Phase 8b B1 VLAN recommendations -- read-only, from native device count."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

VAULT = Path(r"D:\PhronesisVault")
DEVICES_JSON = VAULT / "Operations" / "logs" / "network-devices.json"
INVENTORY = VAULT / "docs" / "agent-coordination" / "home-network-inventory.md"
OUT_JSON = VAULT / "Operations" / "logs" / "network-vlan-b1.json"


def _inventory_has_hardware() -> bool:
    if not INVENTORY.is_file():
        return False
    filled = 0
    skip = {"", "8090, 8091, 8642, 3001, 9119, 8188", "Main LAN"}
    for line in INVENTORY.read_text(encoding="utf-8").splitlines():
        if "|" not in line or line.strip().startswith("|--"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 2:
            continue
        field, value = parts[0], parts[-1]
        if field in ("Field", "Subnet", "Purpose", "Value", "Notes"):
            continue
        if value in skip or value.lower().startswith("e.g."):
            continue
        filled += 1
    return filled >= 3


def build_recommendations(device_count: int, gateway: str) -> List[Dict[str, str]]:
    recs: List[Dict[str, str]] = []
    recs.append({
        "id": "vlan10_trusted",
        "vlan": "10",
        "purpose": "Jeff PCs + Hermes host",
        "action": "Keep :8090-8642 on trusted wired LAN only",
    })
    if device_count >= 15:
        recs.append({
            "id": "vlan20_iot",
            "vlan": "20",
            "purpose": "Smart home / cameras / bulbs",
            "action": "Isolate IoT; block route to VLAN 10 and Hermes ports",
        })
    if device_count >= 8:
        recs.append({
            "id": "vlan30_guest",
            "vlan": "30",
            "purpose": "Visitor WiFi",
            "action": "Guest SSID isolated from RFC1918 trusted subnet",
        })
    recs.append({
        "id": "dns_filter",
        "vlan": "all",
        "purpose": "Perimeter",
        "action": "NextDNS or AdGuard on gateway " + (gateway or "192.168.1.1"),
    })
    recs.append({
        "id": "upnp_off",
        "vlan": "all",
        "purpose": "Router hardening",
        "action": "Disable UPnP on gateway if enabled",
    })
    return recs


def main() -> int:
    data: Dict[str, Any] = {}
    if DEVICES_JSON.is_file():
        data = json.loads(DEVICES_JSON.read_text(encoding="utf-8"))
    device_count = len(data.get("devices") or [])
    gateway = str(data.get("gateway") or "192.168.1.1")
    report = {
        "module": "8b_vlan_b1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "inventory_filled": _inventory_has_hardware(),
        "device_count": device_count,
        "gateway": gateway,
        "recommendations": build_recommendations(device_count, gateway),
        "blocked_until_inventory": not _inventory_has_hardware(),
        "hint": "Fill 3+ rows in home-network-inventory.md for vendor-specific steps",
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())