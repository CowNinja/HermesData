#!/usr/bin/env python3
"""Network adapter base -- swap vendor modules without changing orchestrator."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class NetworkAdapter(ABC):
    """Vendor-agnostic home network read/write surface."""

    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True when inventory + credentials are present."""

    @abstractmethod
    def read_inventory(self) -> Dict[str, Any]:
        """Read-only snapshot (B0)."""

    def recommend(self, audit: Dict[str, Any]) -> List[str]:
        """Optional B1 recommendations from audit context."""
        return []

    def apply_change_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """B2+ approved changes -- default deny."""
        return {"ok": False, "error": "apply_not_implemented", "adapter": self.name}