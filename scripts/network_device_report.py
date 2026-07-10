#!/usr/bin/env python3
"""Generate Fing-style markdown device list from native scan (no Docker)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

VAULT = Path(r"D:\PhronesisVault")
DEVICES_JSON = VAULT / "Operations" / "logs" / "network-devices.json"
LABELS_JSON = VAULT / "Operations" / "logs" / "network-device-labels.json"
REPORT_MD = VAULT / "Operations" / "logs" / "network-device-report.md"


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _merge_labels(data: Dict[str, Any]) -> Dict[str, Any]:
    labels_data = _load_json(LABELS_JSON)
    label_by_mac = {
        (d.get("mac") or "").lower(): d
        for d in labels_data.get("labeled_devices") or []
        if d.get("mac")
    }
    devices: List[Dict[str, Any]] = []
    for dev in data.get("devices") or []:
        item = dict(dev)
        meta = label_by_mac.get((dev.get("mac") or "").lower()) or {}
        if meta.get("skynet_label"):
            item["skynet_label"] = meta["skynet_label"]
            if meta.get("role"):
                item["role"] = meta["role"]
        devices.append(item)
    out = dict(data)
    out["devices"] = devices
    return out


def _load_devices() -> Dict[str, Any]:
    data = _load_json(DEVICES_JSON)
    if not data:
        return {}
    return _merge_labels(data)


def render_markdown(data: Dict[str, Any]) -> str:
    ts = data.get("timestamp") or datetime.now(timezone.utc).isoformat()
    gateway = data.get("gateway") or "unknown"
    subnet = data.get("subnet") or "unknown"
    devices: List[Dict[str, Any]] = data.get("devices") or []
    ping = data.get("ping_verify") or {}
    lines = [
        "# Network Device Report (native scan)",
        "",
        f"**Generated:** {ts}",
        f"**Gateway:** {gateway}",
        f"**Subnet:** {subnet}",
        f"**Devices:** {len(devices)}",
        "",
    ]
    if ping:
        lines.append(
            f"**Alive (ping):** {ping.get('alive_count', 0)} / {ping.get('checked', 0)}"
        )
        lines.append("")
    labeled_n = sum(1 for d in devices if d.get("skynet_label"))
    lines.append(f"**SKYnet labels:** {labeled_n} / {len(devices)}")
    lines.append("")
    lines.extend([
        "| IP | MAC | Label | Role | Alive |",
        "|----|-----|-------|------|-------|",
    ])
    for dev in devices[:60]:
        ip = dev.get("ip") or ""
        mac = dev.get("mac") or ""
        label = dev.get("skynet_label") or "-"
        role = dev.get("role") or "unknown"
        alive = dev.get("alive")
        alive_s = "yes" if alive is True else ("no" if alive is False else "-")
        lines.append(f"| {ip} | {mac} | {label} | {role} | {alive_s} |")
    lines.extend([
        "",
        "## Next steps",
        "",
        "1. Label devices in home-network-inventory.md (router, AP, IoT, trusted PC).",
        "2. Add NETWORK_ROUTER_* to Bitwarden + SSH key for backup.",
        "3. Re-run: powershell -File D:\\HermesData\\scripts\\ops\\run-network-everything.ps1",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    data = _load_devices()
    if not data:
        print(json.dumps({"ok": False, "error": "network-devices.json missing; run home_network_audit first"}))
        return 1
    md = render_markdown(data)
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(md, encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(REPORT_MD), "devices": len(data.get("devices") or [])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())