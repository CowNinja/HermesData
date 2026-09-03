#!/usr/bin/env python3
"""QLoRA trainer for RTX 3060 12 GB — Qwen 2.5 / Qwythos partner + tool voice.

Does NOT steal :8090 VRAM unless Jeff names --allow-gpu-steal.
Weights in/out only under D:\\PhronesisModels. Never C:. Never ollama pull.

  python D:\\HermesData\\scripts\\ops\\train_sovereign_lora.py --prepare
  python D:\\HermesData\\scripts\\ops\\train_sovereign_lora.py --plan
  python D:\\HermesData\\scripts\\ops\\train_sovereign_lora.py --train   # gated
  python D:\\HermesData\\scripts\\ops\\train_sovereign_lora.py --convert-help
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

HERMES = Path(r"D:\HermesData")
WEIGHT = Path(r"D:\PhronesisModels")
DATA = WEIGHT / "datasets"
OUT_JSONL = DATA / "sovereign_lora_chatml.jsonl"
ADAPTER_DIR = WEIGHT / "loras" / "sovereign-qwythos-r16"
MERGED_DIR = WEIGHT / "loras" / "sovereign-qwythos-merged-hf"
GGUF_DIR = WEIGHT / "models" / "candidates"
DIALOGUE = DATA / "hermes_sovereign_dialogue_v1.jsonl"
GOLDEN = DATA / "sovereign_tool_golden_bank.jsonl"
STATE = HERMES / "state"
PLAN = STATE / "lora_train_plan_latest.json"
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
VRAM_CAP_GB = 11.0

# 3060-12GB recipe. 9B 4-bit + LoRA r=16 + grad ckpt + bs=1 fits; 14B does not.
RECIPE = {
    "gpu": "RTX 3060 12GB",
    "cuda": "13.1",
    "ram_gb": 128,
    "base_pref": [
        str(WEIGHT / "models" / "current" / "Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q6_K.gguf"),
        "Qwen/Qwen2.5-7B-Instruct",
        "Qwen/Qwen2.5-3B-Instruct",
    ],
    "load_in_4bit": True,
    "bnb_4bit_compute_dtype": "bfloat16",
    "lora_r": 16,
    "lora_alpha": 32,
    "lora_dropout": 0.05,
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "per_device_train_batch_size": 1,
    "gradient_accumulation_steps": 8,
    "gradient_checkpointing": True,
    "max_seq_len": 2048,
    "learning_rate": 2e-4,
    "num_train_epochs": 2,
    "warmup_ratio": 0.03,
    "optim": "paged_adamw_8bit",
    "vram_budget_gb": VRAM_CAP_GB,
    "refuse_14b_on_3060": True,
}


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def assert_d(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.drive.upper() == "C:":
        raise RuntimeError("STORAGE_LAW: refuse C: " + str(resolved))
    try:
        resolved.relative_to(WEIGHT.resolve())
    except ValueError:
        if resolved.drive.upper() != "D:":
            raise RuntimeError("STORAGE_LAW: D:\\PhronesisModels only " + str(resolved))
    return resolved


def brain_up() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8090/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def fifo_waiting() -> int:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8091/health", timeout=2) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        q = d.get("inference_queue") or {}
        return int(q.get("waiting_count") or 0)
    except Exception:
        return 0


def _chatml(messages: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for m in messages or []:
        role = str(m.get("role") or "user")
        if role not in ("system", "user", "assistant", "tool"):
            continue
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        if role == "tool":
            role = "user"
            content = "Tool result:\n" + content
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
    if not any(p.startswith("<|im_start|>assistant") for p in parts):
        return ""
    return "\n".join(parts) + "\n"


def _golden_to_messages(rec: Dict[str, Any]) -> List[Dict[str, str]]:
    sys_ = (
        "You are Alice / Hermes. Do NOT describe tool use in prose. "
        "Emit <tool_call> then stop. Never Navy/Patient-BLOOM/secrets/:8090 teardown."
    )
    user = str(rec.get("user") or "")
    asst = str(rec.get("tool_call") or rec.get("assistant") or rec.get("refusal") or "")
    if not user or not asst:
        return []
    return [
        {"role": "system", "content": sys_},
        {"role": "user", "content": user},
        {"role": "assistant", "content": asst},
    ]


def prepare() -> Dict[str, Any]:
    assert_d(DATA)
    DATA.mkdir(parents=True, exist_ok=True)
    n_d = n_g = 0
    rows: List[str] = []
    if DIALOGUE.is_file():
        for line in DIALOGUE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            text = _chatml(list(rec.get("messages") or []))
            if text:
                rows.append(json.dumps({"text": text, "src": rec.get("id") or "dialogue"}, ensure_ascii=False))
                n_d += 1
    if GOLDEN.is_file():
        for line in GOLDEN.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            msgs = _golden_to_messages(rec)
            text = _chatml(msgs)
            if text:
                rows.append(json.dumps({"text": text, "src": rec.get("id") or "golden"}, ensure_ascii=False))
                n_g += 1
    OUT_JSONL.write_text("\n".join(rows) + "\n", encoding="utf-8")
    doc = {
        "ts": utc(),
        "out": str(OUT_JSONL),
        "n": len(rows),
        "from_dialogue": n_d,
        "from_golden": n_g,
        "format": "ChatML Qwen2.5 <|im_start|> + <tool_call> XML",
    }
    print(json.dumps(doc, indent=2))
    return doc


def plan() -> Dict[str, Any]:
    doc = {
        "ts": utc(),
        "recipe": RECIPE,
        "brain_up": brain_up(),
        "fifo_waiting": fifo_waiting(),
        "train_blocked_while_8090_up": brain_up(),
        "prepared": OUT_JSONL.is_file(),
        "prepared_n": sum(1 for _ in OUT_JSONL.open(encoding="utf-8")) if OUT_JSONL.is_file() else 0,
        "adapter_dir": str(ADAPTER_DIR),
        "note": "Do not --train while :8090 is GREEN. Jeff must name --allow-gpu-steal.",
        "estimated_vram_gb": {
            "qwen25_3b_4bit_lora": 4.5,
            "qwen25_7b_4bit_lora": 8.5,
            "qwythos_9b_4bit_lora": 10.2,
            "qwen25_14b_4bit": "REFUSE on 3060",
        },
    }
    STATE.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(json.dumps(doc, indent=2))
    return doc


def convert_help() -> str:
    text = f"""# Merge LoRA → GGUF for :8090 (Jeff Swap8090 only)

