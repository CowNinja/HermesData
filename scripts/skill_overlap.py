#!/usr/bin/env python3
"""Skill Librarian: Content Overlap Analyzer
Detects skills that share significant section content, even if descriptions differ."""
import os, re, sys, json
from pathlib import Path
from collections import defaultdict

SKILLS_DIR = Path(r"D:\HermesData\skills")

def extract_sections(content: str) -> dict:
    """Extract ## sections as {title: body_text}."""
    sections = {}
    parts = re.split(r'^##\s+', content, flags=re.MULTILINE)
    for part in parts[1:]:  # skip preamble
        lines = part.split('\n')
        title = lines[0].strip().lower()
        body = '\n'.join(lines[1:]).strip()
        if len(body) > 50:  # Only meaningful sections
            sections[title] = body
    return sections

def jaccard_similarity(set_a, set_b):
    """Jaccard similarity between two sets of words."""
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0

def section_similarity(body_a, body_b):
    """Word-level Jaccard similarity between two section bodies."""
    words_a = set(re.findall(r'\b\w{4,}\b', body_a.lower()))
    words_b = set(re.findall(r'\b\w{4,}\b', body_b.lower()))
    return jaccard_similarity(words_a, words_b)

def main():
    # Load all skills
    skills = {}
    for skill_md in SKILLS_DIR.rglob("SKILL.md"):
        rel = skill_md.parent.relative_to(SKILLS_DIR)
        if '.curator_backups' in str(rel) or '.hub' in str(rel):
            continue
        content = skill_md.read_text(encoding='utf-8', errors='ignore')
        sections = extract_sections(content)
        skills[str(rel)] = {
            'sections': sections,
            'section_titles': set(sections.keys()),
            'chars': len(content),
        }

    print(f"=== CONTENT OVERLAP ANALYSIS ===")
    print(f"Skills analyzed: {len(skills)}")
    print()

    # Find skills with overlapping section titles
    title_groups = defaultdict(list)
    for name, data in skills.items():
        key = frozenset(data['section_titles'])
        title_groups[key].append(name)

    same_sections = {k: v for k, v in title_groups.items() if len(v) > 1 and len(k) > 2}
    if same_sections:
        print(f"=== SKILLS WITH IDENTICAL SECTION STRUCTURES ({len(same_sections)} groups) ===")
        for titles, names in sorted(same_sections.items(), key=lambda x: -len(x[1])):
            print(f"  [{len(names)}x] Sections: {', '.join(sorted(titles)[:5])}")
            for n in sorted(names):
                print(f"        → {n} ({skills[n]['chars']}c)")
            print()

    # Find skills with high content overlap in shared sections
    overlap_pairs = []
    skill_names = list(skills.keys())
    for i in range(len(skill_names)):
        for j in range(i + 1, len(skill_names)):
            a, b = skill_names[i], skill_names[j]
            shared_titles = skills[a]['section_titles'] & skills[b]['section_titles']
            if len(shared_titles) < 2:
                continue
            # Average similarity across shared sections
            sims = []
            for title in shared_titles:
                sim = section_similarity(skills[a]['sections'][title], skills[b]['sections'][title])
                sims.append(sim)
            avg_sim = sum(sims) / len(sims) if sims else 0
            if avg_sim > 0.5:  # More than 50% word overlap
                overlap_pairs.append((a, b, avg_sim, len(shared_titles), shared_titles))

    if overlap_pairs:
        overlap_pairs.sort(key=lambda x: -x[2])
        print(f"=== HIGH CONTENT OVERLAP PAIRS ({len(overlap_pairs)}) ===")
        for a, b, sim, n_sections, titles in overlap_pairs[:20]:
            print(f"  {sim:.0%} overlap across {n_sections} sections")
            print(f"    {a} ({skills[a]['chars']}c) ↔ {b} ({skills[b]['chars']}c)")
            print(f"    Shared: {', '.join(sorted(titles)[:5])}")
            print()

    # Skills missing frontmatter
    missing_fm = []
    for skill_md in SKILLS_DIR.rglob("SKILL.md"):
        rel = skill_md.parent.relative_to(SKILLS_DIR)
        if '.curator_backups' in str(rel) or '.hub' in str(rel):
            continue
        content = skill_md.read_text(encoding='utf-8', errors='ignore')
        if not re.search(r'^---\s*\n.*?\n---', content, re.DOTALL):
            missing_fm.append(str(rel))

    if missing_fm:
        print(f"=== MISSING FRONTMATTER ({len(missing_fm)}) ===")
        for name in missing_fm:
            print(f"  {name}")
        print()

    # Save results
    results = {
        'same_section_groups': {', '.join(sorted(k)): v for k, v in same_sections.items()},
        'overlap_pairs': [{'a': a, 'b': b, 'similarity': round(sim, 3), 'shared_sections': n} for a, b, sim, n, _ in overlap_pairs],
        'missing_frontmatter': missing_fm,
    }
    out_path = SKILLS_DIR / ".librarian_overlap.json"
    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Results saved to {out_path}")

if __name__ == '__main__':
    main()
