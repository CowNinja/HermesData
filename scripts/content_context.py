#!/usr/bin/env python3
"""Content sample + directory/sibling context for relevance evaluation.

Google .gdoc/.gsheet stubs are NOT full documents locally — only JSON pointers.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

GOOGLE_STUBS = {".gdoc", ".gsheet", ".gslides", ".gmap", ".gscript", ".gform"}
IDENTITY_PATH = Path(r"D:\HermesData\config\google_account_identity.json")

def load_google_identity() -> dict:
    try:
        return json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"accounts": []}

def normalize_gmail_local(email: str) -> tuple[str, str]:
    """Return (normalized_local, domain). Gmail dots and +tags ignored in local."""
    email_l = email.strip().lower()
    if "@" not in email_l:
        local, domain = email_l, ""
    else:
        local, domain = email_l.split("@", 1)
    # plus addressing
    if "+" in local:
        local = local.split("+", 1)[0]
    # Gmail/googlemail: dots optional
    if domain in {"gmail.com", "googlemail.com", ""}:
        local_norm = local.replace(".", "")
    else:
        local_norm = local
    return local_norm, domain


def map_email_to_account(email: str | None) -> dict:
    if not email:
        return {"account_id": None, "role": None, "mine": None}
    email_l = email.strip().lower()
    local_norm, domain = normalize_gmail_local(email_l)
    ident = load_google_identity()
    for a in ident.get("accounts") or []:
        # explicit list
        for e in a.get("emails") or []:
            el, ed = normalize_gmail_local(e)
            if el == local_norm and (not domain or not ed or domain == ed or domain in {"gmail.com", "googlemail.com"}):
                return {
                    "account_id": a.get("id"),
                    "role": a.get("role"),
                    "mine": True,
                    "status": a.get("status"),
                    "matched_as": email_l,
                    "normalized_local": local_norm,
                }
        # local_normalized field
        ln = (a.get("local_normalized") or "").replace(".", "").lower()
        if ln and ln == local_norm:
            return {
                "account_id": a.get("id"),
                "role": a.get("role"),
                "mine": True,
                "status": a.get("status"),
                "matched_as": email_l,
                "normalized_local": local_norm,
            }
        # id with dots stripped
        aid = (a.get("id") or "").replace(".", "").lower()
        if aid and aid == local_norm:
            return {
                "account_id": a.get("id"),
                "role": a.get("role"),
                "mine": True,
                "status": a.get("status"),
                "matched_as": email_l,
                "normalized_local": local_norm,
            }
    return {
        "account_id": None,
        "role": "foreign_or_unknown",
        "mine": False,
        "email": email_l,
        "normalized_local": local_norm,
    }



def is_google_stub(path: Path) -> bool:
    return path.suffix.lower() in GOOGLE_STUBS


def read_google_stub(path: Path) -> dict:
    """Local .gdoc is ~300B pseudo-JSON with doc_id/url — no body text.

    Files often contain // comments so strict json.loads fails — use regex.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    def grab(key: str) -> str | None:
        m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', raw)
        return m.group(1) if m else None
    doc_id = grab("doc_id") or grab("id")
    email = grab("email")
    acct = map_email_to_account(email)
    return {
        "stub": True,
        "doc_id": doc_id,
        "url": grab("url"),
        "email": email,
        "google_account_id": acct.get("account_id"),
        "google_account_role": acct.get("role"),
        "google_account_mine": acct.get("mine"),
        "text": "",  # no body
        "note": "local_google_stub_no_body_needs_export",
        "raw_bytes": path.stat().st_size,
    }


