#!/usr/bin/env python3
"""Skill Librarian: Inventory & Analysis Tool"""
import os, re, sys, json
from pathlib import Path

SKILLS_DIR = Path(r"D:\HermesData\skills")

def parse_skill(path: Path):
    """Parse a SKILL.md file and extract metadata."""
    content = path.read_text(encoding='utf-8', errors='ignore')
    chars = len(content)
    
    # Extract frontmatter
    fm_match = re.search(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    fm = fm_match.group(1) if fm_match else ""
    
    desc_match = re.search(r'description:\s*["\']?(.+?)["\']?\s*$', fm, re.MULTILINE)
    desc = desc_match.group(1).strip()[:80] if desc_match else 'NO DESC'
    
    cat_match = re.search(r'category:\s*(.+?)\s*$', fm, re.MULTILINE)
    cat = cat_match.group(1).strip() if cat_match else 'none'
    
    ver_match = re.search(r'version:\s*(.+?)\s*$', fm, re.MULTILINE)
    ver = ver_match.group(1).strip() if ver_match else 'none'
    
    # Count sections
    sections = len(re.findall(r'^##\s+', content, re.MULTILINE))
    
    # Detect duplicates by normalized description
    desc_norm = re.sub(r'[^a-z0-9]', '', desc.lower())
    
    return {
        'path': str(path.parent.relative_to(SKILLS_DIR)),
        'chars': chars,
        'category': cat,
        'description': desc,
        'desc_norm': desc_norm,
        'version': ver,
        'sections': sections,
    }

def main():
    skills = []
    for skill_md in SKILLS_DIR.rglob("SKILL.md"):
        rel = skill_md.parent.relative_to(SKILLS_DIR)
        # Skip backup dirs
        if '.curator_backups' in str(rel) or '.hub' in str(rel):
            continue
        try:
            info = parse_skill(skill_md)
            skills.append(info)
        except Exception as e:
            print(f"ERROR parsing {rel}: {e}", file=sys.stderr)
    
    skills.sort(key=lambda x: x['chars'])
    
    # Find duplicate descriptions
    desc_counts = {}
    for s in skills:
        dn = s['desc_norm']
        if len(dn) > 10:  # Only meaningful descriptions
            desc_counts.setdefault(dn, []).append(s['path'])
    
    dupes = {k: v for k, v in desc_counts.items() if len(v) > 1}
    
    # Find suspiciously similar paths
    path_stems = {}
    for s in skills:
        stem = s['path'].replace('-', '').replace('_', '').lower()
        path_stems.setdefault(stem, []).append(s['path'])
    
    path_dupes = {k: v for k, v in path_stems.items() if len(v) > 1}
    
    # Output
    print(f"=== SKILL LIBRARIAN INVENTORY ===")
    print(f"Total skills: {len(skills)}")
    print(f"Duplicate descriptions: {len(dupes)} clusters")
    print(f"Similar path names: {len(path_dupes)} clusters")
    print()
    
    # Size distribution
    sizes = [s['chars'] for s in skills]
    print(f"Size range: {min(sizes)}-{max(sizes)} chars")
    print(f"Median: {sorted(sizes)[len(sizes)//2]} chars")
    tiny = sum(1 for s in sizes if s < 500)
    small = sum(1 for s in sizes if 500 <= s < 1500)
    medium = sum(1 for s in sizes if 1500 <= s < 5000)
    large = sum(1 for s in sizes if s >= 5000)
    print(f"Tiny (<500c): {tiny} | Small (500-1500c): {small} | Medium (1500-5000c): {medium} | Large (5000c+): {large}")
    print()
    
    # Duplicate description clusters
    if dupes:
        print("=== DUPLICATE DESCRIPTION CLUSTERS ===")
        for dn, paths in sorted(dupes.items(), key=lambda x: -len(x[1])):
            print(f"  [{len(paths)}x] {paths[0]}")
            for p in paths[1:]:
                print(f"        → {p}")
        print()
    
    # Similar path clusters
    if path_dupes:
        print("=== SIMILAR PATH CLUSTERS ===")
        for stem, paths in sorted(path_dupes.items(), key=lambda x: -len(x[1])):
            print(f"  [{len(paths)}x] {paths}")
        print()
    
    # Skills with no description
    no_desc = [s for s in skills if s['description'] == 'NO DESC']
    if no_desc:
        print(f"=== SKILLS WITH NO DESCRIPTION ({len(no_desc)}) ===")
        for s in no_desc:
            print(f"  {s['path']} ({s['chars']}c)")
        print()
    
    # Tiny skills (likely stubs)
    tiny_skills = [s for s in skills if s['chars'] < 500]
    if tiny_skills:
        print(f"=== TINY SKILLS / STUBS ({len(tiny_skills)}) ===")
        for s in tiny_skills:
            print(f"  {s['path']} ({s['chars']}c): {s['description'][:60]}")
        print()
    
    # Category distribution
    cats = {}
    for s in skills:
        cats[s['category']] = cats.get(s['category'], 0) + 1
    print("=== CATEGORY DISTRIBUTION ===")
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")
    
    # Save full inventory as JSON
    out_path = SKILLS_DIR / ".librarian_inventory.json"
    with open(out_path, 'w') as f:
        json.dump({'skills': skills, 'dupes': dupes, 'path_dupes': path_dupes}, f, indent=2)
    print(f"\nFull inventory saved to {out_path}")

if __name__ == '__main__':
    main()
