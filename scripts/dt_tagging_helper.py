"""
DT Tagging Helper (Session 7+)

Core tagging logic for the Personal Data Silo.
Designed for maximum flexibility:
- Multi-domain support (lists)
- Easy to extend with new domains/rules
- Placeholders for knowledge graph, PII handling, versioning
- Future-proof for content-based tagging

Usage:
    from dt_tagging_helper import enhance_with_dt_tags
    res = simple_classify(path)   # or your own classifier
    enhanced = enhance_with_dt_tags(res)
"""

from pathlib import Path
import hashlib

# Data-driven rules for easy extension (no code changes needed for new domains)
DOMAIN_RULES = {
    # Unified Navy + Military domain (merged per Session 8/9 direction)
    "Navy_Service_History": ["navy", "military", "usn", "ps r", "reenlist", "naval", "norfolk", "dd11", "dd28", "dd1172", "dd2870"],
    "Medical": ["medical", "health", "va ", "endocrin", "tricare", "acth", "dd2870"],
    "Relationships_Comms": ["chat", "whatsapp", "email", "text", "social", "relationship"],
    "Family_Context": ["family", "spencer", "bloom"],
    "Knowledge_Projects": ["project", "code", "narrative"],
    # New: Hermes system / agent data (included per Jeff direction, tagged for meta/twin training use)
    "Hermes_System": ["hermes", "discovery_walker", "dt_tagging", "three_bucket", "c_clean", "session", "manifest", "provenance", "silo", "digital-twin", "composer", "phronesis"],
}

SENSITIVITY_RULES = {
    "medical": ["medical", "health", "va ", "endocrin", "acth", "dd2870"],
    "military": ["navy", "military", "usn", "dd11", "dd28", "norfolk"],
    "financial": ["financial", "tax", "income", "1099"],
    "communications": ["chat", "whatsapp", "email", "text"],
}

def _get_file_hash(path: Path, block_size=65536) -> str:
    """Stdlib SHA256 hash for future deduplication and provenance."""
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(block_size), b""):
            h.update(block)
    return h.hexdigest()[:16]  # short hash for readability


