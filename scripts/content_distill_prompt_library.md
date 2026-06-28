# Universal Local Content Distillation Prompts — v1.0 (2026-06-27)

Holistic pipeline for **any** source material: research, wisdom essays, silo ingest, technical docs, narratives.

Use with `local_content_distill.py` + `bridge_dispatch(force_local=True, prefer=vault)`.

Task types (MoE map): `metadata_extraction` → 8083 | `synthesis` → 8082 | `code` → 8081

---

## Step: metadata

```prompt
Extract structured YAML metadata from the source below. Be factual; no invention.

Fields: title, created, updated, type, tags, sources, confidence, key_entities, vault_links

Source excerpt:
{TEXT}
```

---

## Step: summary

```prompt
Produce a concise synthesis for vault ingestion.

## Key Insight
One paragraph grounded in the source.

## Parallels / Context
Bullet parallels to local-first AI, sovereignty, or Jeff's current work where relevant.

## Orientation
Actionable orientation (2-4 sentences).

Source:
{TEXT}
```

---

## Step: artifact (wisdom / growth blueprint mode)

```prompt
You are a PhronesisVault curator. Create a high-fidelity artifact from the source.

POSITIVE REFRAMING when style=wisdom. Ground every claim in the text.

Output Markdown with:
- Title + Source wikilink
- Core Principle
- Superpowers Unlocked (bullets)
- Sovereign Actions (concrete, low-friction)
- Vault Connections (≥4 [[wikilinks]])
- First-Principles check + mantra if applicable
- Provenance line: distilled locally via bridge_dispatch

Source:
{TEXT}
```

---

## Step: artifact (research mode)

```prompt
Create a research note for PhronesisVault from the source.

Structure: Summary, Key Claims, Evidence, Open Questions, Vault Links, Provenance.

Source:
{TEXT}
```