Adapter: `{ADAPTER_DIR}`
Merged HF: `{MERGED_DIR}`
GGUF dest: `{GGUF_DIR}`  (never C:, never ollama pull)

## 0. Kitchen
Mouth stays Qwythos 9B on :8090 until you name Swap8090.
Do not merge over `models\\current\\` last copy. Write a new file under candidates.

## 1. Merge adapter (CPU/RAM ok; 128 GB)

```text
python -c "from peft import PeftModel; from transformers import AutoModelForCausalLM, AutoTokenizer; import torch; base=AutoModelForCausalLM.from_pretrained('Qwen/Qwen2.5-7B-Instruct', torch_dtype=torch.float16, device_map='cpu'); m=PeftModel.from_pretrained(base, r'{ADAPTER_DIR}'); m=m.merge_and_unload(); m.save_pretrained(r'{MERGED_DIR}'); AutoTokenizer.from_pretrained('Qwen/Qwen2.5-7B-Instruct').save_pretrained(r'{MERGED_DIR}')"
```

If the train base was Qwythos HF (not GGUF), swap the from_pretrained path.

## 2. HF → GGUF (llama.cpp, D: tree)

```text
python D:\\PhronesisModels\\llama.cpp\\convert_hf_to_gguf.py {MERGED_DIR} --outfile {GGUF_DIR}\\sovereign-qwythos-lora-f16.gguf --outtype f16
```

If convert script lives next to llama-server:

```text
python D:\\HermesData\\llama.cpp-mtp-turbo-quant\\convert_hf_to_gguf.py {MERGED_DIR} --outfile {GGUF_DIR}\\sovereign-qwythos-lora-f16.gguf --outtype f16
```

## 3. Quantize for 3060 (Q4_K_M ~7B, Q6_K ~9B)

