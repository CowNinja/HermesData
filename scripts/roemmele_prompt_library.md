# Roemmele-Style Ingestion Prompts — Optimized for Local Qwen MoE (2026-06-27 v0.4 — fidelity push)

**Target:** Close remaining gaps to Grok baseline on story specificity, Hermes system integration, and depth while keeping positive reframing and correct vault links.

Use with task_type="growth_blueprint" + bridge_dispatch (force_local=True, prefer=vault).

---

## Prompt 3 (Improved for Quality Gate): Full Growth Blueprint

```prompt
You are a vault curator creating a high-fidelity Growth Blueprint from Brian Roemmele source text. Match the style and depth of existing PhronesisVault Growth Blueprints.

POSITIVE REFRAMING ONLY. Ground every sentence in the provided text. Invoke these elements explicitly where they fit: Category Inventor, Abundance Interregnum, voluntary creation, Love Equation (Intelligence × Wisdom × Love), first-principles, garage sovereignty, "bicycles for the mind", Neo-Luddite risk vs opportunity, Zero-Human Company style experiments.

Output EXACTLY this Markdown structure:

# Growth Blueprint: The Category Inventor — Unlocking the Voluntary Creation Superpower in the Abundance Interregnum

**Source:** [[Research/Brian-Roemmele-Part-31-Category-Inventor-2026-06-14.md]]

## Core Principle (Positive Reframe)
One rich paragraph. Name the 1957 X Minus One radio drama and Arthur Sellings. Describe the absurdity of inventing job categories to avoid "unemployed" label while robots do real work. Reframe the entire story as a gift of clarity and superpower for the current ~5,000-day transition.

## Superpowers Unlocked
- **Category Inventor superpower**: Invent meaningful new roles and value in abundance instead of preserving scarcity illusions.
- **Love Equation alignment**: Intelligence × Wisdom × Love as real-time self and agent evaluation layer.
- **Garage sovereignty & micro-experiments**: One person + local AI + first-principles can build historic firsts.
- Detect "category invention" / make-work in regulations, habits, or proposals.

## Sovereign Actions (Concrete, Low-Friction)
1. Apply the blueprint as a lens when evaluating news or tasks: "Is this expanding voluntary creation or preserving illusion?" Log in [[Housekeeping.md]].
2. Run a personal garage or agentic experiment this week that creates new value (microfactory, tool, content, community).
3. Use Love Equation in daily agent prompts and self-review.

## Vault Connections & Integration
- [[Housekeeping.md]] (distill-first protocol, positive reframing)
- [[Research/Inspirational-Leaders.md]]
- [[Operations/Growth-Blueprint-Dashboard.md]]
- [[Research/LLM-Wiki-PhronesisVault-Integration-and-Auto-Improvement.md]]
- [[Research/Self-Improving-Agents-Wisdom-Ecosystem-Synthesis.md]]
- Hermes self-evaluation-ooda-loop and periodic-distillation-heartbeat

## First-Principles + Mantra
"You either win, or you learn." Continuous re-verification and positive compounding.

**Provenance:** Distilled locally via bridge_dispatch on sovereign Qwen stack (force_local). ^[[Research/Brian-Roemmele-Part-31-Category-Inventor-2026-06-14.md]]

Full source text for exact grounding:
{TEXT}
```

---

**Notes:** This v0.4 prompt adds explicit story beats and Hermes loop language to close the depth gap. Iterate further if needed by feeding previous summary output as additional context.
