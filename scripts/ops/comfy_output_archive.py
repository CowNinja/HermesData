"""Archive Comfy output PNGs to gallery + durable versioned series folders on delivery."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

COMFY_OUTPUT = Path(r"D:\ComfyUI\output")
GALLERY_SIDE = Path(r"D:\ComfyUI\gallery\sidecars")
GENERATE_PY = Path(
    os.environ.get(
        "COMFY_GENERATE_PY",
        r"D:\HermesData\skills\creative\uncensored-image-generation\scripts\generate.py",
    )
)
BATCH_SESSION = Path(r"D:\HermesData\state\comfy-batch-session.json")
ARCHIVE_REGISTRY = Path(r"D:\HermesData\state\comfy-output-archive.json")
SERIES_ROOT = Path(r"D:\PhronesisVault\Roleplay-Sandbox\gallery\series")
MANIFEST_NAME = "series_manifest.json"
LEGACY_MANIFEST = "series-manifest.json"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_copy(src: Path, dest: Path) -> str:
    """Copy with checksum verify; temp file then replace (same volume)."""
    digest = _sha256_file(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        if tmp.is_file():
            tmp.unlink()
        shutil.copy2(str(src), str(tmp))
        if _sha256_file(tmp) != digest:
            raise OSError(f"checksum mismatch after copy: {src.name}")
        tmp.replace(dest)
    finally:
        if tmp.is_file() and not dest.is_file():
            try:
                tmp.unlink()
            except OSError:
                pass
    if _sha256_file(dest) != digest:
        raise OSError(f"checksum mismatch at dest: {dest.name}")
    return digest


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_generate():
    os.environ.setdefault("HERMES_PYTHONW_REEXEC", "1")
    spec = importlib.util.spec_from_file_location("comfy_generate", GENERATE_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {GENERATE_PY}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_batch_session() -> dict:
    if not BATCH_SESSION.is_file():
        return {}
    try:
        data = json.loads(BATCH_SESSION.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _png_index(name: str) -> int | None:
    ops = Path(__file__).resolve().parent
    if str(ops) not in sys.path:
        sys.path.insert(0, str(ops))
    from comfy_output_patterns import parse_png_index  # noqa: WPS433

    return parse_png_index(name)


def _batch_label(session: dict, png_name: str) -> str:
    start = int(session.get("series_start_png") or 0)
    idx = _png_index(png_name)
    if start and idx and idx >= start:
        labels = list(session.get("labels") or [])
        pos = idx - start
        if 0 <= pos < len(labels):
            return str(labels[pos])
    return ""


def _cast_slugs(session: dict) -> list[str]:
    audit = session.get("canon_audit") or {}
    cast = audit.get("cast") or {}
    if isinstance(cast, dict):
        return sorted(str(k) for k in cast.keys())
    return []


def _sidecar_for_output(png_name: str) -> Path | None:
    needle = str((COMFY_OUTPUT / png_name).resolve()).lower()
    if not GALLERY_SIDE.is_dir():
        return None
    for path in GALLERY_SIDE.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        src = str(data.get("source_comfy_output") or "").lower()
        if src and src == needle:
            return path
    return None


def _prompt_fragment(sidecar: Path | None, label: str, caption: str) -> str:
    if sidecar and sidecar.is_file():
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8-sig"))
            prompt = str(data.get("prompt") or "").strip()
            if prompt:
                return prompt[:500]
        except Exception:
            pass
    return (caption or label or "").strip()[:500]


def _load_archive_registry() -> dict:
    if not ARCHIVE_REGISTRY.is_file():
        return {"archived": {}}
    try:
        data = json.loads(ARCHIVE_REGISTRY.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            data.setdefault("archived", {})
            return data
    except Exception:
        pass
    return {"archived": {}}


def _save_archive_registry(reg: dict) -> None:
    ARCHIVE_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(ARCHIVE_REGISTRY, reg)


def _series_dir(session: dict) -> Path | None:
    recipe = str(session.get("recipe") or "").strip()
    if not recipe:
        return None
    started = str(session.get("started_at") or time.strftime("%Y-%m-%dT%H:%M:%S"))
    day = started.split("T", 1)[0]
    return SERIES_ROOT / recipe / day


def _load_manifest(series_dir: Path) -> dict:
    path = series_dir / MANIFEST_NAME
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                data.setdefault("frames", [])
                return data
        except Exception:
            pass
    legacy = series_dir / LEGACY_MANIFEST
    if legacy.is_file():
        try:
            raw = json.loads(legacy.read_text(encoding="utf-8-sig"))
            if isinstance(raw, list):
                return {"frames": raw, "_migrated_from": LEGACY_MANIFEST}
        except Exception:
            pass
    return {}


def _ensure_manifest_header(manifest: dict, session: dict, series_dir: Path) -> dict:
    if manifest.get("series") and manifest.get("recipe"):
        return manifest
    return {
        "series": str(session.get("series") or ""),
        "recipe": str(session.get("recipe") or ""),
        "total": int(session.get("total") or 0),
        "series_start_png": int(session.get("series_start_png") or 0),
        "started_at": str(session.get("started_at") or ""),
        "cast": _cast_slugs(session),
        "series_dir": str(series_dir),
        "frames": list(manifest.get("frames") or []),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _upsert_frame(manifest: dict, frame: dict) -> None:
    frames = list(manifest.get("frames") or [])
    png = str(frame.get("png") or "")
    replaced = False
    for i, row in enumerate(frames):
        if str(row.get("png") or "") == png:
            frames[i] = {**row, **frame}
            replaced = True
            break
    if not replaced:
        frames.append(frame)
    frames.sort(key=lambda r: _png_index(str(r.get("png") or "")) or 0)
    manifest["frames"] = frames
    manifest["archived_count"] = len(frames)
    manifest["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")


def archive_png(
    png_path: Path,
    *,
    label: str = "",
    caption: str = "",
    wait_sec: float = 2.0,
) -> dict:
    """Copy PNG to gallery (if needed) and versioned series archive with manifest."""
    if not png_path.is_file():
        return {"ok": False, "reason": "missing", "png": png_path.name}

    session = _load_batch_session()
    label = label or _batch_label(session, png_path.name)
    reg = _load_archive_registry()
    prior = dict((reg.get("archived") or {}).get(png_path.name) or {})

    if prior.get("sha256") and prior.get("series_copy") and _sidecar_for_output(png_path.name):
        return {"ok": True, "action": "already_archived", "png": png_path.name, **prior}

    deadline = time.time() + max(0.5, wait_sec)
    while time.time() < deadline and not png_path.is_file():
        time.sleep(0.25)

    source_sha = _sha256_file(png_path)
    gallery_name = prior.get("gallery_name") or ""
    gallery_image = prior.get("gallery_image") or ""
    sidecar = _sidecar_for_output(png_path.name)
    if sidecar and sidecar.is_file():
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8-sig"))
            gallery_name = str(meta.get("filename") or gallery_name)
            gallery_image = str(meta.get("filepath") or gallery_image)
        except Exception:
            pass

    if not sidecar:
        try:
            gen = _load_generate()
            prompt = caption or label or f"roleplay deliver {png_path.name}"
            gal_path, gal_name = gen.gallery_log(
                str(png_path),
                prompt,
                "pony",
                0,
                "standard",
                tags="roleplay,batch,deliver",
                context=f"roleplay:deliver:{png_path.stem}",
            )
            gallery_name = gal_name
            gallery_image = gal_path
            sidecar = _sidecar_for_output(png_path.name)
        except Exception as exc:
            return {"ok": False, "reason": f"gallery_log:{exc}", "png": png_path.name}

    series_copy = prior.get("series_copy") or ""
    archive_sha = prior.get("sha256") or ""
    series_dir = _series_dir(session)
    if series_dir:
        series_dir.mkdir(parents=True, exist_ok=True)
        dest = series_dir / png_path.name
        if not dest.is_file() or _sha256_file(dest) != source_sha:
            archive_sha = _atomic_copy(png_path, dest)
        else:
            archive_sha = _sha256_file(dest)
        series_copy = str(dest)

        manifest = _ensure_manifest_header(_load_manifest(series_dir), session, series_dir)
        start = int(session.get("series_start_png") or 0)
        idx = _png_index(png_path.name)
        frame_index = (idx - start + 1) if start and idx and idx >= start else 0
        _upsert_frame(
            manifest,
            {
                "index": frame_index,
                "png": png_path.name,
                "label": label,
                "sha256": archive_sha,
                "source_sha256": source_sha,
                "gallery_name": gallery_name,
                "gallery_image": gallery_image,
                "prompt_fragment": _prompt_fragment(sidecar, label, caption),
                "archived_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "discord_registry": True,
            },
        )
        _atomic_write_json(series_dir / MANIFEST_NAME, manifest)

    record = {
        "gallery_name": gallery_name,
        "gallery_image": gallery_image,
        "gallery_sidecar": str(sidecar) if sidecar else "",
        "series_copy": series_copy,
        "sha256": archive_sha or source_sha,
        "label": label,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    archived = dict(reg.get("archived") or {})
    archived[png_path.name] = record
    reg["archived"] = archived
    _save_archive_registry(reg)
    return {"ok": True, "action": "archived", "png": png_path.name, **record}


def backfill_range(start: int, end: int) -> dict:
    """Archive any standard__ PNGs in [start, end] that lack gallery sidecars."""
    done: list[str] = []
    skipped: list[str] = []
    errors: list[dict] = []
    for n in range(start, end + 1):
        name = f"standard__{n:05d}_.png"
        path = COMFY_OUTPUT / name
        if not path.is_file():
            skipped.append(name)
            continue
        result = archive_png(path)
        if result.get("ok"):
            done.append(name)
        else:
            errors.append(result)
    return {"ok": not errors, "archived": done, "missing": skipped, "errors": errors}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Archive Comfy output PNGs to gallery + series folder")
    parser.add_argument("--backfill", nargs=2, type=int, metavar=("START", "END"))
    parser.add_argument("--verify-manifest", metavar="SERIES_DIR")
    parser.add_argument("png", nargs="?", help="Single standard__ PNG name or path")
    args = parser.parse_args()

    if args.verify_manifest:
        series_dir = Path(args.verify_manifest)
        manifest_path = series_dir / MANIFEST_NAME
        if not manifest_path.is_file():
            print(json.dumps({"ok": False, "reason": "no_manifest"}))
            return 1
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        bad: list[dict] = []
        for frame in manifest.get("frames") or []:
            png = str(frame.get("png") or "")
            path = series_dir / png
            if not path.is_file():
                bad.append({"png": png, "reason": "missing"})
                continue
            sha = _sha256_file(path)
            if sha != str(frame.get("sha256") or ""):
                bad.append({"png": png, "reason": "sha256_mismatch", "disk": sha})
        out = {"ok": not bad, "frames": len(manifest.get("frames") or []), "bad": bad}
        print(json.dumps(out, indent=2))
        return 0 if out["ok"] else 1

    if args.backfill:
        result = backfill_range(args.backfill[0], args.backfill[1])
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1

    if args.png:
        path = Path(args.png)
        ops = Path(__file__).resolve().parent
        if str(ops) not in sys.path:
            sys.path.insert(0, str(ops))
        from comfy_output_patterns import is_batch_png  # noqa: WPS433

        if is_batch_png(path.name):
            path = COMFY_OUTPUT / path.name if not path.is_file() else path
        result = archive_png(path)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())