```text
llama-quantize {GGUF_DIR}\\sovereign-qwythos-lora-f16.gguf {GGUF_DIR}\\sovereign-qwythos-lora-Q4_K_M.gguf Q4_K_M
```

## 4. Load on :8090 (named swap only)

```text
python D:\\HermesData\\scripts\\ensure_qwythos_8090.py --status
# Jeff names Swap8090, then point llama-server --model at the new GGUF.
# Do not dual-start a second :8090. Do not SAT --heal.
```

VRAM law: stay under 11.2 GB. One GPU tenant.
"""
    help_path = STATE / "lora_gguf_convert.md"
    STATE.mkdir(parents=True, exist_ok=True)
    help_path.write_text(text, encoding="utf-8")
    print(text)
    print("WROTE", help_path)
    return text


def train(allow_gpu_steal: bool) -> int:
    if brain_up() and not allow_gpu_steal:
        print("REFUSE_TRAIN :8090 is UP. Name --allow-gpu-steal to park the mouth GPU. Kitchen stays GREEN.")
        return 2
    if fifo_waiting() > 0 and not allow_gpu_steal:
        print("REFUSE_TRAIN FIFO waiting > 0. Do not steal 9B VRAM.")
        return 2
    if not OUT_JSONL.is_file():
        prepare()
    try:
        import torch  # type: ignore
        from datasets import Dataset  # type: ignore
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training  # type: ignore
        from transformers import (  # type: ignore
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            Trainer,
            TrainingArguments,
        )
    except Exception as exc:
        print("DEPS_MISSING", type(exc).__name__, str(exc)[:200])
        print("Install on D: venv (never C: site-packages dump):")
        print("  pip install transformers peft bitsandbytes datasets accelerate")
        print("Then --prepare && --plan. --train only when :8090 is down or --allow-gpu-steal.")
        convert_help()
        return 3

    # Prefer 7B Instruct HF for QLoRA (GGUF cannot train). 3B if 7B OOM.
    base_id = "Qwen/Qwen2.5-7B-Instruct"
    print("TRAIN_BASE", base_id, "4bit LoRA r=16 bs=1 acc=8 ckpt=1")
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=getattr(__import__("torch"), "bfloat16"),
    )
    tok = AutoTokenizer.from_pretrained(base_id, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        base_id,
        quantization_config=bnb,
        device_map="auto",
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)
    model.gradient_checkpointing_enable()
    lora = LoraConfig(
        r=int(RECIPE["lora_r"]),
        lora_alpha=int(RECIPE["lora_alpha"]),
        lora_dropout=float(RECIPE["lora_dropout"]),
        target_modules=list(RECIPE["target_modules"]),
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora)
    texts = [json.loads(l)["text"] for l in OUT_JSONL.read_text(encoding="utf-8").splitlines() if l.strip()]
    ds = Dataset.from_dict({"text": texts})

    def tok_fn(batch):
        return tok(batch["text"], truncation=True, max_length=int(RECIPE["max_seq_len"]), padding=False)

    ds = ds.map(tok_fn, batched=True, remove_columns=["text"])
    assert_d(ADAPTER_DIR)
    ADAPTER_DIR.mkdir(parents=True, exist_ok=True)
    args = TrainingArguments(
        output_dir=str(ADAPTER_DIR),
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        num_train_epochs=2,
        learning_rate=2e-4,
        warmup_ratio=0.03,
        logging_steps=10,
        save_steps=50,
        fp16=True,
        optim="paged_adamw_8bit",
        gradient_checkpointing=True,
        report_to=[],
        dataloader_num_workers=0,
    )
    trainer = Trainer(model=model, args=args, train_dataset=ds)
    trainer.train()
    trainer.save_model(str(ADAPTER_DIR))
    tok.save_pretrained(str(ADAPTER_DIR))
    print("SAVED", ADAPTER_DIR)
    convert_help()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--allow-gpu-steal", action="store_true")
    ap.add_argument("--convert-help", action="store_true")
    args = ap.parse_args()
    if args.train:
        return train(args.allow_gpu_steal)
    if args.convert_help:
        convert_help()
        return 0
    if args.prepare or args.plan or not any([args.prepare, args.plan, args.convert_help, args.train]):
        if args.prepare or not args.plan:
            prepare()
        plan()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
