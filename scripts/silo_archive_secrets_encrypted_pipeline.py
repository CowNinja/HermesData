#!/usr/bin/env python3
"""Multi-format archive eval + encrypted asset staging.

Formats: zip, tar, tar.gz, tgz, tar.bz2, tar.xz, gz (single), 7z/rar if tools present.
Encrypted zips/PDFs: detect → stage → never crack; try Jeff password list only.

Secrets: path quarantine list only — no secret values to stdout/chat.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(r"D:\HermesData\state")
OUT_EVAL = STATE / "archive_eval_latest.json"
ENC_STAGE = STATE / "encrypted_assets_queue.json"
SECRETS = STATE / "secrets_quarantine_candidates.json"
HARVEST = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\_Inbox\from-g-drive\_archive_harvest"
)
# Jeff can drop one password per line (never commit). Optional.
PW_FILE = Path(r"D:\HermesData\config\archive_passwords.local.txt")

ARCHIVE_EXT = {
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
}
# compound handled via name
SKIP_NAME = re.compile(
    r"(virtualbox|\.vmdk|\.vdi|vhdx|qcow|game|steam|gog|music\s*lib|\.iso)",
    re.I,
)
GOLD_NAME = re.compile(
    r"(medical|navy|nmcp|records|orders|eval|legal|bcnr|nvlsp|export|takeout|"
    r"mail|dna|genome|journal|bloom|personal|tax|scan|backup.?doc)",
    re.I,
)
TEXTISH = re.compile(
    r"\.(txt|md|pdf|json|csv|docx?|xlsx?|html?|xml|log|ini|cfg|env|ya?ml)$",
    re.I,
)
SECRETISH = re.compile(
    r"(password|passwd|secret|credential|api[_-]?key|token|private.?key|id_rsa|\.pem)",
    re.I,
)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_passwords() -> list[str]:
    if not PW_FILE.is_file():
        return []
    try:
        lines = PW_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
        return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    except Exception:
        return []


def is_archive(path: Path) -> bool:
    n = path.name.lower()
    if path.suffix.lower() in ARCHIVE_EXT:
        return True
    if n.endswith((".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst")):
        return True
    return False


def list_zip(path: Path, max_n: int = 400) -> tuple[list[str], str | None]:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            # encryption flag
            encrypted = any(i.flag_bits & 0x1 for i in zf.infolist()[:50])
            names = [i.filename for i in zf.infolist()[:max_n]]
            return names, ("encrypted" if encrypted else None)
    except RuntimeError as e:
        if "encrypted" in str(e).lower() or "password" in str(e).lower():
            return [], "encrypted"
        return [], str(e)[:100]
    except Exception as e:
        msg = str(e).lower()
        if "password" in msg or "encrypted" in msg or "bad password" in msg:
            return [], "encrypted"
        return [], str(e)[:100]


def list_tar(path: Path, max_n: int = 400) -> tuple[list[str], str | None]:
    try:
        with tarfile.open(path, "r:*") as tf:
            names = []
            for i, m in enumerate(tf.getmembers()):
                if i >= max_n:
                    break
                names.append(m.name)
            return names, None
    except Exception as e:
        return [], str(e)[:100]


def classify(path: Path) -> dict:
    try:
        size = path.stat().st_size
    except OSError:
        return {"path": str(path), "decision": "skip", "reason": "unreadable"}

    low = str(path).lower()
    name = path.name.lower()
    if SKIP_NAME.search(name) or SKIP_NAME.search(low):
        return {
            "path": str(path),
            "size": size,
            "decision": "skip_bulk",
            "reason": "vm_game_media_name",
            "format": path.suffix.lower(),
        }

    score = 0
    if GOLD_NAME.search(name) or GOLD_NAME.search(low):
        score += 50
    if size < 20_000_000:
        score += 20
    elif size < 100_000_000:
        score += 5
    else:
        score -= 10

    names: list[str] = []
    enc = None
    fmt = path.suffix.lower()
    if name.endswith((".tar.gz", ".tgz")):
        fmt = "tar.gz"
        names, enc = list_tar(path)
    elif name.endswith((".tar.bz2", ".tar.xz", ".tar")) or fmt == ".tar":
        fmt = "tar"
        names, enc = list_tar(path)
    elif fmt == ".zip":
        names, enc = list_zip(path)
    elif fmt == ".gz" and not name.endswith((".tar.gz", ".tgz")):
        fmt = "gzip_single"
        # single-file gzip — treat as land if small/gold
        if size < 50_000_000 or score >= 45:
            return {
                "path": str(path),
                "size": size,
                "decision": "land_or_harvest",
                "format": fmt,
                "score": score + 15,
            }
        return {
            "path": str(path),
            "size": size,
            "decision": "skip_or_catalog",
            "format": fmt,
            "score": score,
        }
    elif fmt in {".7z", ".rar"}:
        # no library — stage for external tool / Jeff
        if size > 150_000_000 and score < 50:
            return {
                "path": str(path),
                "size": size,
                "decision": "skip_bulk",
                "format": fmt,
                "reason": "large_7z_rar_no_gold_no_lister",
            }
        return {
            "path": str(path),
            "size": size,
            "decision": "needs_tool_or_jeff",
            "format": fmt,
            "score": score,
            "reason": "install_7zip_or_unrar_for_list",
        }
    else:
        return {
            "path": str(path),
            "size": size,
            "decision": "skip_or_catalog",
            "format": fmt,
            "score": score,
        }

    if enc == "encrypted":
        return {
            "path": str(path),
            "size": size,
            "decision": "encrypted_stage",
            "format": fmt,
            "score": score,
            "encrypted": True,
        }

    text_members = sum(1 for n in names if TEXTISH.search(n))
    secret_members = sum(1 for n in names if SECRETISH.search(n))
    score += min(40, text_members * 2)
    score += min(15, secret_members * 3)

    if text_members >= 3 or score >= 45:
        decision = "land_or_harvest"
    elif text_members >= 1 or score >= 25:
        decision = "harvest_listing_and_small_text"
    elif size > 500_000_000 and score < 50:
        decision = "skip_bulk"
    else:
        decision = "skip_or_catalog"

    return {
        "path": str(path),
        "size": size,
        "decision": decision,
        "format": fmt,
        "score": score,
        "text_members": text_members,
        "secret_members": secret_members,
        "listing_sample": names[:30],
        "encrypted": False,
    }


def try_decrypt_zip(path: Path, passwords: list[str]) -> dict:
    """Try known passwords only — never brute force."""
    if not passwords:
        return {"ok": False, "reason": "no_password_file"}
    for pw in passwords:
        try:
            with zipfile.ZipFile(path, "r") as zf:
                zf.setpassword(pw.encode("utf-8", errors="ignore"))
                # try reading first file
                for info in zf.infolist()[:3]:
                    if info.is_dir():
                        continue
                    zf.read(info.filename)
                    return {"ok": True, "method": "zip_password", "hint": "password_file_hit"}
        except Exception:
            continue
    return {"ok": False, "reason": "passwords_exhausted"}


def try_decrypt_pdf(path: Path, passwords: list[str]) -> dict:
    try:
        from pypdf import PdfReader
    except Exception:
        return {"ok": False, "reason": "no_pypdf"}
    try:
        r = PdfReader(str(path))
        if not r.is_encrypted:
            return {"ok": True, "method": "not_encrypted"}
        for pw in passwords:
            try:
                if r.decrypt(pw) != 0:
                    return {"ok": True, "method": "pdf_password", "hint": "password_file_hit"}
            except Exception:
                continue
        return {"ok": False, "reason": "pdf_passwords_exhausted", "needs_jeff": True}
    except Exception as e:
        return {"ok": False, "reason": str(e)[:100]}


def stage_encrypted(item: dict, queue: list) -> None:
    path = item.get("path")
    if not path:
        return
    if any(x.get("path") == path for x in queue):
        return
    queue.append(
        {
            "path": path,
            "kind": item.get("format") or item.get("kind") or "unknown",
            "size": item.get("size"),
            "status": "needs_password_or_tool",
            "staged_at": utc(),
            "ask_jeff": True,
            "notes": "Do not crack. Try archive_passwords.local.txt or ask Jeff.",
        }
    )


def harvest_zip_text(path: Path, limit_files: int = 25) -> int:
    n = 0
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir() or not TEXTISH.search(info.filename):
                    continue
                if info.file_size > 5_000_000:
                    continue
                if SECRETISH.search(info.filename):
                    continue
                target = HARVEST / path.stem / Path(info.filename).name
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    continue
                with zf.open(info) as src, target.open("wb") as dst:
                    dst.write(src.read())
                n += 1
                if n >= limit_files:
                    break
    except Exception:
        return n
    return n


def harvest_tar_text(path: Path, limit_files: int = 25) -> int:
    n = 0
    try:
        with tarfile.open(path, "r:*") as tf:
            for m in tf.getmembers():
                if not m.isfile() or not TEXTISH.search(m.name):
                    continue
                if m.size > 5_000_000:
                    continue
                if SECRETISH.search(m.name):
                    continue
                target = HARVEST / path.stem / Path(m.name).name
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    continue
                f = tf.extractfile(m)
                if not f:
                    continue
                target.write_bytes(f.read())
                n += 1
                if n >= limit_files:
                    break
    except Exception:
        return n
    return n


def scan_pdf_encrypted(roots: list[Path], limit: int = 40) -> list[dict]:
    out = []
    try:
        from pypdf import PdfReader
    except Exception:
        return out
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for p in root.rglob("*.pdf"):
                if not p.is_file():
                    continue
                try:
                    if p.stat().st_size > 80_000_000:
                        continue
                    r = PdfReader(str(p))
                    if r.is_encrypted:
                        out.append(
                            {
                                "path": str(p),
                                "kind": "pdf",
                                "format": "pdf",
                                "size": p.stat().st_size,
                                "decision": "encrypted_stage",
                                "encrypted": True,
                            }
                        )
                except Exception:
                    continue
                if len(out) >= limit:
                    return out
        except OSError:
            continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=35)
    ap.add_argument("--harvest", action="store_true")
    ap.add_argument("--try-passwords", action="store_true")
    ap.add_argument("--root", action="append", default=[])
    args = ap.parse_args()
    roots = [Path(r) for r in args.root] or [
        Path(r"G:\Downloads"),
        Path(r"G:\MemoryCard_Backups"),
        Path(r"G:\SEC501_Restore"),
        Path(r"D:\Documents"),
        Path(r"D:\Downloads"),
    ]
    passwords = load_passwords() if args.try_passwords else []

    archives: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for p in root.rglob("*"):
                if p.is_file() and is_archive(p):
                    archives.append(p)
                if len(archives) >= args.limit * 4:
                    break
        except OSError:
            continue

    def sort_key(p: Path):
        try:
            sz = p.stat().st_size
        except OSError:
            sz = 1 << 60
        gold = 0 if GOLD_NAME.search(p.name) else 1
        return (gold, sz)

    archives.sort(key=sort_key)
    results = []
    enc_queue = []
    if ENC_STAGE.is_file():
        try:
            enc_queue = json.loads(ENC_STAGE.read_text(encoding="utf-8")).get("items") or []
        except Exception:
            enc_queue = []

    harvested = 0
    unlocked = 0
    for p in archives[: args.limit]:
        r = classify(p)
        if r.get("decision") == "encrypted_stage":
            if passwords:
                tr = try_decrypt_zip(p, passwords)
                r["unlock_attempt"] = {k: v for k, v in tr.items() if k != "password"}
                if tr.get("ok"):
                    r["decision"] = "land_or_harvest"
                    unlocked += 1
                else:
                    stage_encrypted(r, enc_queue)
            else:
                stage_encrypted(r, enc_queue)
        if args.harvest and r.get("decision") in {
            "land_or_harvest",
            "harvest_listing_and_small_text",
        }:
            fmt = r.get("format") or ""
            if fmt == "zip":
                harvested += harvest_zip_text(p)
            elif fmt in {"tar", "tar.gz"}:
                harvested += harvest_tar_text(p)
        results.append(r)

    # PDF encrypted sample
    for r in scan_pdf_encrypted(roots, limit=20):
        if passwords:
            tr = try_decrypt_pdf(Path(r["path"]), passwords)
            r["unlock_attempt"] = tr
            if tr.get("ok") and tr.get("method") != "not_encrypted":
                unlocked += 1
                r["decision"] = "unlocked_pdf"
            else:
                stage_encrypted(r, enc_queue)
        else:
            stage_encrypted(r, enc_queue)
        results.append(r)

    by: dict[str, int] = {}
    for r in results:
        d = r.get("decision") or "?"
        by[d] = by.get(d, 0) + 1

    summary = {
        "at": utc(),
        "scanned": len(results),
        "by_decision": by,
        "harvested_files": harvested,
        "unlocked_with_local_passwords": unlocked,
        "password_file_present": PW_FILE.is_file(),
        "password_count_loaded": len(passwords) if args.try_passwords else 0,
        "encrypted_queued": len(enc_queue),
        "formats_supported_list": [
            "zip",
            "tar",
            "tar.gz",
            "tgz",
            "tar.bz2",
            "tar.xz",
            "gz",
            "pdf_encrypted_detect",
            "7z/rar_stage_needs_tool",
        ],
        "results": results[:80],
    }
    OUT_EVAL.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    ENC_STAGE.write_text(
        json.dumps(
            {
                "updated": utc(),
                "policy": "no_bruteforce_ask_jeff_or_local_password_file",
                "password_file": str(PW_FILE),
                "count": len(enc_queue),
                "items": enc_queue[-500:],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "scanned": summary["scanned"],
                "by_decision": by,
                "harvested_files": harvested,
                "encrypted_queued": len(enc_queue),
                "unlocked": unlocked,
                "eval": str(OUT_EVAL),
                "enc_queue": str(ENC_STAGE),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
