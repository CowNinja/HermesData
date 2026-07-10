#!/usr/bin/env python3
"""Distill SKYnet notes into hardware/MAC hints -- never exports passwords."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

VAULT = Path(r"D:\PhronesisVault")
OUT_JSON = VAULT / "Operations" / "logs" / "skynet-distillation.json"
LABELS_JSON = VAULT / "Operations" / "logs" / "network-device-labels.json"
DEVICES_JSON = VAULT / "Operations" / "logs" / "network-devices.json"

SKYNET_PATHS = [
    Path(r"G:\MemoryCard_Backups\Google Drive\Pers\SKYnet-notes"),
    Path(r"G:\MemoryCard_Backups\Google Drive(archive)\Pers\SKYnet-notes"),
]

C6250_GLOB = "**/Cable MODEM C6250-100NAS.txt"

# Lines that likely contain secrets -- skip entire line in free-text harvest
_SECRET_MARKERS = (
    "password",
    "passwd",
    "pass:",
    "wifi/",
    "basic ",
    "authorization",
    "privilege 15 encrypted",
    "@cowninja",
    "@gmail",
    "@yahoo",
    "@hpeprint",
    "lastpass",
    "account number",
    "6ru#",
    "blaizen",
    "guestnet",
    "opendns",
)

# Live authoritative labels (Starlink era)
_LIVE_LABELS: Dict[str, Dict[str, str]] = {
    "74-24-9f-c8-9a-6b": {
        "name": "Starlink Router",
        "role": "gateway",
        "source": "live_starlink_2026",
    },
}

# Known hardware patterns from SKYnet history
_KNOWN_DEVICES = [
    {"name": "Netgear C6250-100NAS", "role": "legacy_modem_gateway", "vendor": "netgear"},
    {"name": "TP-Link Archer C50", "role": "legacy_ap", "vendor": "tp-link", "mac": "ec:08:6b:d7:ad:a5"},
    {"name": "Portal Livingroom", "mac": "00:78:cd:00:a7:18", "role": "mesh_ap", "vendor": "portal"},
    {"name": "Portal ManCave", "mac": "00:78:cd:00:78:54", "role": "mesh_ap", "vendor": "portal"},
    {"name": "Portal manager Livingroom", "mac": "00:78:cd:03:c8:fc", "role": "mesh_ap", "vendor": "portal"},
    {"name": "Portal manager ManCave", "mac": "00:78:cd:03:74:5c", "role": "mesh_ap", "vendor": "portal"},
    {"name": "TP-Link AV2000 TL-PA9020P", "role": "powerline", "vendor": "tp-link"},
    {"name": "TP-Link AV1300 TL-PA8030P", "role": "powerline", "vendor": "tp-link"},
    {"name": "ASUS AP", "role": "legacy_ap_retired", "vendor": "asus"},
    {"name": "Hubitat C-4", "role": "iot_hub", "vendor": "hubitat"},
    {"name": "IotaWatt", "mac": "84:f3:eb:26:96:33", "role": "iot", "vendor": "iota"},
    {
        "name": "Nortel_BB01 L3 Switch",
        "mac": "00:15:40:24:d8:00",
        "role": "switch",
        "vendor": "nortel",
        "historical_ip": "10.0.0.7",
        "historical_hostname": "Nortel_BB01",
    },
]

_MAC_RE = re.compile(r"\b([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")

# Lower number = higher priority when two sources label the same MAC
_SOURCE_PRIORITY = {
    "live_starlink_2026": 0,
    "known_devices": 1,
    "c6250_portal": 2,
    "c6250_alexa": 3,
    "c6250_hostname": 4,
    "c6250_iotawatt": 5,
    "c6250_computer": 6,
    "c6250_fing_export": 7,
    "cujo_ocr": 8,
}

_SKIP_NAME_PREFIXES = (
    "device software",
    "serial number",
    "mac address",
    "auto",
    "jeffrey's alexa",
    "pi-top",
)


def _norm_mac(raw: str) -> str:
    return raw.replace(":", "-").replace(".", "-").lower()


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _line_has_secret(line: str) -> bool:
    low = line.lower()
    return any(m in low for m in _SECRET_MARKERS)


def _add_label(
    db: Dict[str, Dict[str, str]],
    mac_raw: str,
    name: str,
    role: str,
    source: str,
) -> None:
    mac = _norm_mac(mac_raw)
    if not _MAC_RE.fullmatch(mac.replace("-", ":")):
        return
    if mac.startswith("ff-ff-ff") or mac.startswith("01-00-5e"):
        return
    existing = db.get(mac)
    if existing:
        old_pri = _SOURCE_PRIORITY.get(existing.get("source", ""), 99)
        new_pri = _SOURCE_PRIORITY.get(source, 99)
        if new_pri >= old_pri:
            return
    db[mac] = {"name": name.strip(), "role": role, "source": source}


def _harvest_macs(text: str) -> Set[str]:
    found: Set[str] = set()
    for m in _MAC_RE.finditer(text):
        mac = _norm_mac(m.group(0))
        if not mac.startswith("ff-ff-ff") and not mac.startswith("01-00-5e"):
            found.add(mac)
    return found


def _harvest_subnets(text: str) -> Set[str]:
    subnets: Set[str] = set()
    for m in re.finditer(r"\b(10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+)\b", text):
        ip = m.group(1)
        parts = ip.split(".")
        subnets.add(f"{parts[0]}.{parts[1]}.{parts[2]}.0/24")
    return subnets


def _harvest_ssids(text: str) -> Set[str]:
    ssids: Set[str] = set()
    for m in re.finditer(r"SSID[:\s]+([A-Za-z0-9_\-]+)", text, re.I):
        ssids.add(m.group(1))
    if "SKYnet" in text:
        ssids.add("SKYnet")
    if "SKYnet-Guest" in text:
        ssids.add("SKYnet-Guest")
    return ssids


def _find_c6250_files() -> List[Path]:
    found: List[Path] = []
    for root in SKYNET_PATHS:
        if not root.is_dir():
            continue
        found.extend(root.glob(C6250_GLOB))
    return found


def _parse_c6250_alexa(lines: List[str], db: Dict[str, Dict[str, str]]) -> int:
    """Parse Alexa device name blocks: Name -> MAC Address XX:XX."""
    count = 0
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if _line_has_secret(line):
            i += 1
            continue
        # "Bedroom Online" or "LivingRoom" (no Online suffix)
        low = line.lower()
        if any(low.startswith(p) for p in _SKIP_NAME_PREFIXES):
            i += 1
            continue
        name_match = re.match(
            r"^([A-Za-z][A-Za-z0-9' \-]+?)(?:\s+(Online|Offline))?\s*$",
            line,
        )
        if name_match and i + 1 < len(lines):
            name = name_match.group(1).strip()
            status = (name_match.group(2) or "").strip()
            if status:
                name = f"{name} {status}"
            # Look ahead for MAC Address within next 4 lines
            for j in range(i + 1, min(i + 5, len(lines))):
                mac_m = re.match(
                    r"^MAC Address\s+([0-9A-Fa-f:.\-]+)\s*$",
                    lines[j].strip(),
                    re.I,
                )
                if mac_m:
                    display = f"Amazon Alexa ({name})"
                    _add_label(db, mac_m.group(1), display, "iot", "c6250_alexa")
                    count += 1
                    break
        i += 1
    return count


def _parse_c6250_hostname_tab(lines: List[str], db: Dict[str, Dict[str, str]]) -> int:
    """Parse DESKTOP-XXX\\tMAC\\tIP rows."""
    count = 0
    for line in lines:
        if _line_has_secret(line):
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            host = parts[0].strip()
            mac_m = _MAC_RE.search(parts[1])
            if host and mac_m and not host.startswith("*"):
                _add_label(db, mac_m.group(0), host, "trusted_pc", "c6250_hostname")
                count += 1
    return count


def _parse_c6250_portal(text: str, db: Dict[str, Dict[str, str]]) -> int:
    """Parse Portal LAN/manager MAC blocks from C6250."""
    count = 0
    portal_ctx = ""
    for line in text.splitlines():
        if _line_has_secret(line):
            continue
        if "PORTAL_FASTLANE" in line or "PORTAL_LR" in line or "PORTAL_MANCAVE" in line:
            portal_ctx = line.strip()
        loc = "Livingroom" if "2776" in portal_ctx or "LR" in portal_ctx.upper() else ""
        loc = "ManCave" if "0804" in portal_ctx or "MANCAVE" in portal_ctx.upper() else loc
        lan_m = re.match(r"^LAN MAC:\s*([0-9A-Fa-f:.\-]+)", line.strip(), re.I)
        if lan_m and loc:
            _add_label(db, lan_m.group(1), f"Portal {loc}", "mesh_ap", "c6250_portal")
            count += 1
        mgr_m = re.match(r"^my_manager:\s*([0-9A-Fa-f:.\-]+)", line.strip(), re.I)
        if mgr_m and loc:
            _add_label(db, mgr_m.group(1), f"Portal manager {loc}", "mesh_ap", "c6250_portal")
            count += 1
        semi_m = re.match(
            r"^[\d.]+;[^;]*;[^;]*;([^;]+);[^;]*;[^;]*;([0-9A-Fa-f:]{2}(?::[0-9A-Fa-f]{2}){5});",
            line.strip(),
        )
        if semi_m:
            hostname = semi_m.group(1).strip()
            mac = semi_m.group(2)
            role = "mesh_ap" if "portal" in hostname.lower() or "ignition" in hostname.lower() else "unknown"
            pretty = hostname.replace("_", " ")
            if "PORTAL_Livingroom" in hostname:
                pretty = "Portal Livingroom"
            elif "PORTAL_ManCave" in hostname:
                pretty = "Portal ManCave"
            elif "IGNITION_RW.lan" in hostname:
                pretty = "Portal manager ManCave"
            elif hostname == "IGNITION_RW":
                pretty = "Portal manager Livingroom"
            _add_label(db, mac, pretty, role, "c6250_fing_export")
            count += 1
    return count


def _parse_c6250_iotawatt(lines: List[str], db: Dict[str, Dict[str, str]]) -> int:
    """Parse IotaWatt MAC on line before/after device name."""
    count = 0
    for i, line in enumerate(lines):
        if _line_has_secret(line):
            continue
        if line.strip() == "IotaWatt" and i > 0:
            mac_m = _MAC_RE.search(lines[i - 1])
            if mac_m:
                _add_label(db, mac_m.group(0), "IotaWatt", "iot", "c6250_iotawatt")
                count += 1
    return count


def _parse_c6250_computer_ips(lines: List[str], db: Dict[str, Dict[str, str]]) -> int:
    """Parse DESKTOP-XXX on one line, IP MAC on next."""
    count = 0
    for i, line in enumerate(lines):
        if _line_has_secret(line):
            continue
        host_m = re.match(r"^(DESKTOP-[A-Z0-9]+)\s*$", line.strip())
        if host_m and i + 1 < len(lines):
            nxt = lines[i + 1]
            ip_mac = re.match(
                r"^(\d+\.\d+\.\d+\.\d+)\s+([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})\s*$",
                nxt.strip(),
            )
            if ip_mac:
                _add_label(db, ip_mac.group(2), host_m.group(1), "trusted_pc", "c6250_computer")
                count += 1
    return count


def _parse_cujo_ocr(path: Path, db: Dict[str, Dict[str, str]]) -> int:
    """Best-effort CUJO OCR MAC-IP dump (fuzzy MAC normalization)."""
    text = _safe_read(path)
    if not text:
        return 0
    count = 0
    # Lines like "AMAZON ECHO DOT" then mac ip on next lines
    current_name = ""
    for line in text.splitlines():
        if _line_has_secret(line):
            continue
        stripped = line.strip()
        if re.match(r"^[A-Z][A-Z0-9 /\-]+$", stripped) and "VENDOR" not in stripped:
            current_name = stripped.title().replace("  ", " ")
        mac_m = re.search(r"([0-9a-fA-F]{2}[:.,][0-9a-fA-F]{2}[:.,][0-9a-fA-F]{2}[:.,][0-9a-fA-F]{2}[:.,][0-9a-fA-F]{2}[:.,][0-9a-fA-F]{2})", stripped)
        if mac_m and current_name:
            cleaned = re.sub(r"[^0-9A-Fa-f]", ":", mac_m.group(1))
            parts = [p for p in cleaned.split(":") if p]
            if len(parts) == 6:
                mac = ":".join(p.zfill(2)[:2] for p in parts)
                _add_label(db, mac, current_name, "iot", "cujo_ocr")
                count += 1
    return count


def _build_mac_label_db() -> Tuple[Dict[str, Dict[str, str]], Dict[str, int]]:
    db: Dict[str, Dict[str, str]] = dict(_LIVE_LABELS)
    stats: Dict[str, int] = {"live": len(_LIVE_LABELS)}

    for dev in _KNOWN_DEVICES:
        mac = dev.get("mac")
        if mac:
            _add_label(db, mac, dev["name"], dev.get("role", "unknown"), "known_devices")

    c6250_files = _find_c6250_files()
    for path in c6250_files:
        raw = _safe_read(path)
        safe_lines = [ln for ln in raw.splitlines() if not _line_has_secret(ln)]
        stats["c6250_alexa"] = stats.get("c6250_alexa", 0) + _parse_c6250_alexa(safe_lines, db)
        stats["c6250_hostname"] = stats.get("c6250_hostname", 0) + _parse_c6250_hostname_tab(safe_lines, db)
        stats["c6250_portal"] = stats.get("c6250_portal", 0) + _parse_c6250_portal(raw, db)
        stats["c6250_iotawatt"] = stats.get("c6250_iotawatt", 0) + _parse_c6250_iotawatt(safe_lines, db)
        stats["c6250_computer"] = stats.get("c6250_computer", 0) + _parse_c6250_computer_ips(safe_lines, db)

    for root in SKYNET_PATHS:
        cujo = root / "CUJO" / "Screenshots" / "2018-04-18 @ 0854 - CUJO MAC-IP BlueStacks_ScreenShot 01.txt"
        if cujo.is_file():
            stats["cujo_ocr"] = _parse_cujo_ocr(cujo, db)

    return db, stats


def distill_paths() -> Dict[str, Any]:
    files_read = 0
    all_macs: Set[str] = set()
    all_subnets: Set[str] = set()
    all_ssids: Set[str] = set()
    models: List[str] = []

    patterns = (
        ("Netgear C6250", "Netgear C6250-100NAS cable modem gateway"),
        ("Archer_C50", "TP-Link Archer C50"),
        ("Portal", "Ignition Design Labs Portal mesh AP"),
        ("Charter Spectrum", "Charter Spectrum ISP"),
        ("tp-link AV", "TP-Link powerline adapter"),
        ("Hubitat", "Hubitat Elevation hub"),
        ("ASUS", "ASUS router/AP (retired)"),
        ("Starlink", "Starlink dish + router"),
    )

    for root in SKYNET_PATHS:
        if not root.is_dir():
            continue
        for path in root.rglob("*.txt"):
            if path.stat().st_size > 500_000:
                continue
            text = _safe_read(path)
            if not text:
                continue
            files_read += 1
            safe_lines = [ln for ln in text.splitlines() if not _line_has_secret(ln)]
            safe_text = "\n".join(safe_lines)
            all_macs |= _harvest_macs(safe_text)
            all_subnets |= _harvest_subnets(safe_text)
            all_ssids |= _harvest_ssids(safe_text)
            for needle, label in patterns:
                if needle.lower() in text.lower() and label not in models:
                    models.append(label)

    if "Charter Spectrum ISP" not in models:
        models.append("Charter Spectrum ISP (historical)")
    if "Starlink dish + router" not in models:
        models.append("Starlink dish + router (current)")

    mac_labels, label_stats = _build_mac_label_db()
    c6250_sources = [str(p) for p in _find_c6250_files()]

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_paths": [str(p) for p in SKYNET_PATHS if p.is_dir()],
        "c6250_primary_sources": c6250_sources,
        "files_scanned": files_read,
        "isp_current": "Starlink (Jeff 2026 -- authoritative over notes)",
        "isp_historical": "Charter Spectrum (SKYnet notes)",
        "dhcp_current": "Starlink router only (ASUS retired; L3 switch capable but not DHCP)",
        "ssid_current_confirmed": ["SKYnet"],
        "hardware_models": models,
        "known_devices": _KNOWN_DEVICES,
        "mac_labels": mac_labels,
        "mac_labels_count": len(mac_labels),
        "mac_label_parse_stats": label_stats,
        "ssids_historical": sorted(all_ssids),
        "subnets_historical": sorted(all_subnets),
        "macs_harvested_count": len(all_macs),
        "macs_sample": sorted(all_macs)[:40],
        "security_note": "Passwords intentionally excluded. Migrate secrets to Bitwarden manually.",
    }


def merge_live_labels(distilled: Dict[str, Any]) -> Dict[str, Any]:
    live: Dict[str, Any] = {}
    if DEVICES_JSON.is_file():
        try:
            live = json.loads(DEVICES_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass

    mac_labels: Dict[str, Dict[str, str]] = distilled.get("mac_labels") or {}

    labeled: List[Dict[str, Any]] = []
    for entry in live.get("devices") or []:
        mac = (entry.get("mac") or "").lower()
        meta = mac_labels.get(mac) or {}
        item = dict(entry)
        if meta.get("name"):
            item["skynet_label"] = meta["name"]
            item["label_source"] = meta.get("source", "")
            if meta.get("role"):
                item["role"] = meta["role"]
        labeled.append(item)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gateway": live.get("gateway"),
        "subnet": live.get("subnet"),
        "labeled_devices": labeled,
        "unlabeled_count": sum(1 for d in labeled if not d.get("skynet_label")),
        "labeled_count": sum(1 for d in labeled if d.get("skynet_label")),
    }


def main() -> int:
    distilled = distill_paths()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(distilled, indent=2), encoding="utf-8")

    labels = merge_live_labels(distilled)
    LABELS_JSON.write_text(json.dumps(labels, indent=2), encoding="utf-8")

    summary = {
        "distillation": str(OUT_JSON),
        "labels": str(LABELS_JSON),
        "mac_labels_count": distilled.get("mac_labels_count"),
        "labeled_count": labels.get("labeled_count"),
        "unlabeled_count": labels.get("unlabeled_count"),
        "c6250_sources": distilled.get("c6250_primary_sources"),
    }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())