#!/usr/bin/env python3
"""Quick sovereign stack readiness for Grok-exhaust fallback."""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

OUT = Path(r"D:\PhronesisVault\Operations\logs\sovereign-stack-ready-latest.json")


def probe(url: str, timeout: float = 5.0) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read()[:500]
            return {"ok": True, "status": r.status, "sample": body.decode("utf-8", "ignore")[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main() -> int:
    cfg = yaml.safe_load(
        (Path.home() / ".hermes" / "config.yaml").read_text(encoding="utf-8")
    )
    fb = cfg.get("fallback_providers") or []
    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "primary": cfg.get("model"),
        "fallback_providers": fb,
        "fallback_wired": bool(fb)
        and any("8091" in str(x) or "phronesis" in str(x).lower() for x in fb),
        "llama_8090": probe("http://127.0.0.1:8090/v1/models"),
        "proxy_8091": probe("http://127.0.0.1:8091/v1/models"),
        "gateway_8642": probe("http://127.0.0.1:8642/"),
    }
    # completion smoke
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8091/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "phronesis-sovereign-auto",
                    "messages": [{"role": "user", "content": "Reply: PING"}],
                    "max_tokens": 8,
                    "temperature": 0,
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=45) as r:
            data = json.loads(r.read().decode())
            report["completion_smoke"] = {
                "ok": True,
                "content": data["choices"][0]["message"]["content"][:80],
            }
    except Exception as e:
        report["completion_smoke"] = {"ok": False, "error": str(e)}

    report["ready"] = (
        report["fallback_wired"]
        and report["llama_8090"].get("ok")
        and report["proxy_8091"].get("ok")
        and report["completion_smoke"].get("ok")
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
