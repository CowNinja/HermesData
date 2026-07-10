#!/usr/bin/env python3
"""ASUS Merlin adapter stub -- wire SSH/API when inventory filled."""

from __future__ import annotations

from typing import Any, Dict

from adapters.network.base import NetworkAdapter


class AsusAdapter(NetworkAdapter):
    name = "asus"

    def is_configured(self) -> bool:
        return False

    def read_inventory(self) -> Dict[str, Any]:
        return {
            "adapter": self.name,
            "configured": False,
            "error": "asus_merlin_not_configured",
            "hint": "Fill home-network-inventory.md router brand/model",
        }