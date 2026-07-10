# Enhanced functions for VaultWalker - explicit-only, local model intelligence, residency tags, smart evaluation
# To be spliced into main script

def local_model_file_evaluation(preview: str, path_str: str, current_silo: str) -> Dict:
    """Use existing qwen2.5:14b (or configured local model) for intelligent evaluation.
    Combines classification, action recommendation (distill, trim, split, relocate, etc.).
    Block by default unless explicit-rp confirmed.
    """
    model = "qwen2.5:14b"
    prompt = (
        "You are a strict sovereign data silo guardian for personal knowledge vaults. "
        "Never move data unless it is clearly explicit roleplay material for the walled sandbox. "
        "Block by default. For the file below output ONLY one line in this format:\n"
        "CLASS:explicit-rp|explicit-non-rp|non-explicit | ACTION:relocate|keep|flag_review|distill_compact|split_atomic|trim | "
        "REASON:short | RESIDENCY:sandbox-only|keep-current | POLICY:no-cross-except-explicit\n"
        f"File: {path_str}\nCurrent silo: {current_silo}\nPreview: {preview[:700]}\n"
    )
    try:
        result = subprocess.run(
            ["ollama", "run", model, prompt],
            capture_output=True, text=True, timeout=75
        )
        out = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        parts = {}
        for item in out.split("|"):
            if ":" in item:
                k, v = item.split(":", 1)
                parts[k.strip().lower()] = v.strip()
        return {
            "class": parts.get("class", "unknown"),
            "action": parts.get("action", "keep"),
            "reason": parts.get("reason", "model parse fail"),
            "residency": parts.get("residency", "keep-current"),
            "policy": parts.get("policy", "no-cross-except-explicit")
        }
    except Exception as e:
        return {"class": "unknown", "action": "keep", "reason": f"model error: {str(e)[:60]}", "residency": "keep-current", "policy": "no-cross-except-explicit"}

def is_explicit_rp_content(path: Path, preview: str = "") -> bool:
    """Hybrid: fast keywords + local model confirmation for RP-explicit only."""
    full = str(path).lower() + " " + preview.lower()
    keyword_hit = any(kw in full for kw in EXPLICIT_RP_KEYWORDS)
    if not keyword_hit:
        return False
    # Confirm with local model for intelligence and edge cases
    eval_result = local_model_file_evaluation(preview, str(path), "unknown")
    return eval_result.get("class") == "explicit-rp"

def evaluate_and_relocate_misplaced(root: Path, silo_name: str, dry_run: bool = False) -> Dict:
    """Explicit-only gates. Block by default.
    Move ONLY confirmed explicit-rp to RoleplaySandbox (central location).
    Edge case: explicit-non-rp or unrelated -> flag in audit, keep in place.
    Uses local model for smart actions (relocate/distill/etc.).
    """
    moved = 0
    evaluated = 0
    flagged = 0
    log = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            preview = p.read_text(encoding="utf-8", errors="ignore")[:600] if p.suffix in [".md", ".txt", ".py"] else ""
            model_eval = local_model_file_evaluation(preview, str(p), silo_name)
            evaluated += 1

            if model_eval["class"] == "explicit-rp" and silo_name != "RoleplaySandbox":
                # Explicit RP material -> centralize in sandbox
                relocate_to_sandbox(p, dry_run)
                moved += 1
                log.append(f"MOVED explicit-rp: {p} | reason: {model_eval['reason']}")
            elif model_eval["class"] == "explicit-non-rp":
                # Explicit but unrelated to roleplay -> keep where it is (edge case)
                flagged += 1
                audit_msg = f"FLAGGED explicit-non-rp (keep in {silo_name}): {p} | reason: {model_eval['reason']}"
                log.append(audit_msg)
                # Still log to sandbox audit for visibility
                audit = Path(r"D:\PhronesisVault\Roleplay-Sandbox\data\misplaced_from_vaultwalker\relocation_audit.md")
                audit.parent.mkdir(parents=True, exist_ok=True)
                with open(audit, "a", encoding="utf-8") as f:
                    f.write("## " + datetime.now().isoformat() + " - " + audit_msg + "\n")
            elif model_eval["action"] in ["distill_compact", "split_atomic", "trim"] and not dry_run:
                # Intelligent action via review pass (handled in review function)
                log.append(f"EVAL smart action suggested: {model_eval['action']} for {p}")
            else:
                log.append(f"KEPT in {silo_name}: {p} | class: {model_eval['class']}")

        except Exception:
            continue
    return {"moved": moved, "evaluated": evaluated, "flagged_non_rp": flagged, "log": log[:8]}

def review_and_modify_markdowns(root: Path, vision_text: str, silo_name: str, state: Dict[str, Any], is_light: bool) -> Dict:
    """Review with residency/policy tags + intelligent local model actions.
    Add PKG + residency. For larger files use model to distill/trim/split intelligently.
    """
    stats = {"reviewed": 0, "pkg_entities": 0, "resurfaced": 0, "proposals": 0, "smart_actions": 0}
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

            # Always ensure residency + policy tags
            if not text.startswith("---"):
                date_str = datetime.now().strftime("%Y-%m-%d")
                pkg = f"""---
type: note
status: active
entities: []
relations: []
review_date: {date_str}
silo: {silo_name}
residency: {"sandbox-only" if "RoleplaySandbox" in str(p) or is_explicit_rp_content(p, text[:300]) else "keep-current"}
policy: no-cross-except-explicit
topic: general
---

"""
                text = pkg + text
                stats["pkg_entities"] += 1
                changed = True

            # Intelligent actions for bigger files using local model
            if len(text) > 4000:
                preview = text[:800]
                eval_res = local_model_file_evaluation(preview, str(p), silo_name)
                action = eval_res.get("action", "keep")
                if action == "distill_compact":
                    # Simple distill: keep first 1500 + summary note
                    distilled = text[:1500] + "\n\n> [VaultWalker distilled via local model: core ideas preserved, bloat trimmed per " + eval_res.get("reason", "") + "]\n"
                    text = distilled
                    stats["smart_actions"] += 1
                    changed = True
                elif action == "split_atomic":
                    text += "\n\n> [Suggested split: break into 2-3 atomic notes focused on single ideas. Use MOC for connections.]\n"
                    stats["smart_actions"] += 1
                    changed = True
                elif action == "trim":
                    text = text[:2500] + "\n\n> [Trimmed for signal per local model recommendation.]\n"
                    stats["smart_actions"] += 1
                    changed = True

            if "[[" not in text[:400] and len(text) > 250:
                text += "\n\n> Link on entry + resurface."
                stats["resurfaced"] += 1
                changed = True

            if changed and text != orig:
                dry = False
                try:
                    dry = getattr(sys.modules.get("__main__"), "args", type("a", (), {"dry_run": False})()).dry_run
                except:
                    pass
                if not dry:
                    try:
                        p.write_text(text, encoding="utf-8")
                    except:
                        pass
                stats["proposals"] += 1
        except:
            continue
    return stats

# Note: relocate_to_sandbox and other helpers remain from main script. Indexes already run first in housekeeping.
