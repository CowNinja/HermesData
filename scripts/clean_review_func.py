def review_and_modify_markdowns(root, vision_text, silo_name, state, is_light):
    """Review MDs: add PKG YAML frontmatter (bulletproof with triple quotes), add resurfacing/splitting notes.
    Uses triple-quoted strings for the YAML block to eliminate any possibility of unterminated string literal errors.
    Clean, readable, efficient.
    """
    stats = {"reviewed": 0, "pkg_entities": 0, "pkg_relations": 0, "resurfaced": 0, "alignment_score": 0.0, "proposals": 0, "notes": ""}
    if not root.exists() or is_light:
        return stats
    for p in root.rglob("*.md"):
        if not should_process_deep(p, state):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
            stats["reviewed"] += 1
            orig = text
            changed = False
            if not text.startswith("---") and len(text) > 300:
                # Bulletproof: triple-quoted YAML frontmatter
                date_str = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
                pkg = """---
type: note
status: active
entities: []
relations: []
review_date: {date}
topic: general
silo: {silo}
---

""".format(date=date_str, silo=silo_name)
                text = pkg + text
                stats["pkg_entities"] += 1
                changed = True
            if len(text) > 5000 and "## " not in text[800:]:
                text += "\n\n> Consider splitting into atomic notes for PKG and resurfacing."
                changed = True
            if "[[" not in text[:400] and len(text) > 250:
                text += "\n\n> Link on entry + resurface: Connect to MOC or entity."
                stats["resurfaced"] += 1
                changed = True
            if changed and text != orig:
                dry = getattr(__import__("sys").modules.get("__main__"), "args", type("a", (), {"dry_run": False})()).dry_run
                if not dry:
                    try:
                        p.write_text(text, encoding="utf-8")
                    except Exception:
                        pass
                stats["proposals"] += 1
        except Exception:
            continue
    return stats
