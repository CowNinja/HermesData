#!/usr/bin/env python3
"""
Local Ollama AI Enrichment Layer for Personal Data Silo
- Uses only local models (no cloud tokens)
- Relevance judge, life event extractor, structured signals
- Works on text + metadata (extendable to vision with llava)
- Outputs JSON for easy manifest merging
"""

import subprocess
import json
import os
from pathlib import Path
from typing import Dict, Any

DEFAULT_MODEL = "phi3:mini"          # fast, good for structured output
JUDGE_MODEL = "qwen3:8b" or "dolphin-llama3:8b"  # stronger reasoning if available
VISION_MODEL = "llava:7b"            # for image/scans

PROMPT_RELEVANCE = """You are an expert curator for a personal digital life archive and digital twin training data.

Given this file metadata and any extracted text, rate its value for telling the story of this person's life.

Output ONLY valid JSON:
{
  "relevance_score": 0.0 to 1.0,
  "reason": "one sentence justification",
  "life_events": ["list of specific events, dates, or insights"],
  "domains": ["Navy_Service_History", "Medical", "Financial_Records", etc.],
  "training_value": "high/medium/low"
}

File: {filename}
Path context: {path_context}
Extracted text snippet: {text_snippet}
Size: {size} bytes
"""

PROMPT_EXTRACT = """Extract structured personal life information from the text below.
Output ONLY valid JSON:
{"dates": [...], "entities": [...], "events": [...], "financial_signals": [...], "medical_signals": [...] }

Text:
{text}
"""

def call_ollama(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 120) -> str:
    """Robust call via CLI (avoids Python package env issues)."""
    try:
        result = subprocess.run(
            ["ollama", "run", model, prompt],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(Path.home())
        )
        out = result.stdout.strip()
        # Try to extract JSON if model wrapped it
        if "```json" in out:
            out = out.split("```json")[1].split("```")[0].strip()
        return out
    except Exception as e:
        return json.dumps({"error": str(e)[:200]})

def enrich_file(file_path: str, extracted_text: str = "", metadata: Dict = None) -> Dict[str, Any]:
    """Run local AI enrichment on a file."""
    p = Path(file_path)
    meta = metadata or {}
    context = " > ".join(meta.get("parent_folders", [])) or str(p.parent)
    
    snippet = (extracted_text or "")[:1500]
    
    # Relevance judge
    prompt = PROMPT_RELEVANCE.format(
        filename=p.name,
        path_context=context,
        text_snippet=snippet[:800],
        size=meta.get("size", p.stat().st_size if p.exists() else 0)
    )
    judge_raw = call_ollama(prompt, model=DEFAULT_MODEL)
    
    try:
        judge = json.loads(judge_raw)
    except:
        judge = {"relevance_score": 0.5, "reason": "parse_error", "life_events": [], "domains": [], "training_value": "medium"}
    
    # Structured extraction (only if we have decent text)
    extract = {}
    if len(snippet) > 50:
        ext_prompt = PROMPT_EXTRACT.format(text=snippet[:1200])
        ext_raw = call_ollama(ext_prompt, model=DEFAULT_MODEL)
        try:
            extract = json.loads(ext_raw)
        except:
            extract = {"raw": ext_raw[:300]}
    
    result = {
        "local_ai": {
            "model": DEFAULT_MODEL,
            "relevance_judge": judge,
            "structured_extraction": extract,
            "ai_enriched_at": __import__("datetime").datetime.now().isoformat()
        }
    }
    return result

if __name__ == "__main__":
    # Quick self-test on a known high-signal file
    test_file = "G:/MemoryCard_Backups/Google Drive/00-scans/HP ADF/2018 - NavyFCU 1099-INT statement Spencer Bloom (2 Pages).pdf"
    print("Testing local AI enrich...")
    res = enrich_file(test_file, extracted_text="NavyFCU 1099-INT for Spencer Bloom 2018", 
                      metadata={"parent_folders": ["00-scans", "HP ADF"], "size": 3000000})
    print(json.dumps(res, indent=2))
