"""Local ComfyUI image generation backend (Pony / Juggernaut @ :8188).

Delegates to ``skills/creative/uncensored-image-generation/scripts/generate.py``
with Roleplay-Sandbox visual registry for character-aware prompts.
Falls back to ``image_gen.fallback`` provider (typically ``xai`` / Grok) when
ComfyUI is down or render fails.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    ImageGenProvider,
    error_response,
    resolve_aspect_ratio,
    success_response,
)

logger = logging.getLogger(__name__)

_HERMES_SCRIPTS = Path(r"D:\HermesData\scripts")
if str(_HERMES_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_HERMES_SCRIPTS))
from windows_subprocess import hidden_powershell_args, prefer_pythonw, run_hidden  # noqa: E402

COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
GENERATE_PY = Path(
    os.environ.get(
        "COMFY_GENERATE_PY",
        r"D:\HermesData\skills\creative\uncensored-image-generation\scripts\generate.py",
    )
)
_COMFY_PYTHONW = Path(r"D:\ComfyUI\venv\Scripts\pythonw.exe")


def _resolve_comfy_python() -> str:
    """Always prefer Comfy venv pythonw - never flash python.exe consoles."""
    env_py = os.environ.get("COMFY_PYTHON", "").strip()
    for candidate in (str(_COMFY_PYTHONW), env_py, sys.executable):
        if not candidate:
            continue
        py = prefer_pythonw(candidate)
        if Path(py).is_file():
            return py
    return prefer_pythonw(sys.executable)


COMFY_PYTHON = _resolve_comfy_python()
REGISTRY_ROOT = Path(
    os.environ.get("ROLEPLAY_SANDBOX_ROOT", r"D:\PhronesisVault\Roleplay-Sandbox")
)
RENDER_SCRIPT = REGISTRY_ROOT / "sandbox" / "render-roleplay-image.py"
RENDER_LOCK = Path(r"D:\HermesData\state\roleplay-render.lock")
BATCH_ORCHESTRATOR = Path(r"D:\HermesData\scripts\ops\rp_batch_orchestrator.py")
RENDER_POLICY = REGISTRY_ROOT / "runtime" / "render-policy.yaml"
_REGISTRY_LIB = REGISTRY_ROOT / "sandbox" / "lib"

_MODELS: Dict[str, Dict[str, Any]] = {
    "pony": {
        "display": "Pony Diffusion V6 XL (local)",
        "speed": "~30-90s",
        "strengths": "RP portraits/scenes, 832x1216, face+hand detailers",
    },
    "juggernaut": {
        "display": "Juggernaut XL v9 (local)",
        "speed": "~30-90s",
        "strengths": "Photoreal establishing shots, 1024x1024",
    },
}
DEFAULT_MODEL = "pony"

def _get_dynamic_cast_slugs() -> frozenset:
    """Dynamic cast tokens from visual-tags.yaml: full kebab + first-name aliases."""
    try:
        if str(_REGISTRY_LIB) not in sys.path:
            sys.path.insert(0, str(_REGISTRY_LIB))
        from visual_registry import list_cast_names  # noqa: WPS433
        names = list_cast_names()
        if names:
            tokens = set()
            for n in names:
                n = str(n).lower()
                tokens.add(n)
                tokens.add(n.split("-", 1)[0])
            return frozenset(tokens)
    except Exception:
        pass
    # Fallback (expanded for twins + future)
    return frozenset({
        "alice", "chloe", "zara", "lyra", "becca", "emily", "sassy", "valentina",
        "amira", "aisha", "alice-al-rashid", "chloe-ramirez", "zara-mehra",
    })

_CAST_SLUGS = _get_dynamic_cast_slugs()


def _load_comfyui_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("image_gen") if isinstance(cfg, dict) else None
        local = section.get("comfyui_local") if isinstance(section, dict) else None
        return local if isinstance(local, dict) else {}
    except Exception as exc:
        logger.debug("Could not load image_gen.comfyui_local config: %s", exc)
        return {}


def _load_fallback_provider_name() -> Optional[str]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("image_gen") if isinstance(cfg, dict) else None
        if isinstance(section, dict):
            fb = section.get("fallback")
            if fb is None or fb is False:
                return None
            if isinstance(fb, str) and fb.strip().lower() in {"null", "none", "off", "false"}:
                return None
            if isinstance(fb, str) and fb.strip():
                return fb.strip()
    except Exception:
        pass
    return None


def _skip_cloud_fallback(prompt: str) -> bool:
    """RP/explicit prompts stay on local Comfy - never route to moderated cloud APIs."""
    lower = (prompt or "").lower()
    markers = (
        "portrait",
        "explicit",
        "nude",
        "naked",
        "scene:",
        "alice",
        "chloe",
        "becca",
        "emily",
        "lyra",
        "zara",
        "sassy",
        "lingerie",
        "bikini",
        "spread",
        "bedroom",
        "roleplay",
        "ooc:",
    )
    return any(m in lower for m in markers)


def _comfy_up(timeout: float = 3.0) -> bool:
    try:
        with urlopen(f"{COMFY_URL.rstrip('/')}/system_stats", timeout=timeout) as resp:
            return resp.status == 200
    except (URLError, OSError, TimeoutError, ValueError):
        return False


def _bootstrap_comfy_for_render(max_wait_sec: int = 300) -> bool:
    """Free GPU from llama and start ComfyUI when :8188 is down (text mode)."""
    if _comfy_up():
        return True
    yield_ps1 = Path(r"D:\HermesData\scripts\Phronesis-Yield-VRAM-For-Image.ps1")
    stack_ps1 = Path(r"D:\ComfyUI\Comfy-Stack.ps1")
    try:
        if yield_ps1.is_file():
            run_hidden(
                hidden_powershell_args(str(yield_ps1), "-Quiet"),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        if stack_ps1.is_file():
            from windows_subprocess import popen_hidden

            popen_hidden(
                hidden_powershell_args(str(stack_ps1), "start", "inference", "-Quiet"),
                cwd=str(stack_ps1.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("Comfy bootstrap launch failed: %s", exc)
        return False

    deadline = time.time() + max_wait_sec
    while time.time() < deadline:
        if _comfy_up(timeout=5.0):
            logger.info("ComfyUI bootstrap ready on %s", COMFY_URL)
            return True
        time.sleep(4)
    return False


def _render_policy_timeout() -> int:
    if RENDER_POLICY.is_file():
        try:
            import yaml

            with RENDER_POLICY.open(encoding="utf-8") as fh:
                policy = yaml.safe_load(fh) or {}
            return int((policy.get("comfy_timeout_seconds") or {}).get("solo_standard") or 900)
        except Exception:
            pass
    return 900


def _load_visual_registry():
    if str(_REGISTRY_LIB) not in sys.path:
        sys.path.insert(0, str(_REGISTRY_LIB))
    from visual_registry import detect_image_intent  # noqa: WPS433

    return detect_image_intent


def _roleplay_spec_from_prompt(prompt: str) -> Optional[Dict[str, Any]]:
    """Use Roleplay-Sandbox visual registry when RP/OOC markers are present."""
    if not _skip_cloud_fallback(prompt):
        return None
    try:
        detect = _load_visual_registry()
        spec = detect(prompt, "", "")
        return spec if isinstance(spec, dict) else None
    except Exception as exc:
        logger.debug("visual_registry routing failed: %s", exc)
        return None


def _load_rp_inbound_text() -> str:
    inbound_file = Path(r"D:\HermesData\state\rp-last-inbound.json")
    if not inbound_file.is_file():
        return ""
    try:
        import json as _json

        inbound = _json.loads(inbound_file.read_text(encoding="utf-8-sig"))
        if isinstance(inbound, dict):
            return str(inbound.get("text") or "").strip()
    except Exception:
        pass
    return ""


def _resolve_batch_intent(
    prompt: str,
    spec: Optional[Dict[str, Any]] = None,
) -> tuple[int, str]:
    """Prefer last Discord OOC inbound text for series count and delegation prompt."""
    inbound_text = _load_rp_inbound_text()
    prompt_count = _infer_batch_count(prompt, spec, _from_inbound=True)
    inbound_count = (
        _infer_batch_count(inbound_text, None, _from_inbound=True) if inbound_text else 0
    )
    count = max(prompt_count, inbound_count)
    if count >= 2 and inbound_text:
        return count, inbound_text
    return count, prompt


def _infer_batch_count(
    prompt: str,
    spec: Optional[Dict[str, Any]] = None,
    *,
    _from_inbound: bool = False,
) -> int:
    """Centralized via visual_registry (pre-existing harem girls as guideline for future chars)."""
    try:
        import sys
        sys.path.insert(0, r"D:\PhronesisVault\Roleplay-Sandbox\sandbox\lib")
        from visual_registry import resolve_image_count
        return resolve_image_count(prompt, spec)
    except Exception:
        pass
    # minimal fallback
    if spec:
        c = int(spec.get("batch_count") or 0)
        if c >= 1: return c
    return 1

def _delegate_batch_series(
    prompt: str,
    spec: Dict[str, Any],
    *,
    model_id: str,
    aspect: str,
) -> Optional[Dict[str, Any]]:
    """Launch background batch script for OOC series requests (>=2 images)."""
    count = _infer_batch_count(prompt, spec)
    if count < 2 or not BATCH_ORCHESTRATOR.is_file():
        return None
    batch_spec = dict(spec or {})
    batch_spec["batch_count"] = count
    batch_spec.setdefault("batch_mode", "series")
    import json as _json
    import sys as _sys

    try:
        _ops = Path(r"D:\HermesData\scripts\ops")
        if str(_ops) not in _sys.path:
            _sys.path.insert(0, str(_ops))
        from rp_batch_spec import enrich_spec_from_intent  # noqa: WPS433

        inbound_path = Path(r"D:\HermesData\state\rp-last-inbound.json")
        inbound_text = ""
        if inbound_path.is_file():
            try:
                inbound = _json.loads(inbound_path.read_text(encoding="utf-8-sig"))
                if isinstance(inbound, dict):
                    inbound_text = str(inbound.get("text") or "").strip()
            except Exception:
                pass
        batch_spec = enrich_spec_from_intent(prompt, batch_spec, inbound_text=inbound_text)
    except Exception:
        pass

    proc = run_hidden(
        [
            prefer_pythonw(sys.executable),
            str(BATCH_ORCHESTRATOR),
            prompt,
            "--spec-json",
            _json.dumps(batch_spec, ensure_ascii=False),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    payload: Dict[str, Any] = {}
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                payload = _json.loads(line)
            except _json.JSONDecodeError:
                pass
    if not payload.get("ok"):
        err = str(payload.get("error") or proc.stderr or proc.stdout or "orchestrator_failed")[:300]
        logger.warning("batch orchestrator failed: %s", err)
        return error_response(
            error=(
                f"Batch series delegation failed ({err}). "
                "Pass the full OOC line verbatim (e.g. 'OOC: series of 7 images - ...') "
                "or wait for the active batch to finish."
            ),
            error_type="batch_delegation_failed",
            provider="comfyui_local",
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
        )
    series = str(payload.get("series") or "batch series")
    action = str(payload.get("action") or "launched")
    return success_response(
        image="",
        provider="comfyui_local",
        model=model_id,
        prompt=prompt,
        aspect_ratio=aspect,
        extra={
            "batch_delegated": True,
            "batch_series": series,
            "batch_action": action,
            "batch_count": count,
            "message": (
                f"Batch series {action} ({series}, {count} images). "
                "Images auto-post to Discord via delivery daemon - respond with "
                "short OOC narration; do not retry image_generate this turn."
            ),
        },
    )


def _versatile_route(prompt: str, *, model_hint: Optional[str] = None, spec: Optional[Dict[str, Any]] = None):
    try:
        if str(_HERMES_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(_HERMES_SCRIPTS))
        from comfy_versatile_router import route_image_prompt  # noqa: WPS433

        return route_image_prompt(prompt, model_hint=str(model_hint or ""), spec=spec)
    except Exception as exc:
        logger.debug("versatile router fallback: %s", exc)
        return None


def _parse_prompt_routing(prompt: str, *, model_hint: Optional[str] = None) -> Dict[str, Any]:
    """Map natural language to generate.py flags (fallback when registry has no spec)."""
    text = (prompt or "").strip()
    lower = text.lower()
    model = (model_hint or DEFAULT_MODEL).strip().lower()
    if model not in _MODELS:
        if "juggernaut" in lower or "photo" in lower or "realistic" in lower:
            model = "juggernaut"
        else:
            model = DEFAULT_MODEL

    characters: List[str] = []
    # Prefer longer full-kebab tokens first so alice-al-rashid beats alice
    for slug in sorted(_CAST_SLUGS, key=len, reverse=True):
        if re.search(rf"(?<![\w-]){re.escape(slug)}(?![\w-])", lower):
            if slug not in characters:
                characters.append(slug)
    # Map first-name aliases to canonical first-last-kebab cast keys
    try:
        if str(_REGISTRY_LIB) not in sys.path:
            sys.path.insert(0, str(_REGISTRY_LIB))
        from visual_registry import resolve_cast_slug  # noqa: WPS433
        resolved: List[str] = []
        for c in characters:
            r = resolve_cast_slug(c)
            if r not in resolved:
                resolved.append(r)
        characters = resolved
    except Exception:
        pass

    scene = ""
    for pat in (
        r"scene:\s*([^,;]+)",
        r"scene\s+([^,;]+)",
        r"in\s+(?:the\s+)?([a-z][a-z\s'-]{2,40})",
    ):
        m = re.search(pat, lower, re.IGNORECASE)
        if m:
            scene = m.group(1).strip()
            break

    mode = "portrait"
    if any(k in lower for k in ("nude", "naked", "explicit", "nsfw")):
        mode = "explicit"
    elif any(k in lower for k in ("establishing", "wide shot", "landscape", "manor exterior")):
        mode = "establishing"
    elif scene or any(k in lower for k in ("scene", "bedroom", "kiss", "together", "duo")):
        mode = "scene"
    elif any(k in lower for k in ("tease", "lingerie", "undress")):
        mode = "tease"

    return {
        "model": model,
        "characters": characters[:2],
        "scene": scene,
        "registry_mode": mode,
        "raw_prompt": text,
        "fresh": mode == "explicit" or "fresh" in lower or "alternate" in lower,
    }


def _build_render_cmd(spec: Dict[str, Any]) -> List[str]:
    """Route through render-roleplay-image.py for fidelity (explicit/solo/duo)."""
    py = prefer_pythonw(sys.executable)
    cmd = [py, str(RENDER_SCRIPT), "--json", "--standard", "--discord-delivery", "--skip-lock"]
    if spec.get("candidate"):
        cmd.extend(["--candidate", str(spec["candidate"])])
        if spec.get("fresh"):
            cmd.append("--fresh")
        return cmd
    chars = spec.get("characters") or []
    mode = str(spec.get("mode") or "portrait")
    if len(chars) >= 2 and mode in ("portrait", "scene"):
        mode = "duo" if mode == "portrait" else mode
    cmd.extend(["--mode", mode])
    if spec.get("fresh"):
        cmd.append("--fresh")
        cmd.append("--new-seed")
    if spec.get("alternate"):
        cmd.extend(["--alternate", str(spec["alternate"])])
    for i, c in enumerate(chars[:2]):
        if i == 0:
            cmd.extend(["--character", c])
        else:
            cmd.extend(["--with", c])
    if spec.get("scene"):
        cmd.extend(["--scene", str(spec["scene"])])
    return cmd


def _normalize_registry_mode(mode: str) -> str:
    """generate.py only accepts portrait|tease|scene|establishing."""
    aliases = {
        "group": "scene",
        "freeform": "scene",
        "explicit": "scene",
        "duo": "scene",
    }
    key = (mode or "portrait").strip().lower()
    key = aliases.get(key, key)
    if key not in ("portrait", "tease", "scene", "establishing"):
        return "scene"
    return key


def _build_generate_cmd(
    route: Dict[str, Any],
    *,
    aspect: str,
    spec: Optional[Dict[str, Any]] = None,
    versatile: Optional[Any] = None,
) -> List[str]:
    py = _resolve_comfy_python()
    spec = spec or {}
    model = str(route.get("model") or DEFAULT_MODEL)
    cmd = [
        py,
        str(GENERATE_PY),
        "-m",
        model,
        "--timeout",
        str(_render_policy_timeout()),
    ]
    path = str(versatile.path if versatile else "freeform")
    use_registry = bool(versatile and versatile.use_registry and route.get("characters") and path == "canon")
    use_enriched = path in ("freeform", "character_enriched")
    if use_registry:
        registry_mode = _normalize_registry_mode(str(route.get("registry_mode") or "portrait"))
        cmd.extend(
            [
                "--registry-root",
                str(REGISTRY_ROOT),
                "--registry-mode",
                registry_mode,
            ]
        )
    mode = str(spec.get("mode") or route.get("registry_mode") or "")
    aspect_use = str(versatile.aspect if versatile else aspect)
    if aspect_use == "square":
        cmd.extend(["--width", "1024", "--height", "1024"])
    elif aspect_use == "landscape" or mode in ("group", "duo", "scene") or aspect == "landscape":
        cmd.extend(["--width", "1216", "--height", "832"])
    else:
        cmd.extend(["--width", "832", "--height", "1216"])
    prompt_text = str(
        (versatile.final_prompt if versatile else "")
        or spec.get("freeform_prompt")
        or route.get("raw_prompt")
        or ""
    )
    chars = route.get("characters") or []
    if use_registry and chars:
        for c in chars[:1]:
            cmd.extend(["--character", c])
        if len(chars) >= 2:
            cmd.extend(["--with", chars[1]])
        if route.get("scene"):
            cmd.extend(["--scene", route["scene"]])
    elif use_enriched or spec.get("freeform_prompt") or spec.get("reason") in ("ooc_freeform", "ooc_enriched"):
        cmd.extend(["-p", prompt_text])
    else:
        cmd.extend(["-p", prompt_text])
    tags = str(spec.get("tags") or (versatile.tags if versatile else "") or "freeform")
    if tags:
        cmd.extend(["--tags", tags])
    neg = str(spec.get("negative_extra") or (versatile.negative_extra if versatile else "") or "")
    if neg:
        cmd.extend(["--negative-extra", neg])
    if versatile and versatile.no_detailers:
        cmd.append("--no-hand-detailer")
        cmd.append("--no-face-detailer")
    if spec.get("reason") == "ooc_freeform" or (versatile and versatile.path == "freeform"):
        cmd.extend(["--context", f"roleplay:freeform:{mode or 'versatile'}"])
    return cmd


def _acquire_render_lock(timeout_sec: int = 30) -> bool:
    RENDER_LOCK.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with RENDER_LOCK.open("x", encoding="utf-8") as fh:
                fh.write(f"{os.getpid()}:{time.time():.0f}")
            return True
        except FileExistsError:
            try:
                raw = RENDER_LOCK.read_text(encoding="utf-8").strip()
                ts = float(raw.split(":", 1)[-1]) if ":" in raw else 0.0
            except Exception:
                ts = 0.0
            if ts and time.time() - ts > 1800:
                try:
                    RENDER_LOCK.unlink(missing_ok=True)
                except OSError:
                    pass
            time.sleep(2)
        except OSError:
            time.sleep(2)
    return False


def _release_render_lock() -> None:
    try:
        RENDER_LOCK.unlink(missing_ok=True)
    except OSError:
        pass


COMFY_OUTPUT = Path(r"D:\ComfyUI\output")


def _parse_image_path(stdout: str) -> Optional[str]:
    for line in (stdout or "").splitlines():
        line = line.strip()
        if line.startswith("IMAGE_PATH="):
            path = line.split("=", 1)[1].strip()
            if path and Path(path).is_file():
                return path
    return None


def _recover_latest_comfy_png(
    since_ts: float,
    *,
    min_bytes: int = 800_000,
    poll_sec: float = 2.0,
    max_wait_sec: float = 270.0,
) -> Optional[str]:
    """Poll Comfy output when subprocess exits without IMAGE_PATH (common 1s race)."""
    deadline = time.time() + max_wait_sec
    best_path: Optional[Path] = None
    best_mtime = 0.0
    while time.time() < deadline:
        for path in COMFY_OUTPUT.glob("standard__*.png"):
            try:
                st = path.stat()
            except OSError:
                continue
            if st.st_mtime < since_ts - 2.0 or st.st_size < min_bytes:
                continue
            if st.st_mtime > best_mtime:
                best_mtime = st.st_mtime
                best_path = path
        if best_path and best_path.is_file():
            logger.info("Recovered Comfy PNG from output folder: %s", best_path.name)
            return str(best_path.resolve())
        time.sleep(poll_sec)
    return None


def _try_t2_image_offload(
    prompt: str,
    aspect: str,
    *,
    reason: str,
    model_id: str,
) -> Optional[Dict[str, Any]]:
    """Phase 8a: optional free T2 image before paid fallback (SFW gate required)."""
    try:
        from fleet_image_offload import try_fleet_image_generate

        t2 = try_fleet_image_generate(prompt, aspect_ratio=aspect)
        if isinstance(t2, dict) and t2.get("success"):
            return success_response(
                image=str(t2.get("image") or ""),
                model=str(t2.get("model") or "t2-sfw"),
                prompt=str(t2.get("prompt") or prompt),
                aspect_ratio=aspect,
                provider=str(t2.get("provider") or "fleet_image_offload"),
                extra={
                    "fallback_from": "comfyui_local",
                    "fallback_reason": reason,
                    "route": t2.get("route", "t2_image_optional"),
                    "gate_reason": t2.get("gate_reason"),
                },
            )
    except Exception as exc:
        logger.debug("T2 image offload skipped: %s", exc)
    return None


def _try_fallback(
    prompt: str,
    aspect: str,
    *,
    reason: str,
    model_id: str,
) -> Dict[str, Any]:
    if _skip_cloud_fallback(prompt):
        return error_response(
            error=f"{reason}; local-only policy (no cloud fallback for RP/explicit prompts)",
            error_type="comfy_unavailable",
            provider="comfyui_local",
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
        )
    t2_result = _try_t2_image_offload(prompt, aspect, reason=reason, model_id=model_id)
    if t2_result is not None:
        return t2_result
    fb_name = _load_fallback_provider_name()
    if not fb_name:
        return error_response(
            error=reason,
            error_type="comfy_unavailable",
            provider="comfyui_local",
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
        )
    try:
        from agent.image_gen_registry import get_provider
        from hermes_cli.plugins import _ensure_plugins_discovered

        _ensure_plugins_discovered(force=True)
        fb = get_provider(fb_name)
        if fb is None or not fb.is_available():
            return error_response(
                error=f"{reason}; fallback '{fb_name}' unavailable",
                error_type="fallback_unavailable",
                provider="comfyui_local",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        result = fb.generate(prompt=prompt, aspect_ratio=aspect)
        if isinstance(result, dict) and result.get("success"):
            result.setdefault("provider", fb_name)
            result["fallback_from"] = "comfyui_local"
            result["fallback_reason"] = reason
        return result if isinstance(result, dict) else error_response(
            error=f"{reason}; fallback returned invalid payload",
            provider="comfyui_local",
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
        )
    except Exception as exc:
        logger.warning("comfyui_local fallback to %s failed: %s", fb_name, exc)
        return error_response(
            error=f"{reason}; fallback error: {exc}",
            error_type="fallback_error",
            provider="comfyui_local",
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
        )


class ComfyUILocalImageGenProvider(ImageGenProvider):
    """Local ComfyUI Pony/Juggernaut backend."""

    @property
    def name(self) -> str:
        return "comfyui_local"

    @property
    def display_name(self) -> str:
        return "ComfyUI Local (Pony/Juggernaut)"

    def is_available(self) -> bool:
        return _comfy_up() and GENERATE_PY.is_file()

    def list_models(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": mid,
                "display": meta.get("display", mid),
                "speed": meta.get("speed", ""),
                "strengths": meta.get("strengths", ""),
            }
            for mid, meta in _MODELS.items()
        ]

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "ComfyUI Local",
            "badge": "local",
            "tag": "Pony/Juggernaut @ :8188 - 832x1216 RP standard; local-only for RP/explicit",
            "env_vars": [
                {"key": "COMFY_URL", "prompt": "ComfyUI base URL", "url": ""},
            ],
        }

    def capabilities(self) -> Dict[str, Any]:
        return {"modalities": ["text"], "max_reference_images": 0}

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        *,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if image_url or reference_image_urls:
            return error_response(
                error="comfyui_local supports text-to-image only (no image_url editing)",
                error_type="modality_unsupported",
                provider="comfyui_local",
                prompt=prompt,
                aspect_ratio=aspect_ratio,
            )

        aspect = resolve_aspect_ratio(aspect_ratio)
        cfg = _load_comfyui_config()
        model_hint = kwargs.get("model") or cfg.get("model")
        spec = _roleplay_spec_from_prompt(prompt)
        versatile = _versatile_route(
            prompt,
            model_hint=str(model_hint) if model_hint else None,
            spec=spec,
        )
        route = _parse_prompt_routing(prompt, model_hint=str(model_hint) if model_hint else None)
        if versatile:
            route["model"] = versatile.model
            route["registry_mode"] = versatile.registry_mode
            route["characters"] = list(versatile.characters or [])
            route["raw_prompt"] = versatile.final_prompt
            if versatile.fresh:
                route["fresh"] = True
        if spec:
            route["registry_mode"] = str(spec.get("mode") or route["registry_mode"])
            if versatile and versatile.use_registry:
                route["characters"] = list(spec.get("characters") or route.get("characters") or [])
            if spec.get("freeform_prompt") and not (versatile and versatile.use_registry):
                route["registry_mode"] = "freeform"
        use_render_script = bool(
            versatile
            and versatile.path == "canon"
            and spec
            and RENDER_SCRIPT.is_file()
            and (spec.get("characters") or spec.get("candidate"))
            and spec.get("reason") not in ("ooc_freeform", "ooc_enriched")
        )
        if versatile and versatile.path == "character_enriched" and spec:
            spec = dict(spec)
            spec["freeform_prompt"] = versatile.final_prompt
            spec["negative_extra"] = versatile.negative_extra
            spec["tags"] = versatile.tags
            spec["reason"] = "ooc_enriched"
            spec["fresh"] = True
        model_id = route["model"]

        try:
            from inference_queue import should_defer_comfy_render

            defer, defer_reason = should_defer_comfy_render()
            if defer:
                return error_response(
                    error=(
                        f"GPU busy ({defer_reason}) — Qwythos inference has priority. "
                        "Retry OOC portrait in ~60s or run .\\Phronesis.ps1 vram image wait."
                    ),
                    error_type="gpu_inference_busy",
                    provider="comfyui_local",
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )
        except Exception as exc:
            logger.debug("inference defer check skipped: %s", exc)

        if not _comfy_up():
            booted = _bootstrap_comfy_for_render()
            if not booted:
                hint = (
                    "ComfyUI not reachable at "
                    + COMFY_URL
                    + " after auto-bootstrap (yielded GPU + start attempt). "
                    + "Jeff: run .\\Phronesis.ps1 vram image wait for Comfy on :8188 "
                    + "then resend OOC portrait. Chat needs .\\Phronesis.ps1 vram text after."
                )
                return error_response(
                    error=hint,
                    error_type="comfy_bootstrap_failed",
                    provider="comfyui_local",
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )

        batch_count = int(versatile.batch_count if versatile else 0) or 0
        delegate_prompt = prompt
        if batch_count < 2:
            batch_count, delegate_prompt = _resolve_batch_intent(prompt, spec)
        if batch_count >= 2:
            delegated = _delegate_batch_series(
                delegate_prompt,
                spec or {},
                model_id=model_id,
                aspect=aspect,
            )
            if delegated is not None:
                return delegated

        if use_render_script and spec:
            cmd = _build_render_cmd(spec)
            cwd = str(RENDER_SCRIPT.parent)
            timeout = _render_policy_timeout() + 120
        else:
            cmd = _build_generate_cmd(route, aspect=aspect, spec=spec, versatile=versatile)
            cwd = str(GENERATE_PY.parent)
            timeout = _render_policy_timeout() + 60

        if not _acquire_render_lock(timeout_sec=120):
            return error_response(
                error="Another roleplay render is in progress - batch or prior render still running; retry in ~60s",
                error_type="render_busy",
                provider="comfyui_local",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        render_started = time.time()
        image_path: Optional[str] = None
        proc = None
        try:
            proc = run_hidden(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            image_path = _recover_latest_comfy_png(render_started)
            if not image_path:
                return _try_fallback(prompt, aspect, reason="ComfyUI render timed out", model_id=model_id)
        except Exception as exc:
            return _try_fallback(prompt, aspect, reason=f"ComfyUI subprocess error: {exc}", model_id=model_id)
        finally:
            _release_render_lock()

        if image_path is None and proc is not None:
            if proc.returncode != 0:
                image_path = _recover_latest_comfy_png(render_started)
                if not image_path:
                    err = (proc.stderr or proc.stdout or "")[:400]
                    return _try_fallback(
                        prompt, aspect, reason=f"ComfyUI render failed (rc={proc.returncode}): {err}", model_id=model_id
                    )
            else:
                image_path = _parse_image_path(proc.stdout or "")

        if use_render_script and spec and proc:
            for line in (proc.stdout or "").splitlines():
                line = line.strip()
                if line.startswith("{"):
                    try:
                        import json

                        payload = json.loads(line)
                        image_path = payload.get("gallery_image") or payload.get("image") or image_path
                    except Exception:
                        pass
                    break
        if not image_path:
            image_path = _recover_latest_comfy_png(render_started)
        if not image_path:
            return _try_fallback(prompt, aspect, reason="ComfyUI returned no IMAGE_PATH", model_id=model_id)

        p = Path(image_path)
        min_bytes = 800_000
        if RENDER_POLICY.is_file():
            try:
                import yaml

                with RENDER_POLICY.open(encoding="utf-8") as fh:
                    min_bytes = int((yaml.safe_load(fh) or {}).get("min_delivery_bytes") or min_bytes)
            except Exception:
                pass
        if p.stat().st_size < min_bytes:
            return _try_fallback(
                prompt,
                aspect,
                reason=f"Output below delivery floor ({p.stat().st_size} < {min_bytes} bytes)",
                model_id=model_id,
            )

        return success_response(
            image=str(p.resolve()),
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
            provider="comfyui_local",
            modality="text",
            extra={
                "width": 832 if model_id == "pony" else 1024,
                "height": 1216 if model_id == "pony" else 1024,
                "characters": route.get("characters"),
                "registry_mode": route.get("registry_mode"),
                "comfy_url": COMFY_URL,
            },
        )


def register(ctx: Any) -> None:
    ctx.register_image_gen_provider(ComfyUILocalImageGenProvider())