#!/usr/bin/env python3
"""Encrypted asset unlock assist — YOUR files, YOUR password candidates only.

What this does (legitimate personal recovery):
  1) Detect encrypted zip/PDF
  2) Try passwords from:
       - config/archive_passwords.local.txt
       - config/password_candidates.local.txt (mined/curated, still local)
       - optional --from-bw-note-ids (paths only logged)
  3) PDF "permissions only" / empty-user-password cases via pypdf
  4) Stage failures for Jeff (email dig / remember)

What this does NOT do:
  - Brute-force AES / long random passwords
  - Hashcat/John attacks by default
  - Print passwords to stdout/chat
  - Crack others' files

Research: pypdf/pikepdf known-password decrypt; PDF user vs owner password;
Bitwarden as password store; dictionary-attack only with owner wordlists.
"""
from __future__ import annotations

import argparse
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(r"D:\HermesData\state")
ENC_Q = STATE / "encrypted_assets_queue.json"
UNLOCK_LOG = STATE / "encrypted_unlock_results.jsonl"
PW_PRIMARY = Path(r"D:\HermesData\config\archive_passwords.local.txt")
PW_CANDIDATES = Path(r"D:\HermesData\config\password_candidates.local.txt")
OUT_DIR = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\_Inbox\from-g-drive\_unlocked"
)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_pw_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    out = []
    for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    # de-dupe preserve order
    seen = set()
    uniq = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def all_passwords(extra: list[str] | None = None) -> list[str]:
    pw = load_pw_file(PW_PRIMARY) + load_pw_file(PW_CANDIDATES)
    if extra:
        pw = extra + pw
    # Always try empty / common "open but restricted" cases for PDFs handled separately
    seen = set()
    out = []
    for p in pw:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def try_zip(path: Path, passwords: list[str]) -> dict:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            encrypted = any(i.flag_bits & 0x1 for i in zf.infolist()[:20])
            if not encrypted:
                return {"ok": True, "method": "not_encrypted"}
            for pw in passwords:
                try:
                    zf.setpassword(pw.encode("utf-8", errors="ignore"))
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        zf.read(info.filename)
                        return {
                            "ok": True,
                            "method": "zip_dictionary",
                            "password_source": "local_list",
                        }
                except Exception:
                    continue
            return {"ok": False, "method": "zip", "reason": "dictionary_exhausted"}
    except Exception as e:
        return {"ok": False, "method": "zip", "reason": str(e)[:120]}


def try_pdf(path: Path, passwords: list[str]) -> dict:
    try:
        from pypdf import PdfReader, PdfWriter
    except Exception:
        return {"ok": False, "reason": "no_pypdf"}
    try:
        reader = PdfReader(str(path))
        if not reader.is_encrypted:
            return {"ok": True, "method": "not_encrypted"}
        # empty password sometimes works for permission-only PDFs
        attempts = [""] + passwords
        for pw in attempts:
            try:
                code = reader.decrypt(pw)
                if code != 0:
                    # write unlocked copy (strip encryption for silo OCR)
                    OUT_DIR.mkdir(parents=True, exist_ok=True)
                    dest = OUT_DIR / (path.stem + "_unlocked.pdf")
                    if not dest.exists():
                        w = PdfWriter()
                        for page in reader.pages:
                            w.add_page(page)
                        with dest.open("wb") as f:
                            w.write(f)
                        meta = {
                            "source": str(path),
                            "unlocked_at": utc(),
                            "method": "empty" if pw == "" else "pdf_dictionary",
                        }
                        dest.with_suffix(".pdf.meta.json").write_text(
                            json.dumps(meta, indent=2), encoding="utf-8"
                        )
                    return {
                        "ok": True,
                        "method": "empty_or_dictionary",
                        "dest": str(dest),
                        "used_empty": pw == "",
                    }
            except Exception:
                continue
        return {"ok": False, "method": "pdf", "reason": "dictionary_exhausted"}
    except Exception as e:
        return {"ok": False, "method": "pdf", "reason": str(e)[:120]}


def log_result(path: str, result: dict) -> None:
    # never log password values
    safe = {k: v for k, v in result.items() if k not in {"password", "pw"}}
    rec = {"at": utc(), "path": path, **safe}
    with UNLOCK_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument(
        "--mine-note",
        action="store_true",
        help="Print instructions for mining candidates (no secrets printed)",
    )
    args = ap.parse_args()
    if args.mine_note:
        print(
            json.dumps(
                {
                    "how_to_grow_dictionary": [
                        "Add remembered passwords to archive_passwords.local.txt",
                        "Export Bitwarden passwords YOU own → review → paste likely old ones into password_candidates.local.txt",
                        "Search email/silo for 'password is' near bank/NMCP/VA filenames (manual or later miner)",
                        "SSN-last4 / DOB patterns only if YOU used them historically — add yourself, we won't invent",
                    ],
                    "not_supported": [
                        "GPU brute force of strong random passwords",
                        "Online cracking services for unknown owners",
                    ],
                },
                indent=2,
            )
        )
        return 0

    passwords = all_passwords()
    items = []
    if ENC_Q.is_file():
        try:
            items = json.loads(ENC_Q.read_text(encoding="utf-8")).get("items") or []
        except Exception:
            items = []

    results = []
    unlocked = 0
    for it in items[: args.limit]:
        path = Path(it.get("path") or "")
        if not path.is_file():
            continue
        kind = (it.get("kind") or it.get("format") or path.suffix.lower()).lower()
        if kind in {"zip", ".zip"} or path.suffix.lower() == ".zip":
            r = try_zip(path, passwords)
        elif kind in {"pdf", ".pdf"} or path.suffix.lower() == ".pdf":
            r = try_pdf(path, passwords)
        else:
            r = {"ok": False, "reason": f"unsupported_kind_{kind}"}
        log_result(str(path), r)
        if r.get("ok") and r.get("method") != "not_encrypted":
            unlocked += 1
            it["status"] = "unlocked"
            it["unlocked_at"] = utc()
        elif not r.get("ok"):
            it["status"] = "needs_jeff_or_better_dictionary"
            it["last_attempt"] = utc()
        results.append({"path": str(path), "ok": r.get("ok"), "method": r.get("method")})

    if ENC_Q.is_file():
        ENC_Q.write_text(
            json.dumps(
                {
                    "updated": utc(),
                    "policy": "dictionary_only_no_bruteforce",
                    "password_files": [str(PW_PRIMARY), str(PW_CANDIDATES)],
                    "count": len(items),
                    "items": items,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "passwords_loaded": len(passwords),
                "attempted": len(results),
                "unlocked_this_run": unlocked,
                "still_locked_sample": [r["path"] for r in results if not r.get("ok")][:10],
                "log": str(UNLOCK_LOG),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
