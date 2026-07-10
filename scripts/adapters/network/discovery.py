#!/usr/bin/env python3
"""LAN discovery helpers -- filtered ARP + optional nmap soft scan."""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Set


_MULTICAST_PREFIXES = (
    "01-00-5e",
    "ff-ff-ff",
    "33-33",
)


def _is_lan_ip(ip: str) -> bool:
    if not ip or ip.count(".") != 3:
        return False
    parts = ip.split(".")
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    if a == 192 and b == 168:
        return True
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    return False


def _is_multicast_mac(mac: str) -> bool:
    low = (mac or "").lower()
    return any(low.startswith(p) for p in _MULTICAST_PREFIXES)


def filter_lan_hosts(hosts: List[Dict[str, str]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for host in hosts:
        ip = host.get("ip") or ""
        mac = host.get("mac") or ""
        if not _is_lan_ip(ip):
            continue
        if _is_multicast_mac(mac):
            continue
        if ip in seen:
            continue
        seen.add(ip)
        role = "unknown"
        if ip.endswith(".1"):
            role = "likely_gateway"
        out.append({"ip": ip, "mac": mac, "role": role})
    return out


def classify_devices(hosts: List[Dict[str, str]]) -> Dict[str, Any]:
    filtered = filter_lan_hosts(hosts)
    roles: Dict[str, int] = {}
    for h in filtered:
        role = h.get("role") or "unknown"
        roles[role] = roles.get(role, 0) + 1
    return {
        "lan_hosts_filtered_count": len(filtered),
        "lan_hosts_filtered": filtered[:50],
        "role_counts": roles,
    }


def nmap_soft_scan(subnet: str, *, timeout_sec: int = 120) -> Dict[str, Any]:
    """Optional nmap -sn ping scan. Skipped gracefully if nmap missing."""
    nmap = shutil.which("nmap")
    if not nmap:
        return {"ok": False, "skipped": True, "reason": "nmap_not_on_path"}
    target = subnet if "/" in subnet else f"{subnet}/24"
    try:
        result = subprocess.run(
            [nmap, "-sn", "-T3", target],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        text = (result.stdout or "") + (result.stderr or "")
        hosts: List[str] = []
        for line in text.splitlines():
            m = re.search(r"Nmap scan report for (.+)", line)
            if m:
                hosts.append(m.group(1).strip())
        return {
            "ok": result.returncode == 0,
            "subnet": target,
            "hosts_found": len(hosts),
            "hosts_sample": hosts[:30],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def infer_subnet(gateway: Optional[str]) -> Optional[str]:
    if not gateway or gateway.count(".") != 3:
        return None
    parts = gateway.split(".")
    return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"


def ping_host(ip: str, *, timeout_ms: int = 400) -> bool:
    """Windows native ping -- one packet, no extra deps."""
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout_ms), ip],
            capture_output=True,
            text=True,
            timeout=5,
        )
        text = (result.stdout or "").lower()
        return result.returncode == 0 and "ttl=" in text
    except Exception:
        return False


def ping_verify_arp_hosts(hosts: List[Dict[str, str]], *, max_hosts: int = 40) -> Dict[str, Any]:
    """Ping only ARP-known LAN IPs -- lightweight alive check (no /24 sweep)."""
    filtered = filter_lan_hosts(hosts)[:max_hosts]
    alive: List[Dict[str, Any]] = []
    dead: List[str] = []
    for host in filtered:
        ip = host.get("ip") or ""
        if not ip:
            continue
        up = ping_host(ip)
        entry = dict(host)
        entry["alive"] = up
        alive.append(entry)
        if not up:
            dead.append(ip)
    up_count = sum(1 for h in alive if h.get("alive"))
    return {
        "checked": len(alive),
        "alive_count": up_count,
        "dead_count": len(dead),
        "devices": alive,
        "dead_sample": dead[:10],
    }