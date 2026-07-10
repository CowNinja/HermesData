#!/usr/bin/env python3
"""UniFi adapter stub -- wire controller API when inventory filled."""

from __future__ import annotations

from typing import Any, Dict

from adapters.network.base import NetworkAdapter


class UniFiAdapter(NetworkAdapter):
    name = "unifi"

    def is_configured(self) -> bool:
        return False

    def read_inventory(self) -> Dict[str, Any]:
        return {
            "adapter": self.name,
            "configured": False,
            "error": "unifi_controller_url_not_set",
            "hint": "Fill home-network-inventory.md Admin API field",
        }