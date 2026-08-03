#!/usr/bin/env python3
"""Phase 8a T2 SFW image offload -- multi-provider adapters + failover.

Providers SSOT: config/fleet_registry.yaml -> image_providers[]
Gate: fleet_sfw_gate.classify_image_offload
Rate: free_sfw_rate_scheduler
Profiles: config/free_sfw_provider_profiles.json
Route judgment: image_route_judge.py

Expand: add adapter to _ADAPTERS + registry row (enabled, priority, api_mode).
Providers may come and go -- discover via free_sfw_discover.py.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

SCRIPTS = Path(__file__).resolve().parent
REGISTRY_PATH = Path(r"D:\HermesData\config\fleet_registry.yaml")
OUT_DIR = Path(r"D:\HermesData\benchmarks\outputs\free_sfw")

if str(SCRIPTS) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPTS))

# Load D:\HermesData\.env so HUGGINGFACE_TOKEN / AI_HORDE_API_KEY resolve
def _load_dotenv() -> None:
    env_path = Path(r"D:\HermesData\.env")
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip("'").strip('"')
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass


_load_dotenv()

from fleet_sfw_gate import classify_image_offload  # noqa: E402
import free_sfw_rate_scheduler as rate  # noqa: E402

PNG_MAGIC = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
JPG_MAGIC = bytes([0xFF, 0xD8, 0xFF])


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return {}
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def list_image_providers(*, enabled_only: bool = True) -> List[Dict[str, Any]]:
    reg = _load_yaml(REGISTRY_PATH)
    providers = reg.get("image_providers") or []
    out: List[Dict[str, Any]] = []
    for item in providers:
        if not isinstance(item, dict):
            continue
        if enabled_only and not item.get("enabled", True):
            continue
        # skip if required env missing
        env_key = str(item.get("api_key_env") or "").strip()
        if env_key and not os.environ.get(env_key):
            # still list if allow_anonymous
            if not item.get("allow_anonymous"):
                continue
        out.append(item)
    out.sort(key=lambda p: int(p.get("priority") or 99))
    return out


def _save_image_bytes(data: bytes, *, label: str, ext: str = ".jpg") -> str:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (label or "sfw")[:48]).strip("_")
    if not safe:
        safe = "sfw"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUT_DIR / f"free_sfw_{safe}_{stamp}{ext}"
    path.write_bytes(data)
    return str(path)


def _dims_for_aspect(aspect_ratio: str, provider: Dict[str, Any]) -> tuple[int, int]:
    base_w = int(provider.get("width") or 1024)
    base_h = int(provider.get("height") or 1024)
    ar = (aspect_ratio or "1:1").strip().lower().replace(" ", "")
    table = {
        "1:1": (base_w, base_h),
        "square": (base_w, base_h),
        # Prefer 64-multiple sizes free providers actually honor (avoid post-stretch).
        "16:9": (1024, 576),
        "landscape": (1024, 576),
        "9:16": (576, 1024),
        "portrait": (768, 1024),
        "fullbody": (768, 1024),
        "4:3": (1024, 768),
        "3:4": (768, 1024),
        "3:2": (1152, 768),
        "2:3": (768, 1152),
        "832x1216": (832, 1216),
        "512": (512, 512),
    }
    w, h = table.get(ar, (base_w, base_h))
    # provider max dim clamp
    max_dim = int(provider.get("max_dim") or 1536)
    scale = min(1.0, max_dim / max(w, h))
    if scale < 1.0:
        w, h = int(w * scale), int(h * scale)
    # horde likes multiples of 64
    if provider.get("multiple_of"):
        m = int(provider["multiple_of"])
        w = max(m, (w // m) * m)
        h = max(m, (h // m) * m)
    return w, h


def _http_get(url: str, *, headers: Optional[Dict[str, str]] = None, timeout: float = 45.0) -> bytes:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "HermesFreeSFW/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"http_{resp.status}")
        return resp.read()


def _http_json(
    url: str,
    *,
    method: str = "GET",
    payload: Optional[dict] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 60.0,
) -> Any:
    data = None
    hdrs = {"User-Agent": "HermesFreeSFW/2.0", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        if not body:
            return {}
        return json.loads(body.decode("utf-8", errors="replace"))


def _decode_image_bytes(data: bytes) -> tuple[bytes, str]:
    if data[:8] == PNG_MAGIC:
        return data, ".png"
    if data[:3] == JPG_MAGIC:
        return data, ".jpg"
    # sometimes base64 text
    try:
        text = data.decode("utf-8", errors="strict").strip()
        if text.startswith("data:image"):
            b64 = text.split(",", 1)[1]
            raw = base64.b64decode(b64)
            return _decode_image_bytes(raw)
    except Exception:
        pass
    raise ValueError("not_image_bytes")

def _probe_image_size(data: bytes) -> tuple[int, int] | None:
    """Return (width, height) from PNG/JPEG headers without full decode."""
    if data[:8] == PNG_MAGIC and len(data) >= 24:
        w = int.from_bytes(data[16:20], "big")
        h = int.from_bytes(data[20:24], "big")
        return w, h
    if data[:3] == JPG_MAGIC:
        i = 2
        n = len(data)
        while i < n - 8:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                h = int.from_bytes(data[i + 5 : i + 7], "big")
                w = int.from_bytes(data[i + 7 : i + 9], "big")
                return w, h
            if marker == 0xD9:
                break
            if marker == 0x01 or (0xD0 <= marker <= 0xD9):
                i += 2
                continue
            if i + 4 > n:
                break
            seglen = int.from_bytes(data[i + 2 : i + 4], "big")
            if seglen < 2:
                break
            i += 2 + seglen
    return None


def _aspect_close(w: int, h: int, rw: int, rh: int, tol: float = 0.08) -> bool:
    if w <= 0 or h <= 0 or rw <= 0 or rh <= 0:
        return False
    return abs((w / h) - (rw / rh)) <= tol



# --- adapters -----------------------------------------------------------------

def _pollinations_generate(
    prompt: str,
    provider: Dict[str, Any],
    *,
    aspect_ratio: str = "1:1",
    label: str = "",
    seed: int | None = None,
) -> Dict[str, Any]:
    """Keyless Pollinations URL mode. model query optional (flux/turbo/etc)."""
    base = str(provider.get("base_url") or "https://image.pollinations.ai/prompt").rstrip("/")
    encoded = urllib.parse.quote(prompt, safe="")
    width, height = _dims_for_aspect(aspect_ratio, provider)
    seed0 = int(seed) if seed is not None else (int(time.time() * 1000) % 999999)
    timeout = float(provider.get("timeout_sec") or 45.0)
    retries = int(provider.get("retries") or 3)
    model = str(provider.get("model") or "").strip()
    # strip fake model ids used only for labeling
    if model in ("pollinations-generic", "generic", ""):
        model_q = ""
    else:
        model_q = model
    last_err = "unknown"
    pid = str(provider.get("id") or "pollinations-sfw")
    for attempt in range(retries):
        s = seed0 + attempt
        q = f"width={width}&height={height}&nologo=true&seed={s}"
        if model_q:
            q += f"&model={urllib.parse.quote(model_q)}"
        # enhance off by default (faster, fewer surprises)
        if provider.get("enhance"):
            q += "&enhance=true"
        url = f"{base}/{encoded}?{q}"
        try:
            data = _http_get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 HermesFreeSFW/2.0",
                    "Accept": "image/*,*/*",
                },
                timeout=timeout,
            )
            if not data or len(data) < 64:
                last_err = "empty_body"
                time.sleep(2 * (attempt + 1))
                continue
            try:
                img, ext = _decode_image_bytes(data)
            except ValueError:
                last_err = "not_image_bytes"
                continue
            actual = _probe_image_size(img)
            if actual and not _aspect_close(actual[0], actual[1], width, height, tol=0.10):
                last_err = f"aspect_mismatch_got_{actual[0]}x{actual[1]}_want_{width}x{height}"
                continue
            aw, ah = actual if actual else (width, height)
            path = _save_image_bytes(img, label=label or pid, ext=ext)
            return {
                "success": True,
                "image": path,
                "image_url": url,
                "output": path,
                "model": model_q or "pollinations-default",
                "provider": pid,
                "attempts": attempt + 1,
                "width": aw,
                "height": ah,
                "requested_width": width,
                "requested_height": height,
                "seed": s,
            }
        except Exception as exc:
            last_err = str(exc)
            if "429" in last_err and attempt + 1 < retries:
                time.sleep(8 * (attempt + 1))
                continue
            if attempt + 1 < retries and any(
                x in last_err.lower() for x in ("timeout", "temporarily", "503", "502")
            ):
                time.sleep(4 * (attempt + 1))
                continue
            if attempt + 1 >= retries:
                break
            time.sleep(3 * (attempt + 1))
    return {"success": False, "error": f"{pid}:{last_err}"}


def _ai_horde_generate(
    prompt: str,
    provider: Dict[str, Any],
    *,
    aspect_ratio: str = "1:1",
    label: str = "",
    seed: int | None = None,
) -> Dict[str, Any]:
    """Community AI Horde (stablehorde) -- free, queue-based, no local GPU."""
    base = str(provider.get("base_url") or "https://aihorde.net/api/v2").rstrip("/")
    pid = str(provider.get("id") or "ai-horde")
    api_key = os.environ.get(str(provider.get("api_key_env") or "AI_HORDE_API_KEY") or "") or "0000000000"
    width, height = _dims_for_aspect(aspect_ratio, {**provider, "multiple_of": 64})
    # keep cheap for anonymous kudos - clamp by max side while PRESERVING aspect
    # (old min(w,max_w)+min(h,max_h) independently forced near-square / bad AR)
    max_w = int(provider.get("max_width") or 768)
    max_h = int(provider.get("max_height") or 768)
    scale = min(1.0, max_w / float(width), max_h / float(height))
    width = max(64, int(width * scale))
    height = max(64, int(height * scale))
    width = max(64, (width // 64) * 64)
    height = max(64, (height // 64) * 64)
    req = _dims_for_aspect(aspect_ratio, {**provider, "multiple_of": 64})
    if not _aspect_close(width, height, req[0], req[1], tol=0.12):
        ar = req[0] / float(req[1])
        if ar >= 1.0:
            width = min(max_w, (max_w // 64) * 64)
            height = max(64, (int(width / ar) // 64) * 64)
        else:
            height = min(max_h, (max_h // 64) * 64)
            width = max(64, (int(height * ar) // 64) * 64)
    steps = int(provider.get("steps") or 20)
    cfg = float(provider.get("cfg_scale") or 7.0)
    models = provider.get("models") or ["stable_diffusion"]
    if isinstance(models, str):
        models = [models]
    timeout = float(provider.get("timeout_sec") or 180.0)
    poll_s = float(provider.get("poll_sec") or 3.0)

    payload = {
        "prompt": prompt,
        "params": {
            "sampler_name": str(provider.get("sampler") or "k_euler"),
            "cfg_scale": cfg,
            "width": width,
            "height": height,
            "steps": steps,
            "n": 1,
            "karras": True,
        },
        "nsfw": False,
        "censor_nsfw": True,
        "trusted_workers": bool(provider.get("trusted_workers", False)),
        "models": list(models),
        "r2": True,
    }
    if seed is not None:
        payload["params"]["seed"] = str(seed)

    try:
        async_resp = _http_json(
                    f"{base}/generate/async",
                    method="POST",
                    payload=payload,
                    headers={
                        "apikey": api_key,
                        "Client-Agent": "HermesFreeSFW:2.0:jeff@local",
                        "User-Agent": "HermesFreeSFW/2.0",
                    },
                    timeout=30.0,
                )
    except Exception as exc:
        return {"success": False, "error": f"{pid}:submit:{exc}"}

    job_id = str(async_resp.get("id") or "")
    if not job_id:
        return {"success": False, "error": f"{pid}:no_id:{async_resp}"}

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(poll_s)
        try:
            check = _http_json(
                            f"{base}/generate/check/{job_id}",
                            headers={
                                "apikey": api_key,
                                "Client-Agent": "HermesFreeSFW:2.0:jeff@local",
                                "User-Agent": "HermesFreeSFW/2.0",
                            },
                            timeout=30.0,
                        )
        except Exception as exc:
            last = str(exc)
            continue
        if check.get("faulted"):
            return {"success": False, "error": f"{pid}:faulted"}
        if check.get("done"):
            break
    else:
        return {"success": False, "error": f"{pid}:timeout_queue"}

    try:
        status = _http_json(
                    f"{base}/generate/status/{job_id}",
                    headers={
                        "apikey": api_key,
                        "Client-Agent": "HermesFreeSFW:2.0:jeff@local",
                        "User-Agent": "HermesFreeSFW/2.0",
                    },
                    timeout=60.0,
                )
    except Exception as exc:
        return {"success": False, "error": f"{pid}:status:{exc}"}

    gens = status.get("generations") or []
    if not gens:
        return {"success": False, "error": f"{pid}:empty_generations"}
    g0 = gens[0] if isinstance(gens[0], dict) else {}
    img_field = g0.get("img") or g0.get("url") or ""
    if not img_field:
        return {"success": False, "error": f"{pid}:no_img_field"}

    try:
        if str(img_field).startswith("http"):
            raw = _http_get(str(img_field), timeout=60.0)
            img, ext = _decode_image_bytes(raw)
        else:
            # base64
            raw = base64.b64decode(img_field)
            img, ext = _decode_image_bytes(raw)
    except Exception as exc:
        return {"success": False, "error": f"{pid}:decode:{exc}"}

    actual = _probe_image_size(img)
    if actual and not _aspect_close(actual[0], actual[1], width, height, tol=0.12):
        return {
            "success": False,
            "error": f"{pid}:aspect_mismatch_got_{actual[0]}x{actual[1]}_want_{width}x{height}",
        }
    aw, ah = actual if actual else (width, height)
    path = _save_image_bytes(img, label=label or pid, ext=ext)
    return {
        "success": True,
        "image": path,
        "output": path,
        "model": str(g0.get("model") or (models[0] if models else "horde")),
        "provider": pid,
        "attempts": 1,
        "width": aw,
        "height": ah,
        "requested_width": width,
        "requested_height": height,
        "seed": seed,
        "horde_id": job_id,
        "worker": g0.get("worker_name"),
    }


def _hf_inference_generate(
    prompt: str,
    provider: Dict[str, Any],
    *,
    aspect_ratio: str = "1:1",
    label: str = "",
    seed: int | None = None,
) -> Dict[str, Any]:
    """Hugging Face Inference API (needs HUGGINGFACE_TOKEN / HF_TOKEN)."""
    pid = str(provider.get("id") or "hf-inference")
    token = (
        os.environ.get(str(provider.get("api_key_env") or "HUGGINGFACE_TOKEN") or "")
        or os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGINGFACE_TOKEN")
        or ""
    )
    if not token:
        return {"success": False, "error": f"{pid}:missing_token"}
    model = str(provider.get("model") or "black-forest-labs/FLUX.1-schnell")
    base = str(provider.get("base_url") or "https://api-inference.huggingface.co/models").rstrip("/")
    url = f"{base}/{model}"
    width, height = _dims_for_aspect(aspect_ratio, provider)
    # many HF image models ignore size; still pass
    payload: Dict[str, Any] = {
        "inputs": prompt,
        "parameters": {
            "width": width,
            "height": height,
        },
        "options": {"wait_for_model": True},
    }
    if seed is not None:
        payload["parameters"]["seed"] = int(seed)
    timeout = float(provider.get("timeout_sec") or 120.0)
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "image/png",
                "User-Agent": "HermesFreeSFW/2.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "")
        if "application/json" in ctype:
            try:
                j = json.loads(data.decode("utf-8", errors="replace"))
                err = j.get("error") or j
            except Exception:
                err = data[:200]
            return {"success": False, "error": f"{pid}:json:{err}"}
        img, ext = _decode_image_bytes(data)
        path = _save_image_bytes(img, label=label or pid, ext=ext)
        return {
            "success": True,
            "image": path,
            "output": path,
            "model": model,
            "provider": pid,
            "attempts": 1,
            "width": width,
            "height": height,
            "seed": seed,
        }
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        return {"success": False, "error": f"{pid}:HTTP {exc.code}:{body or exc.reason}"}
    except Exception as exc:
        return {"success": False, "error": f"{pid}:{exc}"}


# adapter registry
_ADAPTERS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "pollinations": _pollinations_generate,
    "ai_horde": _ai_horde_generate,
    "ai-horde": _ai_horde_generate,
    "horde": _ai_horde_generate,
    "hf_inference": _hf_inference_generate,
    "huggingface": _hf_inference_generate,
}


def try_fleet_image_generate(
    prompt: str,
    *,
    aspect_ratio: str = "1:1",
    skip_gate: bool = False,
    label: str = "",
    seed: int | None = None,
    provider_id: str | None = None,
    no_rate_limit: bool = False,
) -> Dict[str, Any]:
    """Attempt free-SFW generation with ranked multi-provider failover."""
    if skip_gate:
        gate: Dict[str, Any] = {
            "allow_t2": True,
            "reason": "skip_gate",
            "sanitized_prompt": prompt,
        }
    else:
        gate = classify_image_offload(prompt)
    if not gate.get("allow_t2"):
        return {
            "success": False,
            "error": f"t2_gate_blocked:{gate.get('reason')}",
            "route": gate.get("route", "local_comfy_only"),
            "gate": gate,
        }

    sanitized = str(gate.get("sanitized_prompt") or prompt)
    ar_l = (aspect_ratio or "1:1").strip().lower().replace(" ", "")
    if ar_l in ("16:9", "landscape", "4:3", "3:2"):
        if "horizontal framing" not in sanitized.lower():
            sanitized = (
                sanitized.rstrip(", ")
                + ", native horizontal framing, correct unstretched human proportions, "
                + "wide scene composition not vertical portrait cropped, natural anatomy aspect"
            )
    elif ar_l in ("9:16", "portrait", "fullbody", "3:4", "2:3"):
        if "vertical framing" not in sanitized.lower():
            sanitized = (
                sanitized.rstrip(", ")
                + ", native vertical portrait framing, correct unstretched human proportions"
            )
    providers = list_image_providers()
    if not providers:
        return {"success": False, "error": "no_image_providers_configured"}

    if provider_id:
        providers = [p for p in providers if str(p.get("id")) == provider_id]
        if not providers:
            return {"success": False, "error": f"provider_not_found:{provider_id}"}
    else:
        providers = rate.rank_providers(providers, prompt=sanitized)

    tags = rate.infer_task_tags(sanitized)
    errors: List[str] = []
    tried: List[str] = []

    for provider in providers:
        mode = str(provider.get("api_mode") or provider.get("adapter") or "").lower()
        fn = _ADAPTERS.get(mode)
        pid = str(provider.get("id") or mode)
        if fn is None:
            errors.append(f"unknown_adapter:{mode}")
            continue
        # Skip long cooldowns - try next provider (true failover)
        if not no_rate_limit and not rate.provider_available(pid):
            errors.append(f"{pid}:cooldown_skip")
            continue
        tried.append(pid)
        waited = 0.0
        if not no_rate_limit:
            # min-gap only; 429 cooldown handled via provider_available skip
            waited = rate.wait_turn(
                pid,
                min_gap_s=float(provider.get("min_gap_s") or 8.0),
            )
        t0 = time.perf_counter()
        result = fn(
            sanitized,
            provider,
            aspect_ratio=aspect_ratio,
            label=label or pid,
            seed=seed,
        )
        dt = time.perf_counter() - t0
        if result.get("success"):
            rate.record_success(pid, dt)
            result["route"] = "free_sfw"
            result["aspect_ratio"] = aspect_ratio
            result["prompt"] = sanitized
            result["gate_reason"] = gate.get("reason")
            result["task_tags"] = tags
            result["waited_s"] = round(waited, 2)
            result["latency_s"] = round(dt, 2)
            result["tried_providers"] = tried
            if label:
                result["label"] = label
            return result
        err = str(result.get("error") or "provider_fail")
        errors.append(err)
        rate.record_failure(pid, err)

    return {
        "success": False,
        "error": ";".join(errors) or "all_providers_failed",
        "tried_providers": tried,
        "task_tags": tags,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Fleet free-SFW image offload (multi-provider)")
    ap.add_argument("prompt", nargs="*", default=["landscape", "mountain", "sunset"])
    ap.add_argument("--label", default="sfw")
    ap.add_argument("--aspect", default="1:1", help="1:1|16:9|9:16|portrait|landscape|4:3|3:4")
    ap.add_argument("--provider", default="", help="force provider id")
    ap.add_argument("--skip-gate", action="store_true")
    ap.add_argument("--no-rate-limit", action="store_true")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list-providers", action="store_true")
    args = ap.parse_args()

    if args.list_providers:
        print(json.dumps(list_image_providers(enabled_only=False), indent=2, default=str))
        return 0

    prompt = " ".join(args.prompt) if args.prompt else "landscape mountain sunset"
    gate = classify_image_offload(prompt)
    print(json.dumps({"gate": gate}))
    if not gate.get("allow_t2") and not args.skip_gate:
        return 0
    result = try_fleet_image_generate(
        prompt,
        skip_gate=bool(args.skip_gate),
        label=args.label,
        aspect_ratio=str(args.aspect or "1:1"),
        seed=args.seed,
        provider_id=str(args.provider or "") or None,
        no_rate_limit=bool(args.no_rate_limit),
    )
    print(json.dumps(result, indent=2 if args.json else None, default=str))
    if result.get("success") and result.get("output"):
        print(f"MEDIA:{result['output']}", flush=True)
        return 0
    err = str(result.get("error") or "")
    if "403" in err or "Forbidden" in err:
        print(json.dumps({"smoke": "gate_ok_provider_blocked", "note": "rate_or_auth"}))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