def sample_text_content(path: Path, max_chars: int = 2500) -> dict:
    """Best-effort content sample for evaluation (not full train extract)."""
    p = Path(path)
    if not p.is_file():
        return {"text": "", "error": "not_a_file"}
    if is_google_stub(p):
        return read_google_stub(p)

    ext = p.suffix.lower()
    try:
        if ext in {".txt", ".md", ".csv", ".log", ".json", ".yaml", ".yml", ".py", ".html", ".xml"}:
            raw = p.read_bytes()[: max_chars * 4]
            for enc in ("utf-8", "cp1252", "latin-1"):
                try:
                    t = raw.decode(enc)
                    return {"text": t[:max_chars], "encoding": enc, "stub": False}
                except Exception:
                    continue
            return {"text": raw.decode("utf-8", errors="replace")[:max_chars], "stub": False}

        if ext == ".pdf":
            try:
                from pypdf import PdfReader

                r = PdfReader(str(p))
                parts = []
                for page in r.pages[:3]:
                    parts.append(page.extract_text() or "")
                t = "\n".join(parts)[:max_chars]
                return {
                    "text": t,
                    "stub": False,
                    "pdf_pages_sampled": min(3, len(r.pages)),
                    "needs_ocr": len(re.sub(r"\s+", "", t)) < 40,
                }
            except Exception as e:
                return {"text": "", "error": f"pdf:{e}", "stub": False}

        # binary office: filename+context only for cheap pass
        if ext in {".docx", ".xlsx", ".pptx"}:
            return {
                "text": "",
                "stub": False,
                "note": "office_binary_use_name_context_or_full_extract_later",
            }

        # images/audio: no text body here
        if ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".mp3", ".wav", ".m4a"}:
            return {"text": "", "stub": False, "note": f"modality_{ext}_needs_ocr_or_asr"}

        # generic small text attempt
        if p.stat().st_size < 200_000:
            raw = p.read_bytes()[:max_chars]
            if b"\x00" not in raw[:1000]:
                return {
                    "text": raw.decode("utf-8", errors="replace")[:max_chars],
                    "stub": False,
                }
        return {"text": "", "stub": False, "note": "no_text_sample"}
    except Exception as e:
        return {"text": "", "error": str(e), "stub": False}


def directory_context(path: Path, sibling_limit: int = 12) -> dict:
    """Parent path segments + sibling filenames for context-aware scoring."""
    p = Path(path)
    parent = p.parent
    parts = [x for x in parent.parts if x not in {"/", "\\"} and not re.match(r"^[A-Za-z]:\\?$", x)]
    # last 4 folder names matter most
    folder_signal = parts[-4:] if parts else []
    siblings: list[str] = []
    try:
        for c in sorted(parent.iterdir(), key=lambda x: x.name.lower())[: sibling_limit + 5]:
            if c.name == p.name:
                continue
            siblings.append(c.name)
            if len(siblings) >= sibling_limit:
                break
    except Exception:
        pass
    blob = " / ".join(folder_signal) + " || " + " | ".join(siblings[:sibling_limit])
    return {
        "folders": folder_signal,
        "siblings": siblings,
        "context_blob": blob[:2000],
    }


def gold_keywords_in_text(text: str) -> list[str]:
    if not text:
        return []
    pats = [
        (r"(?i)\bmedical|dental|diagnosis|physician|clinic\b", "medical"),
        (r"(?i)\bnavy|navadmin|military|orders|eval\b", "navy"),
        (r"(?i)\btax|income|expense|bank|invoice|receipt\b", "finance"),
        (r"(?i)\bfamily|wedding|spouse|children\b", "family"),
        (r"(?i)\bresume|curriculum vitae|employment\b", "career"),
        (r"(?i)\bsermon|bible|prayer|spiritual\b", "spiritual"),
        (r"(?i)\bpassword|api[_-]?key|secret\b", "secrets_caution"),
    ]
    hits = []
    for pat, lab in pats:
        if re.search(pat, text):
            hits.append(lab)
    return hits


def evaluate_bundle(path: str | Path, max_chars: int = 2500) -> dict:
    p = Path(path)
    content = sample_text_content(p, max_chars=max_chars)
    ctx = directory_context(p)
    text = content.get("text") or ""
    content_hits = gold_keywords_in_text(text)
    ctx_hits = gold_keywords_in_text(ctx.get("context_blob") or "")
    return {
        "path": str(p),
        "content": content,
        "context": ctx,
        "content_keyword_hits": content_hits,
        "context_keyword_hits": ctx_hits,
        "is_google_stub": is_google_stub(p),
        "google_account_id": content.get("google_account_id"),
        "google_account_role": content.get("google_account_role"),
        "google_account_mine": content.get("google_account_mine"),
    }


if __name__ == "__main__":
    import sys

    for a in sys.argv[1:]:
        print(json.dumps(evaluate_bundle(a), indent=2, ensure_ascii=False)[:3000])
