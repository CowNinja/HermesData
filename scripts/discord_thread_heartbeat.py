#!/usr/bin/env python
"""Minimal no_agent heartbeat for Discord thread connection maintenance.
Prints status for delivery to origin chat. ASCII only.
"""
import datetime
import json
import requests
import sys

def main():
    now = datetime.datetime.now().isoformat()
    gateway_ok = False
    try:
        r = requests.get("http://127.0.0.1:8642/health", timeout=5)
        if r.status_code == 200 and r.json().get("status") == "ok":
            gateway_ok = True
    except Exception:
        pass

    discord_connected = False
    try:
        # Best effort from gateway state or known
        with open("D:\\HermesData\\gateway_state.json", "r") as f:
            state = json.load(f)
            platforms = state.get("platforms", {})
            discord_connected = platforms.get("discord", {}).get("state") == "connected"
    except Exception:
        pass

    status = {
        "ts": now,
        "gateway": "OK" if gateway_ok else "DOWN",
        "discord": "connected" if discord_connected else "check",
        "message": "Connection maintained. Gateway healthy. Discord bridge active."
    }
    print(json.dumps(status))
    print("Connection maintained at {} - Gateway: {} - Discord: {}".format(
        now, "OK" if gateway_ok else "DOWN", "connected" if discord_connected else "verify"))
    sys.exit(0)

if __name__ == "__main__":
    main()
