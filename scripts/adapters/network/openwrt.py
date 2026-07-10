#!/usr/bin/env python3
"""OpenWrt adapter stub -- wire ubus/ssh when inventory filled."""

from __future__ import annotations

from typing import Any, Dict

from adapters.network.base import NetworkAdapter


class OpenWrtAdapter(NetworkAdapter):
    name = "openwrt"

    def is_configured(self) -> bool:
        return False

    def read_inventory(self) -> Dict[str, Any]:
        return {
            "adapter": self.name,
            "configured": False,
            "error": "openwrt_ssh_not_configured",
            "hint": "Fill home-network-inventory.md router management URL",
        }