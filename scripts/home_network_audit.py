#!/usr/bin/env python3
"""Phase 8b home network audit B0 -- read-only LAN discovery."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

SCRIPTS = Path(__file__).resolve().parent
VAULT = Path(r"D:\PhronesisVault")
INVENTORY_PATH = VAULT / "docs" / "agent-coordination" / "home-network-inventory.md"
REPORT_PATH = VAULT / "Operations" / "logs" / "home-network-audit.json"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _run(cmd: List[str], timeout: int = 30) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (result.stdout or "") + (result.stderr or "")
    except Exception as exc:
        return str(exc)


def _parse_arp(text: str) -> List[Dict[str, str]]:
    hosts: List[Dict[str, str]] = []
    for line in text.splitlines():
        m = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-f\-]{17})", line, re.I)
        if m:
            hosts.append({"ip": m.group(1), "mac": m.group(2).lower()})
    return hosts


def _parse_inventory_rows() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    if not INVENTORY_PATH.is_file():
        return rows
    text = INVENTORY_PATH.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "|" not in line or line.strip().startswith("|--"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 2:
            continue
        field, value = parts[0], parts[-1]
        if field in ("Field", "Subnet", "Purpose", "Value", "Notes"):
            continue
        rows.append({"field": field, "value": value})
    return rows


def _inventory_filled() -> bool:
    skip_values = {
        "",
        "8090, 8091, 8642, 3001, 9119, 8188",
        "Main LAN",
    }
    filled = 0
    for row in _parse_inventory_rows():
        value = row["value"]
        if value in skip_values:
            continue
        if value.lower().startswith("e.g."):
            continue
        filled += 1
    return filled >= 3


def run_audit() -> Dict[str, Any]:
    from adapters.network import detect_vendor_from_inventory, load_adapter

    vendor = detect_vendor_from_inventory(INVENTORY_PATH)
    net_adapter = load_adapter(vendor)
    snapshot = net_adapter.read_inventory()
    if not net_adapter.is_configured() or not snapshot.get("lan_hosts_count"):
        from adapters.network.generic_readonly import GenericReadOnlyAdapter

        net_adapter = GenericReadOnlyAdapter()
        snapshot = net_adapter.read_inventory()
        vendor = "generic_readonly"

    inventory_filled = _inventory_filled()
    audit_ctx = {
        "inventory_filled": inventory_filled,
        "lan_hosts_count": int(snapshot.get("lan_hosts_count") or 0),
    }
    recommendations = net_adapter.recommend(audit_ctx)

    try:
        from phronesis_env import bootstrap_env

        bootstrap_env()
    except Exception:
        pass
    from network_cred_loader import list_credential_status

    creds = list_credential_status()
    discovery = snapshot.get("discovery") or {}
    ping_verify = snapshot.get("ping_verify") or {}
    filtered_count = int(discovery.get("lan_hosts_filtered_count") or 0)

    if not creds.get("router_ssh_configured"):
        recommendations.append("add_network_router_ssh_key_or_bitwarden")
    if filtered_count > 20:
        recommendations.append("consider_iot_vlan_isolation")
    recommendations.append("open_network_device_report_md")

    device_registry_path = VAULT / "Operations" / "logs" / "network-devices.json"
    devices = discovery.get("lan_hosts_filtered", [])[:50]
    if ping_verify.get("devices"):
        devices = ping_verify.get("devices", [])[:50]
    registry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scan_mode": snapshot.get("scan_mode", "native"),
        "gateway": snapshot.get("default_gateway"),
        "subnet": snapshot.get("subnet_inferred"),
        "devices": devices,
        "role_counts": discovery.get("role_counts", {}),
        "ping_verify": {
            "checked": ping_verify.get("checked"),
            "alive_count": ping_verify.get("alive_count"),
        },
    }
    device_registry_path.parent.mkdir(parents=True, exist_ok=True)
    device_registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")

    return {
        "module": "8b_home_network",
        "phase": "B0_read_only",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "inventory_filled": inventory_filled,
        "vendor_adapter": net_adapter.name,
        "vendor_configured": net_adapter.is_configured(),
        "default_gateway": snapshot.get("default_gateway"),
        "subnet_inferred": snapshot.get("subnet_inferred"),
        "adapters": snapshot.get("adapters", [])[:8],
        "lan_hosts_count": snapshot.get("lan_hosts_count", 0),
        "lan_hosts_filtered_count": filtered_count,
        "lan_hosts_sample": snapshot.get("lan_hosts_sample", [])[:20],
        "devices_filtered_sample": discovery.get("lan_hosts_filtered", [])[:20],
        "scan_mode": snapshot.get("scan_mode", "native"),
        "ping_verify": registry.get("ping_verify"),
        "nmap_soft": snapshot.get("nmap_soft"),
        "credentials": creds,
        "device_registry_path": str(device_registry_path),
        "recommendations": list(dict.fromkeys(recommendations)),
        "adapters_planned": ["native_scan", "ssh_backup", "git_local", "unifi", "openwrt", "asus"],
        "report_path": str(REPORT_PATH),
    }


def main() -> int:
    report = run_audit()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())