def enhance_with_dt_tags(res: dict) -> dict:
    """
    Enhances a classification result with DT tags.
    Expects at minimum: 'path', 'filename' or derives from path,
    'footprint_category', optional 'entity_links', 'category'.

    Now supports provenance fields (auto-populated or passed in):
    - source_account: e.g. "old_jeffrey_j_bloom", "warz_burner"
    - source_original_path: original Drive path or local mirror path
    - backup_timestamp: ISO timestamp from backup/mtime if available
    - cross_account_notes: notes for cross-account merges / references
    These are preserved if pre-set on input res; defaults otherwise.
    Navy_Related_Medical and all other rules continue to operate cleanly.
    """
    path_str = res.get("path", "")
    name = Path(path_str).name.lower()
    full_path = path_str.lower()
    footprint_cat = res.get("footprint_category", "General")
    entities = res.get("entity_links", [])
    category = res.get("category", "")
    is_export_stub = res.get("is_export_stub", False)
    file_size = res.get("size_bytes", 0)

    # === DT Relevance (dynamic + variability for AI curation, 2026-06-26)
    # Domains detected first for real dynamic scoring
    twin_domains = set()
    for domain, keywords in DOMAIN_RULES.items():
        if any(kw in (name + full_path) for kw in keywords):
            twin_domains.add(domain)
    if footprint_cat == "Military_Service":
        twin_domains.add("Navy_Service_History")
    elif footprint_cat in ["Medical", "Navy_Service_History"]:
        twin_domains.add(footprint_cat)
    if "Medical" in twin_domains or footprint_cat == "Medical":
        navy_related_kws = ["service", "va ", "navy", "military", "disability", "injury", "retirement", "dd11", "dd28", "dd2870", "acth", "norfolk"]
        if any(kw in (name + full_path) for kw in navy_related_kws):
            twin_domains.add("Navy_Related_Medical")
    if "Personal_Family" in entities or "family" in full_path:
        twin_domains.add("Family_Context")
    if footprint_cat in ["Personal_Narrative", "Projects_Code"]:
        twin_domains.add("Knowledge_Projects")

    # Dynamic scoring with real variability (size, domain density, life signals, path)
    reasons = []
    base = 0.4
    if is_export_stub or "Needs-Review" in category or "ORPHAN" in category:
        base = 0.15
        reasons.append("export_stub_or_orphan")
    elif "PERSONAL" in category:
        base = 0.65
        reasons.append("personal_classification")

    size_factor = 0.0
    if file_size > 100000: size_factor = 0.12
    elif file_size > 10000: size_factor = 0.08
    elif file_size < 2000: size_factor = -0.15
    if size_factor != 0: reasons.append(f"size_factor_{size_factor}")

    domain_density = min(0.25, len(twin_domains) * 0.07)
    if domain_density > 0: reasons.append(f"domain_density_{len(twin_domains)}")

    life_boost = 0.0
    if "Navy_Service_History" in twin_domains or "Medical" in twin_domains or "Navy_Related_Medical" in twin_domains:
        life_boost = 0.15
        reasons.append("high_life_history_signal")

    path_boost = 0.0
    if any(x in full_path for x in ["documents", "desktop", "medical", "navy", "phronesis", "hermesdata", "vault"]):
        path_boost = 0.1
        reasons.append("strong_path_signal")

    relevance_score = min(1.0, max(0.0, base + size_factor + domain_density + life_boost + path_boost))
    if relevance_score >= 0.75:
        dt_relevance = "high"
    elif relevance_score >= 0.45:
        dt_relevance = "medium"
    else:
        dt_relevance = "low"

    res["dt_relevance"] = dt_relevance
    res["relevance_score"] = round(relevance_score, 3)
    res["relevance_reasons"] = reasons

    # === Twin Domains (multi-domain support) ===
    twin_domains = set()

    # Process all data-driven rules (includes new unified Navy_Service_History)
    for domain, keywords in DOMAIN_RULES.items():
        if any(kw in (name + full_path) for kw in keywords):
            twin_domains.add(domain)

    # Legacy footprint handling (update old Military_Service references)
    if footprint_cat == "Military_Service":
        twin_domains.add("Navy_Service_History")
    elif footprint_cat in ["Medical", "Navy_Service_History"]:
        twin_domains.add(footprint_cat)

    # Smart cross-link: Medical files mentioning service/VA/Navy get Navy_Related_Medical + cross-twin
    if "Medical" in twin_domains or footprint_cat == "Medical":
        navy_related_kws = ["service", "va ", "navy", "military", "disability", "injury", "retirement", "dd11", "dd28", "dd2870", "acth", "norfolk"]
        if any(kw in (name + full_path) for kw in navy_related_kws):
            twin_domains.add("Navy_Related_Medical")
            # Explicit cross-twin signal (already default True, but reinforce)
            res["cross_twin_potential"] = True
            res.setdefault("extensible_tags", []).append("Navy_Related_Medical")

    if "Personal_Family" in entities or "family" in full_path:
        twin_domains.add("Family_Context")
    if footprint_cat in ["Personal_Narrative", "Projects_Code"]:
        twin_domains.add("Knowledge_Projects")

    # === Privacy & Sensitivity ===
    privacy_tier = "me_only"
    sensitivity_tags = set()

    for tag, keywords in SENSITIVITY_RULES.items():
        if any(kw in name for kw in keywords) or (tag == "medical" and footprint_cat == "Medical"):
            sensitivity_tags.add(tag)
        if tag == "military" and (footprint_cat in ["Military_Service", "Navy_Service_History"] or "Navy_Service_History" in twin_domains):
            sensitivity_tags.add(tag)

    # === Extensibility & Provenance helpers ===
    res["dt_training_relevance"] = dt_relevance
    res["twin_domains"] = sorted(list(twin_domains)) or ["General"]
    res["privacy_tier"] = privacy_tier
    res["sensitivity_tags"] = sorted(list(sensitivity_tags))
    res["curator_review_status"] = "auto_suggested"
    res["dt_notes"] = "Auto-suggested. Override any field during review."

    # Future-proof fields (populated by caller if available)
    if "file_hash" not in res:
        try:
            p = Path(path_str)
            res["file_hash"] = _get_file_hash(p) if p.exists() else ""
        except Exception:
            res["file_hash"] = ""

    # Placeholders for growth
    if "knowledge_graph_relations" not in res:
        res["knowledge_graph_relations"] = []
    if "extensible_tags" not in res:
        res["extensible_tags"] = []
    if "cross_twin_potential" not in res:
        res["cross_twin_potential"] = True
    if "pii_detected" not in res:
        res["pii_detected"] = bool(sensitivity_tags)  # crude initial signal

    # === Data source provenance (new: account, original path, timestamp, cross-account notes) ===
    # Preserved if passed in via base res (e.g. from discovery_walker or multi-account copy);
    # defaults to empty / path-derived. Does not interfere with Navy_Related_Medical etc.
    provenance_defaults = {
        "source_account": "",
        "source_original_path": path_str,
        "backup_timestamp": "",
        "cross_account_notes": "",
    }
    for k, default_val in provenance_defaults.items():
        if k not in res:
            res[k] = default_val
        elif res.get(k) in (None, ""):
            res[k] = default_val

    return res
