#!/usr/bin/env python3
"""Load network adapter by vendor name from phase8_modules.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Type

from adapters.network.base import NetworkAdapter
from adapters.network.generic_readonly import GenericReadOnlyAdapter

_VENDOR_STUBS: Dict[str, Type[NetworkAdapter]] = {}


def _register_stubs() -> None:
    global _VENDOR_STUBS
    if _VENDOR_STUBS:
        return
    from adapters.network.unifi import UniFiAdapter
    from adapters.network.openwrt import OpenWrtAdapter
    from adapters.network.asus import AsusAdapter

    _VENDOR_STUBS = {
        "generic_readonly": GenericReadOnlyAdapter,
        "generic_snmp": GenericReadOnlyAdapter,
        "unifi": UniFiAdapter,
        "openwrt": OpenWrtAdapter,
        "asus": AsusAdapter,
    }


def load_adapter(vendor: Optional[str] = None) -> NetworkAdapter:
    _register_stubs()
    key = (vendor or "generic_readonly").strip().lower()
    cls = _VENDOR_STUBS.get(key, GenericReadOnlyAdapter)
    return cls()


def detect_vendor_from_inventory(path: Path) -> str:
    if not path.is_file():
        return "generic_readonly"
    admin_api = ""
    brand = ""
    controller = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if "|" not in line or line.strip().startswith("|--"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 2:
            continue
        field, value = parts[0].lower(), parts[-1].strip().lower()
        if not value or value in ("value", "notes"):
            continue
        if "admin api" in field:
            admin_api = value
        elif "brand" in field and "model" in field:
            brand = value
        elif "controller" in field:
            controller = value
    blob = " ".join((admin_api, brand, controller))
    if len(blob) < 3 or "confirm" in blob or "fill" in blob or "generic" in blob:
        return "generic_readonly"
    if "starlink" in blob:
        return "generic_readonly"
    if "unifi" in blob and "unifi /" not in blob:
        return "unifi"
    if "openwrt" in blob or "gl.inet" in blob:
        return "openwrt"
    if ("asus" in brand or "merlin" in brand) and "asus" not in admin_api[:6]:
        return "asus"
    if brand.startswith("asus") or "rt-ax" in brand or "rt-ac" in brand:
        return "asus"
    return "generic_readonly"