#!/usr/bin/env python3
"""
ComfyUI duplicate image purge (content-hash SHA256).

Targets:
  - D:\\ComfyUI\\gallery\\images   (main bulk — re-import / watchdog copies)
  - D:\\ComfyUI\\output           (milder; optional)

Default: DRY-RUN. Prints plan + writes JSON report. No deletes.
Apply:   --apply   (moves dups to quarantine OR --hard-delete)

Keep policy per hash group (highest score wins):
  1. DB rating / thumbs
  2. Explicit PREFERRED_IMMERSION_NAMES (canonical / gallery aliases)
  3. "canonical" / "latest" / short alias names (no timestamp spam)
  4. Prefer gallery over raw Comfy output names (standard__/full__)
  5. Prefer earliest mtime / shorter path

Immersion mode (default on apply):
  - Merge metadata (rating/thumbs/tags/prompt/context) across dup DB rows + sidecars
    into the kept row / keep sidecar.
  - Preserve immersion alias filenames as hardlinks (same inode) under gallery/images
    so RP paths like alice_sandbox_canonical.png and *_portrait_gallery.png keep working.
  - Quarantine only true byte-dups that are not preserved as alias hardlinks.
  - Clean orphaned DB rows for quarantined names; keep/merge rows for surviving names.

Usage:
  PYTHONPATH="" /d/ComfyUI/venv/Scripts/python.exe \\
    D:/HermesData/scripts/comfy_purge_duplicate_images.py --scope both
  ... --scope both --apply
  ... --scope both --apply --hard-delete
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

GALLERY_DIR = Path(r"D:\ComfyUI\gallery")
IMAGE_DIR = GALLERY_DIR / "images"
SIDECAR_DIR = GALLERY_DIR / "sidecars"
DB_PATH = GALLERY_DIR / "gallery.db"
OUTPUT_DIR = Path(r"D:\ComfyUI\output")
REPORT_DIR = Path(r"D:\HermesData\logs")
QUARANTINE_ROOT = GALLERY_DIR / "_dedup_quarantine"
EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

ALIAS_HINTS = (
    "canonical",
    "latest",
    "replacement",
    "_gallery.png",
    "alice_portrait",
    "alice_sandbox",
    "alice_nasty",
    "alice_canonical",
    "lyra_portrait",
    "emily_portrait",
    "becca_portrait",
    "chloe_portrait",
    "sassy_portrait",
    "zara_portrait",
    "breakfast_dining",
    "group3_",
    "group4_",
    "glitches-to-grace",
    "orgy_birthday",
    "comparison_",
)

# Explicit immersion names (hardlink-preserved + strong keep bias)
PREFERRED_IMMERSION_NAMES = {
    "alice_sandbox_canonical.png",
    "alice_nasty_solo_replacement_latest.png",
    "alice_portrait_canonical.png",
    "2026-07-09_alice_portrait_canonical.png",
    "alice_portrait_gallery.png",
    "chloe_portrait_gallery.png",
    "becca_portrait_gallery.png",
    "emily_portrait_gallery.png",
    "sassy_portrait_gallery.png",
    "lyra_portrait_gallery.png",
    "zara_portrait_gallery.png",
    "group3_alice_chloe_becca.png",
    "group4_emily_sassy_lyra_zara.png",
    "breakfast_dining_7girls.png",
    "glitches-to-grace-cover.png",
    "orgy_birthday_01.png",
    "alice_portrait_replacement_2026-07-09.png",
    "alice_canonical_sandbox_portrait_20260710_084637.png",
}

# Names worth preserving as hardlinks even if not the primary keep target
IMMERSION_ALIAS_RE = re.compile(
    r"(?:^alice_|^chloe_|^becca_|^emily_|^sassy_|^lyra_|^zara_|"
    r"^group[34]_|breakfast_|glitches-to-grace|orgy_birthday|"
    r"canonical|latest|replacement|_gallery\.png$|^comparison_)",
    re.I,
)

# Stable short aliases that should always hardlink to a preferred cluster member if present
STABLE_ALIAS_TARGETS = {
    # short name -> preferred source basenames (first existing wins)
    "alice_portrait_canonical.png": [
        "alice_sandbox_canonical.png",
        "alice_nasty_solo_replacement_latest.png",
        "2026-07-09_alice_portrait_canonical.png",
    ],
}

TS_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}[_-]")
OUTPUT_GENERIC = re.compile(r"^(standard|full|draft)__\d+_\.png$", re.I)


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def collect(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    # top-level only for output/gallery images (avoid quarantine recursion)
    out = []
    for p in root.iterdir() if root in (IMAGE_DIR, OUTPUT_DIR) else root.rglob("*"):
        if p.is_file() and p.suffix.lower() in EXTS:
            out.append(p)
        elif p.is_dir() and root not in (IMAGE_DIR, OUTPUT_DIR):
            continue
    # if rglob path for other roots
    if root not in (IMAGE_DIR, OUTPUT_DIR):
        return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in EXTS]
    return out


def is_immersion_name(name: str) -> bool:
    if name in PREFERRED_IMMERSION_NAMES:
        return True
    if IMMERSION_ALIAS_RE.search(name):
        # exclude pure timestamp juggernaut spam unless preferred
        if TS_PREFIX.match(name) and "juggernaut" in name.lower():
            return False
        if not TS_PREFIX.match(name):
            return True
        if "canonical" in name.lower() or "gallery" in name.lower() or "replacement" in name.lower():
            return True
    return False


def load_db_rows() -> dict[str, dict]:
    """Map lower(filepath) and lower(filename) -> full DB row dict."""
    meta: dict[str, dict] = {}
    if not DB_PATH.exists():
        return meta
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    try:
        cols = [c[1] for c in con.execute("PRAGMA table_info(images)")]
        for row in con.execute("SELECT * FROM images"):
            d = {c: row[c] for c in cols}
            d["rating"] = d.get("rating") or 0
            d["thumbs"] = d.get("thumbs") or 0
            d["tags"] = d.get("tags") or ""
            d["prompt"] = d.get("prompt") or ""
            d["negative_prompt"] = d.get("negative_prompt") or ""
            d["context"] = d.get("context") or ""
            d["sidecar_path"] = d.get("sidecar_path") or ""
            fp = (d.get("filepath") or "").replace("/", "\\")
            keys = []
            if fp:
                keys.append(str(Path(fp)).lower())
            fn = d.get("filename") or ""
            if fn:
                keys.append(str((IMAGE_DIR / fn).resolve()).lower())
                keys.append(fn.lower())
            for key in keys:
                prev = meta.get(key)
                if prev is None or (d["rating"], d["thumbs"], d.get("id") or 0) > (
                    prev["rating"],
                    prev["thumbs"],
                    prev.get("id") or 0,
                ):
                    meta[key] = d
    finally:
        con.close()
    return meta


def load_sidecar(path: Path) -> dict:
    if not path or not Path(path).exists():
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def merge_tags(*tag_blobs: str) -> str:
    seen: list[str] = []
    for blob in tag_blobs:
        if not blob:
            continue
        if isinstance(blob, list):
            parts = [str(x).strip() for x in blob]
        else:
            parts = re.split(r"[,;|]", str(blob))
        for p in parts:
            p = p.strip()
            if p and p.lower() not in {s.lower() for s in seen}:
                seen.append(p)
    return ",".join(seen)


def pick_richest_text(*vals: str) -> str:
    best = ""
    for v in vals:
        s = (v or "").strip()
        if len(s) > len(best):
            best = s
    return best


def merge_meta_dicts(items: list[dict]) -> dict:
    """Union/max-merge metadata dicts from DB rows and sidecars."""
    if not items:
        return {}
    out: dict = {}
    ratings = [int(i.get("rating") or 0) for i in items]
    thumbs = [int(i.get("thumbs") or 0) for i in items]
    out["rating"] = max(ratings) if ratings else 0
    out["thumbs"] = max(thumbs) if thumbs else 0
    out["tags"] = merge_tags(*[i.get("tags") or "" for i in items])
    out["prompt"] = pick_richest_text(*[i.get("prompt") or "" for i in items])
    out["negative_prompt"] = pick_richest_text(*[i.get("negative_prompt") or "" for i in items])
    out["context"] = pick_richest_text(*[i.get("context") or "" for i in items])
    # model/mode/seed: prefer non-empty from highest-rating item first
    ranked = sorted(items, key=lambda i: (int(i.get("rating") or 0), int(i.get("thumbs") or 0)), reverse=True)
    for key in ("model", "mode", "seed", "width", "height", "steps", "cfg", "parent_id", "created_at"):
        for i in ranked:
            if i.get(key) not in (None, ""):
                out[key] = i[key]
                break
    # alias names collected
    aliases = []
    for i in items:
        for k in ("filename", "alias", "name"):
            if i.get(k):
                aliases.append(str(i[k]))
    out["merged_aliases"] = sorted(set(aliases))
    return out


def keep_score(path: Path, db_meta: dict[str, dict]) -> tuple:
    """Higher is better keep candidate."""
    name = path.name
    name_l = name.lower()
    key = str(path.resolve()).lower()
    db = db_meta.get(key) or db_meta.get(name_l) or {}
    rating = int(db.get("rating") or 0)
    thumbs = int(db.get("thumbs") or 0)
    alias = 0

    if name in PREFERRED_IMMERSION_NAMES:
        alias += 100
    for hint in ALIAS_HINTS:
        if hint in name_l:
            alias += 3
    if is_immersion_name(name):
        alias += 10
    if not TS_PREFIX.match(name):
        alias += 2
    # gallery lives > output generic Comfy names
    try:
        resolved = path.resolve()
        if IMAGE_DIR.resolve() in resolved.parents or resolved.parent == IMAGE_DIR.resolve():
            alias += 8
        if OUTPUT_DIR.resolve() in resolved.parents or resolved.parent == OUTPUT_DIR.resolve():
            if OUTPUT_GENERIC.match(name):
                alias -= 15
            else:
                alias -= 3
    except OSError:
        pass
    # re-import spam
    if "2026-07-09_14" in name or "2026-07-09_15" in name or "2026-07-09_21" in name:
        alias -= 5
    if "juggernaut_standard_2026-" in name_l:
        alias -= 2
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (rating, thumbs, alias, -mtime, -len(str(path)))


def gather_group_meta(files: list[Path], db_meta: dict[str, dict]) -> list[dict]:
    items = []
    for p in files:
        key = str(p.resolve()).lower()
        db = db_meta.get(key) or db_meta.get(p.name.lower())
        if db:
            items.append(dict(db))
        # sidecar from db or conventional path
        sc_path = ""
        if db and db.get("sidecar_path"):
            sc_path = db["sidecar_path"]
        else:
            cand = SIDECAR_DIR / f"{p.stem}.json"
            if cand.exists():
                sc_path = str(cand)
        sc = load_sidecar(Path(sc_path)) if sc_path else {}
        if sc:
            sc = dict(sc)
            sc.setdefault("filename", p.name)
            items.append(sc)
        # adjacent .meta.json
        meta_json = p.with_suffix(p.suffix + ".meta.json")
        if not meta_json.exists():
            meta_json = Path(str(p) + ".meta.json")
        if not meta_json.exists():
            meta_json = p.parent / f"{p.stem}.meta.json"
        mj = load_sidecar(meta_json)
        if mj:
            mj = dict(mj)
            mj.setdefault("filename", p.name)
            # tags may be list
            if isinstance(mj.get("tags"), list):
                mj["tags"] = ",".join(str(t) for t in mj["tags"])
            items.append(mj)
        items.append({"filename": p.name, "filepath": str(p)})
    return items


def plan_duplicates(roots: list[Path], db_meta: dict[str, dict]) -> dict:
    by_hash: dict[str, list[Path]] = defaultdict(list)
    errors: list[str] = []
    for root in roots:
        for p in collect(root):
            # skip quarantine
            if "_dedup_quarantine" in p.parts:
                continue
            try:
                by_hash[sha256_file(p)].append(p)
            except OSError as e:
                errors.append(f"{p}: {e}")

    groups = []
    delete_list: list[dict] = []
    keep_list: list[dict] = []
    alias_preserve: list[dict] = []
    reclaim = 0

    for h, files in by_hash.items():
        if len(files) < 2:
            continue
        # de-dupe identical path strings
        uniq = []
        seen_p = set()
        for p in files:
            rp = str(p.resolve()).lower()
            if rp in seen_p:
                continue
            seen_p.add(rp)
            uniq.append(p)
        if len(uniq) < 2:
            continue

        ranked = sorted(uniq, key=lambda p: keep_score(p, db_meta), reverse=True)
        keep = ranked[0]
        # Prefer keep living in gallery if top score is output generic and an immersion alias exists
        gallery_imm = [
            p
            for p in ranked
            if p.parent.resolve() == IMAGE_DIR.resolve() and is_immersion_name(p.name)
        ]
        if gallery_imm and (
            keep.parent.resolve() != IMAGE_DIR.resolve() or OUTPUT_GENERIC.match(keep.name)
        ):
            keep = gallery_imm[0]

        dups = [p for p in ranked if p.resolve() != keep.resolve()]

        # Immersion aliases among dups: hardlink-preserve instead of delete
        preserve: list[Path] = []
        purge: list[Path] = []
        for p in dups:
            if p.parent.resolve() == IMAGE_DIR.resolve() and is_immersion_name(p.name):
                preserve.append(p)
            else:
                purge.append(p)

        # Always ensure preferred immersion names that appear in the group exist as aliases of keep
        group_names = {p.name for p in uniq}
        wanted_aliases = sorted(
            (PREFERRED_IMMERSION_NAMES & group_names)
            | {p.name for p in preserve}
            | ({keep.name} if is_immersion_name(keep.name) else set())
        )

        merged = merge_meta_dicts(gather_group_meta(uniq, db_meta))
        keep_sz = keep.stat().st_size
        # reclaim only purge targets (hardlinks don't free space until all gone)
        dup_bytes = sum(p.stat().st_size for p in purge)
        reclaim += dup_bytes

        g = {
            "sha256": h,
            "keep": str(keep),
            "keep_score": list(keep_score(keep, db_meta)[:4]),
            "duplicates": [str(p) for p in purge],
            "preserve_aliases": [str(p) for p in preserve],
            "wanted_alias_names": wanted_aliases,
            "merged_meta": {
                k: merged.get(k)
                for k in (
                    "rating",
                    "thumbs",
                    "tags",
                    "prompt",
                    "negative_prompt",
                    "context",
                    "model",
                    "mode",
                    "seed",
                    "merged_aliases",
                )
                if k in merged
            },
            "n": len(uniq),
            "reclaim_bytes": dup_bytes,
            "bytes_each": keep_sz,
        }
        groups.append(g)
        keep_list.append(
            {
                "path": str(keep),
                "sha256": h,
                "merged_meta": g["merged_meta"],
                "wanted_alias_names": wanted_aliases,
            }
        )
        for p in preserve:
            alias_preserve.append(
                {
                    "path": str(p),
                    "sha256": h,
                    "keep": str(keep),
                    "action": "hardlink_alias",
                }
            )
        for p in purge:
            key = str(p.resolve()).lower()
            db = db_meta.get(key) or db_meta.get(p.name.lower()) or {}
            sc = db.get("sidecar_path") or str(SIDECAR_DIR / f"{p.stem}.json")
            delete_list.append(
                {
                    "path": str(p),
                    "sha256": h,
                    "size": p.stat().st_size,
                    "db_id": db.get("id"),
                    "sidecar": sc,
                    "keep": str(keep),
                }
            )

    groups.sort(key=lambda g: g["reclaim_bytes"], reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roots": [str(r) for r in roots],
        "unique_hashes": len(by_hash),
        "total_images": sum(len(v) for v in by_hash.values()),
        "dup_groups": len(groups),
        "files_to_delete": len(delete_list),
        "aliases_to_preserve": len(alias_preserve),
        "reclaim_bytes": reclaim,
        "reclaim_mb": round(reclaim / 1024 / 1024, 1),
        "groups": groups,
        "delete": delete_list,
        "keep": keep_list,
        "alias_preserve": alias_preserve,
        "errors": errors,
    }


def same_file(a: Path, b: Path) -> bool:
    try:
        sa, sb = a.stat(), b.stat()
        return sa.st_ino == sb.st_ino and sa.st_dev == sb.st_dev
    except OSError:
        return False


def ensure_hardlink_alias(keep: Path, alias_path: Path) -> str:
    """Make alias_path a hardlink to keep (gallery immersion name). Returns status."""
    alias_path = Path(alias_path)
    keep = Path(keep)
    if not keep.exists():
        return "keep_missing"
    if alias_path.resolve() == keep.resolve():
        return "is_keep"
    if alias_path.exists() and same_file(alias_path, keep):
        return "already_linked"
    # If alias exists as separate bytes (shouldn't after plan) replace with hardlink
    tmp = None
    try:
        if alias_path.exists():
            # only replace if same content hash
            if sha256_file(alias_path) != sha256_file(keep):
                return "content_mismatch_skip"
            tmp = alias_path.with_name(alias_path.name + f".__dedup_tmp_{os.getpid()}")
            alias_path.replace(tmp)
        os.link(str(keep), str(alias_path))
        if tmp and tmp.exists():
            tmp.unlink()
        return "hardlinked"
    except OSError as e:
        # fallback: copy if hardlink fails (different volumes etc.)
        try:
            if tmp and tmp.exists() and not alias_path.exists():
                tmp.replace(alias_path)
                tmp = None
            if not alias_path.exists():
                shutil.copy2(str(keep), str(alias_path))
                return f"copied_fallback:{e}"
            return f"link_failed:{e}"
        except OSError as e2:
            return f"failed:{e2}"
    finally:
        if tmp and tmp.exists():
            try:
                if not alias_path.exists():
                    tmp.replace(alias_path)
                else:
                    tmp.unlink()
            except OSError:
                pass


def write_merged_sidecar(keep: Path, merged: dict, hard: bool) -> str | None:
    """Write/update sidecar for keep with merged metadata."""
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    sc_path = SIDECAR_DIR / f"{keep.stem}.json"
    existing = load_sidecar(sc_path)
    out = dict(existing)
    for k, v in merged.items():
        if k == "merged_aliases":
            continue
        if v in (None, ""):
            continue
        if k in ("rating", "thumbs"):
            out[k] = max(int(out.get(k) or 0), int(v or 0))
        elif k == "tags":
            out[k] = merge_tags(out.get("tags") or "", v)
        elif k in ("prompt", "negative_prompt", "context"):
            out[k] = pick_richest_text(out.get(k) or "", v)
        else:
            out.setdefault(k, v)
    out["filename"] = keep.name
    out["filepath"] = str(keep)
    out["merged_from_dedup"] = True
    out["merged_at"] = datetime.now(timezone.utc).isoformat()
    if merged.get("merged_aliases"):
        out["alias_names"] = merged["merged_aliases"]
    sc_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    # also update adjacent meta.json for canonical alice if present
    if "canonical" in keep.name.lower() or keep.name in PREFERRED_IMMERSION_NAMES:
        meta_path = IMAGE_DIR / f"{keep.stem}.meta.json"
        if meta_path.exists() or keep.name.startswith("2026-07-09_alice"):
            mj = load_sidecar(meta_path) if meta_path.exists() else {}
            mj = dict(mj) if mj else {}
            mj["image"] = str(keep)
            mj["source_image"] = str(keep)
            tags = merged.get("tags") or mj.get("tags") or ""
            if isinstance(tags, str):
                mj["tags"] = [t for t in tags.split(",") if t]
            mj["slug"] = mj.get("slug") or "alice" if "alice" in keep.name.lower() else mj.get("slug")
            meta_path.write_text(json.dumps(mj, indent=2), encoding="utf-8")
    return str(sc_path)


def upsert_db_keep(keep: Path, merged: dict, sidecar_path: str | None, alias_names: list[str]) -> dict:
    """Merge metadata into keep's DB row; ensure alias filename rows point at keep or are removed after hardlink."""
    stats = {"updated": 0, "inserted": 0, "deleted_alias_rows": 0, "rewritten": 0}
    if not DB_PATH.exists():
        return stats
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    try:
        # find any row matching keep path/name
        rows = list(
            con.execute(
                "SELECT * FROM images WHERE filename = ? OR filepath = ? OR filepath = ?",
                (keep.name, str(keep), str(keep).replace("\\", "/")),
            )
        )
        # also rows for alias names (same content groups)
        alias_rows = []
        for an in alias_names:
            if an == keep.name:
                continue
            alias_rows.extend(
                con.execute("SELECT * FROM images WHERE filename = ?", (an,)).fetchall()
            )

        # gather merge from alias rows too
        extra = [dict(r) for r in alias_rows]
        if extra:
            merged = merge_meta_dicts([merged] + extra)

        def apply_fields(row_id: int):
            con.execute(
                """
                UPDATE images SET
                  filepath = ?,
                  filename = ?,
                  sidecar_path = COALESCE(?, sidecar_path),
                  rating = MAX(COALESCE(rating,0), ?),
                  thumbs = MAX(COALESCE(thumbs,0), ?),
                  tags = ?,
                  prompt = CASE WHEN length(COALESCE(prompt,'')) >= length(?) THEN prompt ELSE ? END,
                  negative_prompt = CASE WHEN length(COALESCE(negative_prompt,'')) >= length(?) THEN negative_prompt ELSE ? END,
                  context = CASE WHEN length(COALESCE(context,'')) >= length(?) THEN context ELSE ? END,
                  model = COALESCE(NULLIF(model,''), ?),
                  mode = COALESCE(NULLIF(mode,''), ?)
                WHERE id = ?
                """,
                (
                    str(keep),
                    keep.name,
                    sidecar_path,
                    int(merged.get("rating") or 0),
                    int(merged.get("thumbs") or 0),
                    merged.get("tags") or "",
                    merged.get("prompt") or "",
                    merged.get("prompt") or "",
                    merged.get("negative_prompt") or "",
                    merged.get("negative_prompt") or "",
                    merged.get("context") or "",
                    merged.get("context") or "",
                    merged.get("model") or "",
                    merged.get("mode") or "standard",
                    row_id,
                ),
            )
            stats["updated"] += 1

        if rows:
            # keep first row, delete other keep-matching duplicates
            primary = rows[0]
            apply_fields(primary["id"])
            for r in rows[1:]:
                con.execute("DELETE FROM images WHERE id = ?", (r["id"],))
                stats["deleted_alias_rows"] += 1
        else:
            # insert minimal row if keep is in gallery
            if keep.parent.resolve() == IMAGE_DIR.resolve():
                try:
                    con.execute(
                        """
                        INSERT INTO images (
                          filename, filepath, sidecar_path, prompt, negative_prompt,
                          model, width, height, steps, cfg, seed, mode, tags, rating, thumbs, context
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            keep.name,
                            str(keep),
                            sidecar_path or "",
                            merged.get("prompt") or keep.name,
                            merged.get("negative_prompt") or "",
                            merged.get("model") or "unknown",
                            merged.get("width") or 0,
                            merged.get("height") or 0,
                            merged.get("steps") or 0,
                            merged.get("cfg") or 0,
                            int(merged.get("seed") or 0),
                            merged.get("mode") or "standard",
                            merged.get("tags") or "",
                            int(merged.get("rating") or 0),
                            int(merged.get("thumbs") or 0),
                            merged.get("context") or "",
                        ),
                    )
                    stats["inserted"] += 1
                except sqlite3.IntegrityError:
                    # race unique filename
                    r = con.execute("SELECT id FROM images WHERE filename = ?", (keep.name,)).fetchone()
                    if r:
                        apply_fields(r["id"])

        # For hardlinked aliases: rewrite their DB rows to same filepath OR drop extras and keep one row per alias name pointing to alias path (file exists as hardlink)
        for an in alias_names:
            if an == keep.name:
                continue
            alias_path = IMAGE_DIR / an
            existing = con.execute("SELECT id FROM images WHERE filename = ?", (an,)).fetchall()
            if alias_path.exists():
                # keep a DB row for the alias name so gallery UI still finds it, merged meta
                if existing:
                    eid = existing[0]["id"]
                    con.execute(
                        """
                        UPDATE images SET
                          filepath = ?,
                          sidecar_path = COALESCE(?, sidecar_path),
                          rating = MAX(COALESCE(rating,0), ?),
                          thumbs = MAX(COALESCE(thumbs,0), ?),
                          tags = ?,
                          prompt = CASE WHEN length(COALESCE(prompt,'')) >= length(?) THEN prompt ELSE ? END
                        WHERE id = ?
                        """,
                        (
                            str(alias_path),
                            sidecar_path,
                            int(merged.get("rating") or 0),
                            int(merged.get("thumbs") or 0),
                            merged.get("tags") or "",
                            merged.get("prompt") or "",
                            merged.get("prompt") or "",
                            eid,
                        ),
                    )
                    stats["rewritten"] += 1
                    for r in existing[1:]:
                        con.execute("DELETE FROM images WHERE id = ?", (r["id"],))
                        stats["deleted_alias_rows"] += 1
                else:
                    # optional: don't insert alias rows to avoid UNIQUE spam; hardlink file is enough for path refs
                    pass
            else:
                for r in existing:
                    con.execute("DELETE FROM images WHERE id = ?", (r["id"],))
                    stats["deleted_alias_rows"] += 1

        con.commit()
        try:
            con.execute("INSERT INTO images_fts(images_fts) VALUES('rebuild')")
            con.commit()
        except sqlite3.Error:
            pass
    finally:
        con.close()
    return stats


def cleanup_db_for_deleted(entries: list[dict], hard: bool) -> dict:
    removed_db = 0
    removed_sc = 0
    if not DB_PATH.exists():
        return {"db_rows": 0, "sidecars": 0}
    con = sqlite3.connect(str(DB_PATH))
    try:
        for e in entries:
            path = Path(e["path"])
            # Do not delete DB rows for immersion alias names that still exist
            if (IMAGE_DIR / path.name).exists() and is_immersion_name(path.name):
                continue
            cur = con.execute(
                "DELETE FROM images WHERE filepath = ? OR filepath = ? OR filename = ?",
                (str(path), str(path).replace("\\", "/"), path.name),
            )
            removed_db += cur.rowcount
            sc = Path(e.get("sidecar") or "")
            if sc.exists() and hard:
                try:
                    sc.unlink()
                    removed_sc += 1
                except OSError:
                    pass
        con.commit()
    finally:
        con.close()
    return {"db_rows": removed_db, "sidecars": removed_sc}


def ensure_stable_aliases() -> dict[str, str]:
    """Create short stable immersion aliases as hardlinks when sources exist."""
    results: dict[str, str] = {}
    for alias_name, sources in STABLE_ALIAS_TARGETS.items():
        alias_path = IMAGE_DIR / alias_name
        src = None
        for s in sources:
            cand = IMAGE_DIR / s
            if cand.exists():
                src = cand
                break
        if src is None:
            results[alias_name] = "no_source"
            continue
        results[alias_name] = ensure_hardlink_alias(src, alias_path)
    return results


def reconcile_db_fs(*, quarantine_orphan_sidecars: bool = False) -> dict:
    """
    Post-dedup consistency:
      - drop DB rows whose image file is missing (not immersion still-present)
      - ensure PREFERRED immersion files have a DB row (copy meta from sibling alias if needed)
      - rebuild FTS once
      - optional: move orphan sidecars (no matching image) into quarantine
    """
    stats = {
        "orphan_db_deleted": 0,
        "immersion_rows_inserted": 0,
        "immersion_rows_updated": 0,
        "orphan_sidecars_moved": 0,
        "stable_aliases": {},
        "fts_rebuilt": False,
        "wal_checkpoint": None,
    }
    stats["stable_aliases"] = ensure_stable_aliases()
    if not DB_PATH.exists():
        return stats

    # backup before reconcile
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = GALLERY_DIR / f"gallery.db.bak.reconcile_{stamp}"
    try:
        shutil.copy2(DB_PATH, bak)
        stats["db_backup"] = str(bak)
    except OSError as e:
        stats["db_backup_error"] = str(e)

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    try:
        rows = list(con.execute("SELECT id, filename, filepath, sidecar_path FROM images"))
        for r in rows:
            fn = r["filename"] or ""
            fp = Path(r["filepath"] or "")
            gallery_fp = IMAGE_DIR / fn
            exists = (fp.exists() if str(fp) else False) or gallery_fp.exists()
            if not exists:
                con.execute("DELETE FROM images WHERE id = ?", (r["id"],))
                stats["orphan_db_deleted"] += 1

        # Ensure preferred immersion names on disk have DB rows
        # Prefer cloning meta from any existing preferred sibling that shares inode/size
        preferred_on_disk = [n for n in sorted(PREFERRED_IMMERSION_NAMES) if (IMAGE_DIR / n).exists()]
        meta_by_ino: dict[tuple, sqlite3.Row] = {}
        for n in preferred_on_disk:
            p = IMAGE_DIR / n
            try:
                st = p.stat()
                key = (st.st_dev, st.st_ino)
            except OSError:
                continue
            row = con.execute("SELECT * FROM images WHERE filename = ?", (n,)).fetchone()
            if row:
                meta_by_ino.setdefault(key, row)

        for n in preferred_on_disk:
            p = IMAGE_DIR / n
            existing = con.execute("SELECT id FROM images WHERE filename = ?", (n,)).fetchone()
            sc = SIDECAR_DIR / f"{p.stem}.json"
            sc_path = str(sc) if sc.exists() else ""
            try:
                st = p.stat()
                key = (st.st_dev, st.st_ino)
            except OSError:
                continue
            donor = meta_by_ino.get(key)
            sc_data = load_sidecar(sc) if sc_path else {}
            if existing:
                con.execute(
                    """
                    UPDATE images SET filepath = ?, sidecar_path = COALESCE(NULLIF(?, ''), sidecar_path)
                    WHERE id = ?
                    """,
                    (str(p), sc_path, existing["id"]),
                )
                stats["immersion_rows_updated"] += 1
                continue
            # insert from donor or sidecar
            prompt = (donor["prompt"] if donor else None) or sc_data.get("prompt") or n
            neg = (donor["negative_prompt"] if donor else None) or sc_data.get("negative_prompt") or ""
            model = (donor["model"] if donor else None) or sc_data.get("model") or "unknown"
            tags = (donor["tags"] if donor else None) or sc_data.get("tags") or ""
            if isinstance(tags, list):
                tags = ",".join(str(t) for t in tags)
            try:
                con.execute(
                    """
                    INSERT INTO images (
                      filename, filepath, sidecar_path, prompt, negative_prompt,
                      model, width, height, steps, cfg, seed, mode, tags, rating, thumbs, context
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        n,
                        str(p),
                        sc_path,
                        prompt,
                        neg,
                        model,
                        (donor["width"] if donor else None) or sc_data.get("width") or 0,
                        (donor["height"] if donor else None) or sc_data.get("height") or 0,
                        (donor["steps"] if donor else None) or sc_data.get("steps") or 0,
                        (donor["cfg"] if donor else None) or sc_data.get("cfg") or 0,
                        int((donor["seed"] if donor else None) or sc_data.get("seed") or 0),
                        (donor["mode"] if donor else None) or sc_data.get("mode") or "standard",
                        tags,
                        int((donor["rating"] if donor else None) or sc_data.get("rating") or 0),
                        int((donor["thumbs"] if donor else None) or sc_data.get("thumbs") or 0),
                        (donor["context"] if donor else None) or sc_data.get("context") or "",
                    ),
                )
                stats["immersion_rows_inserted"] += 1
                row = con.execute("SELECT * FROM images WHERE filename = ?", (n,)).fetchone()
                if row:
                    meta_by_ino[key] = row
            except sqlite3.IntegrityError:
                pass

        con.commit()
        try:
            con.execute("INSERT INTO images_fts(images_fts) VALUES('rebuild')")
            con.commit()
            stats["fts_rebuilt"] = True
        except sqlite3.Error as e:
            stats["fts_error"] = str(e)

        try:
            ck = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            stats["wal_checkpoint"] = list(ck) if ck else None
        except sqlite3.Error as e:
            stats["wal_checkpoint_error"] = str(e)
    finally:
        con.close()

    if quarantine_orphan_sidecars and SIDECAR_DIR.is_dir():
        qdir = QUARANTINE_ROOT / f"orphan_sidecars_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        qdir.mkdir(parents=True, exist_ok=True)
        img_stems = {p.stem.lower() for p in IMAGE_DIR.iterdir() if p.is_file() and p.suffix.lower() in EXTS}
        # also accept alias stems that match preferred
        for sc in SIDECAR_DIR.glob("*.json"):
            if sc.stem.lower() in img_stems:
                continue
            # keep if any image references this sidecar in DB — already cleaned; move orphan
            try:
                dest = qdir / sc.name
                shutil.move(str(sc), str(dest))
                stats["orphan_sidecars_moved"] += 1
            except OSError:
                pass
        stats["orphan_sidecar_dir"] = str(qdir)
    return stats


