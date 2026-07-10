#!/usr/bin/env python3
"""Generic read-only network adapter -- ARP + ipconfig baseline (B0)."""

from __future__ import annotations

import re
import subprocess
from typing import Any, Dict, List

from adapters.network.base import NetworkAdapter
from adapters.network.discovery import (
    classify_devices,
    infer_subnet,
    nmap_soft_scan,
    ping_verify_arp_hosts,
)


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


class GenericReadOnlyAdapter(NetworkAdapter):
    name = "generic_readonly"

    def is_configured(self) -> bool:
        return True

    def read_inventory(self) -> Dict[str, Any]:
        arp_out = _run(["arp", "-a"], timeout=20)
        hosts = _parse_arp(arp_out)
        ipconfig_out = _run(["ipconfig", "/all"], timeout=20)

        gateway = None
        for line in ipconfig_out.splitlines():
            if "Default Gateway" in line:
                m = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                if m:
                    gateway = m.group(1)
                    break

        adapters: List[str] = []
        for line in ipconfig_out.splitlines():
            if "adapter" in line.lower() and ":" in line:
                adapters.append(line.strip())

        if not gateway:
            for host in hosts:
                ip = host.get("ip") or ""
                if ip.startswith("192.168.") and ip.endswith(".1"):
                    gateway = ip
                    break

        classified = classify_devices(hosts)
        subnet = infer_subnet(gateway)
        ping_verify = ping_verify_arp_hosts(hosts)
        nmap_result = None
        if subnet:
            nmap_result = nmap_soft_scan(subnet)
        if ping_verify.get("devices"):
            classified["lan_hosts_filtered"] = ping_verify["devices"][:50]
            classified["ping_verify"] = {
                "checked": ping_verify.get("checked"),
                "alive_count": ping_verify.get("alive_count"),
            }

        return {
            "adapter": self.name,
            "scan_mode": "native",
            "default_gateway": gateway,
            "subnet_inferred": subnet,
            "adapters": adapters[:8],
            "lan_hosts_count": len(hosts),
            "lan_hosts_sample": hosts[:20],
            "discovery": classified,
            "ping_verify": ping_verify,
            "nmap_soft": nmap_result,
        }

    def recommend(self, audit: Dict[str, Any]) -> List[str]:
        recs: List[str] = []
        if not audit.get("inventory_filled"):
            recs.append("fill_home_network_inventory_md")
        if int(audit.get("lan_hosts_count") or 0) > 25:
            recs.append("consider_iot_vlan_isolation")
        recs.append("run_phase_8c_security_audit_first")
        return recs