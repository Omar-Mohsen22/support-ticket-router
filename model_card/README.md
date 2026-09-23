---
license: cc-by-nc-4.0
base_model: Qwen/Qwen2.5-1.5B-Instruct
library_name: peft
datasets:
- Tobi-Bueck/customer-support-tickets
language:
- en
pipeline_tag: text-generation
tags:
- qlora
- lora
- text-classification
- customer-support
---

# ticket-router: QLoRA adapter for Qwen/Qwen2.5-1.5B-Instruct

## What it is

This is a LoRA adapter for [`Qwen/Qwen2.5-1.5B-Instruct`](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct). It
is not a full set of model weights. Given the text of an English customer-support ticket, it
outputs one compact JSON object with three labels: `queue` (10 classes),
`priority` (3) and `type` (4).

This repo holds checkpoint-1500. I picked it because it had the lowest eval loss on
the full validation set out of the 10 checkpoints saved during training.

## Test results

Scored on a frozen test split of 1633 tickets, using the evaluation harness in the
GitHub repo.

| field | macro-F1 | accuracy |
| --- | --- | --- |
| queue | 0.3999 | 48.81% |
| priority | 0.4944 | 53.09% |
| type | 0.8559 | 85.67% |

- Exact match (all three fields correct): 26.03%.
- Invalid outputs (not parseable, or a label outside the allowed set): 0.06%,
  which is 1 of 1633.

For comparison, on the same split: TF-IDF + logistic regression scores 0.3683 /
0.5445 / 0.8412 macro-F1 (queue / priority / type), and zero-shot
`gpt-4o-mini` scores 0.2554 / 0.3214 / 0.5209. So this adapter beats
zero-shot `gpt-4o-mini` on every field, and beats TF-IDF on queue and type but not on priority.

The full comparison table is in the [GitHub README](https://github.com/Omar-Mohsen22/support-ticket-router#headline-results). The GitHub repo is
private for now.

## Training

- **Method:** QLoRA. The base model is loaded in 4-bit NF4, with
  double quantization. The compute dtype is picked at runtime from the GPU: bfloat16 where it is
  supported, float16 otherwise, which is the case on a T4.
- **LoRA:** r=16, alpha=32, dropout
  0.05, on `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`.
- **Loss:** on completion tokens only. The system prompt and ticket text are not trained on.
- **Data:** 13,070 training examples and 1,635 validation examples, from the English
  rows of [Tobi-Bueck/customer-support-tickets](https://huggingface.co/datasets/Tobi-Bueck/customer-support-tickets).
- **Schedule:** 3 epochs, effective batch size 16
  (4 per device x 4 gradient
  accumulation). Learning rate 0.0002, cosine schedule, warmup
  ratio 0.03, `paged_adamw_8bit`, max sequence length 384, seed
  42.
- **Hardware:** one Tesla T4 on Google Colab (free tier),
  3.35 GPU-hours.
- **Checkpoint selection:** a checkpoint was saved every 250 steps, and each
  one was scored on the full validation set after training. checkpoint-1500 had the
  lowest loss (0.1538). The final checkpoint, 2451, scored
  0.1649, which is 7.24% worse.

## How to use

This follows `src/ticket_router/predictors/adapter_predictor.py` in the GitHub repo. It uses the
same system prompt, the base model's chat template, left padding and greedy decoding. It needs a
CUDA GPU with `bitsandbytes`. This repo is private, so log in first (`hf auth login`) or pass
`token=...` to `from_pretrained`.

The user message is the ticket text: the subject, a newline, then the body. If there is no
subject, it is the body alone.

```python
import json

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

BASE = "Qwen/Qwen2.5-1.5B-Instruct"
ADAPTER = "Omar-Mohsen22/ticket-router-qwen2.5-1.5b-qlora"
SYSTEM = "You are a support-ticket routing classifier. Given a ticket's text, output ONLY a single, compact JSON object (no extra whitespace) with exactly these three keys, in this order: queue, priority, type.\n\nqueue must be exactly one of: [\"Billing and Payments\", \"Customer Service\", \"General Inquiry\", \"Human Resources\", \"IT Support\", \"Product Support\", \"Returns and Exchanges\", \"Sales and Pre-Sales\", \"Service Outages and Maintenance\", \"Technical Support\"]\npriority must be exactly one of: [\"high\", \"low\", \"medium\"]\ntype must be exactly one of: [\"Change\", \"Incident\", \"Problem\", \"Request\"]"

# bfloat16 on compute capability 8.0 or newer, float16 otherwise (e.g. a T4).
major, _ = torch.cuda.get_device_capability(0)
dtype = torch.bfloat16 if major >= 8 else torch.float16

tokenizer = AutoTokenizer.from_pretrained(BASE)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "left"  # batched generation needs left padding

bnb = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=dtype,
    bnb_4bit_use_double_quant=True,
)
base = AutoModelForCausalLM.from_pretrained(
    BASE, quantization_config=bnb, device_map="auto", dtype=dtype
)
model = PeftModel.from_pretrained(base, ADAPTER)
model.eval()

tickets = ["Invoice charged twice\nI was billed twice for my March subscription. Please refund one charge."]
prompts = [
    tokenizer.apply_chat_template(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": t}],
        tokenize=False,
        add_generation_prompt=True,
    )
    for t in tickets
]
enc = tokenizer(
    prompts, truncation=True, max_length=384, add_special_tokens=False,
    padding=True, return_tensors="pt",
).to(model.device)

with torch.no_grad():
    out = model.generate(
        **enc, max_new_tokens=64, do_sample=False,
        pad_token_id=tokenizer.pad_token_id,
    )

for row in out[:, enc["input_ids"].shape[1]:]:
    text = tokenizer.decode(row, skip_special_tokens=True).strip()
    print(json.loads(text))  # can raise on an invalid output
```

The evaluation harness parses each output once, and never retries or repairs it. An output that
does not parse, or has a label outside the allowed set, counts as wrong.

## Licence

- **This adapter** is released under
  [CC-BY-NC-4.0](https://creativecommons.org/licenses/by-nc/4.0/), because it was trained on
  data licensed CC-BY-NC-4.0
  ([Tobi-Bueck/customer-support-tickets](https://huggingface.co/datasets/Tobi-Bueck/customer-support-tickets)).
  Non-commercial use only.
- **The base model**, `Qwen/Qwen2.5-1.5B-Instruct`, keeps its own licence. According to its Hub
  metadata, that is `apache-2.0` ([licence](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct/blob/main/LICENSE)).

## Limitations

- **Synthetic, English-only data.** According to the dataset's data card in the GitHub repo,
  the tickets are synthetic (LLM-generated), not real customer correspondence. Only the English
  rows were used. Results may not transfer to real tickets.
- **One training run, one seed.** There are no repeated runs and no confidence intervals.
- **Label noise.** An [error analysis](https://github.com/Omar-Mohsen22/support-ticket-router/blob/master/reports/error_analysis.md) found that
  this adapter and an unrelated TF-IDF model often fail on the same tickets and usually pick the
  same wrong label, and that several sampled tickets have text that contradicts their gold label. This
  suggests that much of the remaining error comes from the labels, not the model.