def apply_plan(plan: dict, hard_delete: bool) -> dict:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    qdir = QUARANTINE_ROOT / ts
    moved = 0
    deleted = 0
    failed: list[str] = []
    applied = []
    link_stats: dict[str, int] = defaultdict(int)
    db_merge_stats = {"updated": 0, "inserted": 0, "deleted_alias_rows": 0, "rewritten": 0}
    sidecars_written = 0

    if not hard_delete:
        qdir.mkdir(parents=True, exist_ok=True)
        (qdir / "output").mkdir(exist_ok=True)
        (qdir / "gallery").mkdir(exist_ok=True)

    # 1) Establish keep + hardlink aliases + merge metadata FIRST (before quarantine)
    for k in plan["keep"]:
        keep = Path(k["path"])
        if not keep.exists():
            failed.append(f"keep_missing:{keep}")
            continue
        merged = k.get("merged_meta") or {}
        # If keep is in output but immersion aliases wanted in gallery, promote keep to primary alias in gallery
        wanted = list(k.get("wanted_alias_names") or [])
        if keep.parent.resolve() != IMAGE_DIR.resolve():
            # prefer a preferred immersion name as gallery anchor
            gallery_anchor = None
            for name in wanted:
                if name in PREFERRED_IMMERSION_NAMES:
                    gallery_anchor = IMAGE_DIR / name
                    break
            if gallery_anchor is None and wanted:
                gallery_anchor = IMAGE_DIR / wanted[0]
            if gallery_anchor is not None:
                if not gallery_anchor.exists():
                    try:
                        shutil.copy2(str(keep), str(gallery_anchor))
                        link_stats["promoted_to_gallery"] += 1
                    except OSError as e:
                        failed.append(f"promote:{gallery_anchor}:{e}")
                # hardlink remaining aliases to gallery anchor
                keep_for_aliases = gallery_anchor if gallery_anchor.exists() else keep
            else:
                keep_for_aliases = keep
        else:
            keep_for_aliases = keep

        for name in wanted:
            alias_path = IMAGE_DIR / name
            st = ensure_hardlink_alias(keep_for_aliases, alias_path)
            link_stats[st] += 1

        sc_path = None
        if keep_for_aliases.parent.resolve() == IMAGE_DIR.resolve() or any(
            (IMAGE_DIR / n).exists() for n in wanted
        ):
            anchor = keep_for_aliases if keep_for_aliases.parent.resolve() == IMAGE_DIR.resolve() else IMAGE_DIR / (
                wanted[0] if wanted else keep.name
            )
            if anchor.exists():
                sc_path = write_merged_sidecar(anchor, merged, hard=hard_delete)
                sidecars_written += 1
                st = upsert_db_keep(anchor, merged, sc_path, wanted)
                for kk, vv in st.items():
                    db_merge_stats[kk] = db_merge_stats.get(kk, 0) + vv

    # 2) Quarantine / delete purge targets (skip if path still needed as hardlink alias)
    for e in plan["delete"]:
        src = Path(e["path"])
        if not src.exists():
            # may already have been replaced by hardlink flow
            link_stats["already_gone"] += 1
            continue
        # if this name is immersion and lives in gallery, skip purge (hardlinked)
        if src.parent.resolve() == IMAGE_DIR.resolve() and is_immersion_name(src.name):
            # ensure it's linked to keep
            keep = Path(e["keep"])
            keep_anchor = keep
            if keep.parent.resolve() != IMAGE_DIR.resolve():
                # find any preferred surviving gallery file with same hash group
                for name in PREFERRED_IMMERSION_NAMES:
                    cand = IMAGE_DIR / name
                    if cand.exists() and cand.resolve() != src.resolve():
                        try:
                            if sha256_file(cand) == e["sha256"] or same_file(cand, src):
                                keep_anchor = cand
                                break
                        except OSError:
                            pass
            st = ensure_hardlink_alias(keep_anchor if keep_anchor.exists() else keep, src)
            link_stats[f"preserve_{st}"] += 1
            continue
        try:
            if hard_delete:
                src.unlink()
                deleted += 1
                action = "hard_delete"
            else:
                sub = "gallery" if "gallery" in str(src).lower() else "output"
                dest = qdir / sub / src.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    dest = qdir / sub / f"{src.stem}__{e['sha256'][:8]}{src.suffix}"
                shutil.move(str(src), str(dest))
                sc = Path(e.get("sidecar") or "")
                if sc.exists() and not is_immersion_name(src.name):
                    sc_dest = qdir / sub / sc.name
                    if not sc_dest.exists():
                        shutil.move(str(sc), str(sc_dest))
                moved += 1
                action = "quarantine"
                e["quarantine"] = str(dest)
            applied.append({**e, "action": action})
        except OSError as err:
            failed.append(f"{src}: {err}")

    db_del = cleanup_db_for_deleted(plan["delete"], hard=hard_delete)
    return {
        "moved": moved,
        "deleted": deleted,
        "failed": failed[:50],
        "failed_count": len(failed),
        "quarantine_dir": str(qdir) if not hard_delete else None,
        "db_cleanup": db_del,
        "db_merge": db_merge_stats,
        "hardlink_stats": dict(link_stats),
        "sidecars_written": sidecars_written,
        "applied_count": len(applied),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Purge byte-identical ComfyUI duplicate images")
    ap.add_argument(
        "--scope",
        choices=["gallery", "output", "both"],
        default="gallery",
        help="Where to scan (default: gallery — main waste)",
    )
    ap.add_argument("--apply", action="store_true", help="Execute purge (default dry-run)")
    ap.add_argument(
        "--hard-delete",
        action="store_true",
        help="With --apply: permanent delete instead of quarantine under gallery/_dedup_quarantine",
    )
    ap.add_argument("--top", type=int, default=12, help="Print top N groups")
    ap.add_argument(
        "--reconcile-only",
        action="store_true",
        help="Skip scan/purge; only reconcile DB↔FS, stable aliases, FTS rebuild",
    )
    ap.add_argument(
        "--quarantine-orphan-sidecars",
        action="store_true",
        help="With reconcile: move sidecars with no matching image into quarantine",
    )
    args = ap.parse_args()

    if args.reconcile_only:
        print("[comfy-dedup] reconcile-only mode")
        stats = reconcile_db_fs(quarantine_orphan_sidecars=args.quarantine_orphan_sidecars)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        outp = REPORT_DIR / f"comfy_dedup_reconcile_{stamp}.json"
        outp.write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")
        print(json.dumps(stats, indent=2, default=str))
        print(f"reconcile log: {outp}")
        return 0

    roots: list[Path] = []
    if args.scope in ("gallery", "both"):
        roots.append(IMAGE_DIR)
    if args.scope in ("output", "both"):
        roots.append(OUTPUT_DIR)

    print(f"[comfy-dedup] scope={args.scope} apply={args.apply} hard={args.hard_delete}")
    print(f"[comfy-dedup] immersion merge+hardlink aliases=ON")
    print(f"[comfy-dedup] roots={roots}")
    db_meta = load_db_rows()
    print(f"[comfy-dedup] db index entries={len(db_meta)}")

    plan = plan_duplicates(roots, db_meta)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"comfy_dedup_report_{stamp}.json"
    # trim merged prompts in report file size
    report_path.write_text(json.dumps(plan, indent=2, default=str), encoding="utf-8")

    print()
    print("=== SCOREBOARD ===")
    print(f"images scanned : {plan['total_images']}")
    print(f"unique hashes  : {plan['unique_hashes']}")
    print(f"dup groups     : {plan['dup_groups']}")
    print(f"files to drop  : {plan['files_to_delete']}")
    print(f"aliases keep   : {plan['aliases_to_preserve']}")
    print(f"reclaim        : {plan['reclaim_mb']} MB ({plan['reclaim_bytes']} bytes)")
    print(f"report         : {report_path}")
    print()
    print(f"=== TOP {args.top} GROUPS ===")
    for g in plan["groups"][: args.top]:
        print(
            f"  n={g['n']} reclaim={g['reclaim_bytes']/1024/1024:.1f}MB  "
            f"keep={Path(g['keep']).name}  aliases={len(g.get('preserve_aliases') or [])}"
        )
        for d in g["duplicates"][:3]:
            print(f"      DUP  {Path(d).name}")
        for a in (g.get("preserve_aliases") or [])[:3]:
            print(f"      ALIAS {Path(a).name}")
        if len(g["duplicates"]) > 3:
            print(f"      ... +{len(g['duplicates'])-3} more dups")

    if not args.apply:
        print()
        print("DRY-RUN only. Re-run with --apply to quarantine dups + merge/hardlink immersion names.")
        print("  --apply                  → quarantine + metadata merge + alias hardlinks")
        print("  --apply --hard-delete    → permanent delete + DB/sidecar cleanup")
        return 0

    if plan["files_to_delete"] == 0 and plan["aliases_to_preserve"] == 0:
        print("Nothing to purge.")
        return 0

    # backup DB before apply
    if DB_PATH.exists():
        bak = GALLERY_DIR / f"gallery.db.bak.dedup_{stamp}"
        shutil.copy2(DB_PATH, bak)
        print(f"[comfy-dedup] DB backup → {bak}")

    result = apply_plan(plan, hard_delete=args.hard_delete)
    # Always reconcile after apply (catches orphan DB rows, stable short aliases, FTS once)
    recon = reconcile_db_fs(quarantine_orphan_sidecars=args.quarantine_orphan_sidecars)
    result["reconcile"] = recon
    result_path = REPORT_DIR / f"comfy_dedup_apply_{stamp}.json"
    result_path.write_text(
        json.dumps({"plan_report": str(report_path), **result}, indent=2, default=str),
        encoding="utf-8",
    )
    print()
    print("=== APPLY RESULT ===")
    print(json.dumps(result, indent=2, default=str))
    print(f"apply log: {result_path}")

    # verify immersion aliases exist
    print()
    print("=== IMMERSION ALIAS CHECK ===")
    missing = []
    for name in sorted(PREFERRED_IMMERSION_NAMES):
        p = IMAGE_DIR / name
        st = "OK" if p.exists() else "MISSING"
        if not p.exists():
            # only report missing if it was in the pre-plan universe — check report keep wanted lists
            wanted_any = any(name in (k.get("wanted_alias_names") or []) for k in plan["keep"])
            if wanted_any or name in STABLE_ALIAS_TARGETS:
                missing.append(name)
                print(f"  {st}  {name}")
            else:
                print(f"  skip {name} (not in dup groups)")
        else:
            try:
                nlink = p.stat().st_nlink
            except OSError:
                nlink = "?"
            print(f"  {st}  nlink={nlink}  {name}")
    if missing:
        print(f"WARNING missing aliases: {missing}")
        return 1
    return 0 if result.get("failed_count", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
