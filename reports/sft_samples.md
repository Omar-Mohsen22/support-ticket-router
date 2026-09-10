# SFT format samples

**Fine-tuning target model: `Qwen/Qwen2.5-1.5B-Instruct`** (QLoRA on Colab, self-hosted afterward -- see README.md "Next steps" for why this is not an OpenAI fine-tune). 5 formatted examples from `data/processed/sft/train.jsonl`, shown in full so the format can be read directly. Token counts below use `Qwen/Qwen2.5-1.5B-Instruct`'s own tokenizer and chat template (`tokenizer.apply_chat_template(...)`), not an OpenAI tokenizer.

## System message (identical for every example)

```
You are a support-ticket routing classifier. Given a ticket's text, output ONLY a single, compact JSON object (no extra whitespace) with exactly these three keys, in this order: queue, priority, type.

queue must be exactly one of: ["Billing and Payments", "Customer Service", "General Inquiry", "Human Resources", "IT Support", "Product Support", "Returns and Exchanges", "Sales and Pre-Sales", "Service Outages and Maintenance", "Technical Support"]
priority must be exactly one of: ["high", "low", "medium"]
type must be exactly one of: ["Change", "Incident", "Problem", "Request"]
```

## Example 1 -- ticket `tkt_014220` (268 tokens, Qwen/Qwen2.5-1.5B-Instruct)

**User turn (ticket text):**

```
Software Crashes and Performance Issues
Customer Support, <br>Our agency is facing software crashes and performance issues across multiple applications, which are significantly affecting productivity. This may be due to recent updates or conflicts with software versions. We have attempted to resolve the issue by restarting systems and reinstalling affected applications, but the problems persist. <br>The crashes and performance issues are causing substantial disruptions to our work, and we urgently need assistance to resolve the matter as soon as possible. <br>We would appreciate your guidance.
```

**Assistant turn (minified JSON, fixed key order):**

```
{"queue":"IT Support","priority":"medium","type":"Incident"}
```

Gold labels: queue='IT Support', priority='medium', type='Incident'

**Raw JSONL line (exact bytes written to the file -- a message list, not a pre-rendered string; the target model's chat template is applied at training time, not baked in here):**

```json
{"messages": [{"role": "system", "content": "You are a support-ticket routing classifier. Given a ticket's text, output ONLY a single, compact JSON object (no extra whitespace) with exactly these three keys, in this order: queue, priority, type.\n\nqueue must be exactly one of: [\"Billing and Payments\", \"Customer Service\", \"General Inquiry\", \"Human Resources\", \"IT Support\", \"Product Support\", \"Returns and Exchanges\", \"Sales and Pre-Sales\", \"Service Outages and Maintenance\", \"Technical Support\"]\npriority must be exactly one of: [\"high\", \"low\", \"medium\"]\ntype must be exactly one of: [\"Change\", \"Incident\", \"Problem\", \"Request\"]"}, {"role": "user", "content": "Software Crashes and Performance Issues\nCustomer Support, <br>Our agency is facing software crashes and performance issues across multiple applications, which are significantly affecting productivity. This may be due to recent updates or conflicts with software versions. We have attempted to resolve the issue by restarting systems and reinstalling affected applications, but the problems persist. <br>The crashes and performance issues are causing substantial disruptions to our work, and we urgently need assistance to resolve the matter as soon as possible. <br>We would appreciate your guidance."}, {"role": "assistant", "content": "{\"queue\":\"IT Support\",\"priority\":\"medium\",\"type\":\"Incident\"}"}]}
```

**What `Qwen/Qwen2.5-1.5B-Instruct`'s chat template actually renders this to at training time (for reference only -- this rendered string is NOT what's stored in the JSONL file):**

```
<|im_start|>system
You are a support-ticket routing classifier. Given a ticket's text, output ONLY a single, compact JSON object (no extra whitespace) with exactly these three keys, in this order: queue, priority, type.

queue must be exactly one of: ["Billing and Payments", "Customer Service", "General Inquiry", "Human Resources", "IT Support", "Product Support", "Returns and Exchanges", "Sales and Pre-Sales", "Service Outages and Maintenance", "Technical Support"]
priority must be exactly one of: ["high", "low", "medium"]
type must be exactly one of: ["Change", "Incident", "Problem", "Request"]<|im_end|>
<|im_start|>user
Software Crashes and Performance Issues
Customer Support, <br>Our agency is facing software crashes and performance issues across multiple applications, which are significantly affecting productivity. This may be due to recent updates or conflicts with software versions. We have attempted to resolve the issue by restarting systems and reinstalling affected applications, but the problems persist. <br>The crashes and performance issues are causing substantial disruptions to our work, and we urgently need assistance to resolve the matter as soon as possible. <br>We would appreciate your guidance.<|im_end|>
<|im_start|>assistant
{"queue":"IT Support","priority":"medium","type":"Incident"}<|im_end|>

```

## Example 2 -- ticket `tkt_023561` (231 tokens, Qwen/Qwen2.5-1.5B-Instruct)

**User turn (ticket text):**

```
Help with SaaS Integration for Valve Index VR Kit
Need support in optimizing SaaS integration for Valve Index VR Kit to enhance project management and streamline workflow for increased productivity. This VR Kit is essential for our team, and we aim to integrate it smoothly with our existing SaaS platform. Could use some guidance and recommendations to achieve this.
```

**Assistant turn (minified JSON, fixed key order):**

```
{"queue":"Product Support","priority":"medium","type":"Change"}
```

Gold labels: queue='Product Support', priority='medium', type='Change'

**Raw JSONL line (exact bytes written to the file -- a message list, not a pre-rendered string; the target model's chat template is applied at training time, not baked in here):**

```json
{"messages": [{"role": "system", "content": "You are a support-ticket routing classifier. Given a ticket's text, output ONLY a single, compact JSON object (no extra whitespace) with exactly these three keys, in this order: queue, priority, type.\n\nqueue must be exactly one of: [\"Billing and Payments\", \"Customer Service\", \"General Inquiry\", \"Human Resources\", \"IT Support\", \"Product Support\", \"Returns and Exchanges\", \"Sales and Pre-Sales\", \"Service Outages and Maintenance\", \"Technical Support\"]\npriority must be exactly one of: [\"high\", \"low\", \"medium\"]\ntype must be exactly one of: [\"Change\", \"Incident\", \"Problem\", \"Request\"]"}, {"role": "user", "content": "Help with SaaS Integration for Valve Index VR Kit\nNeed support in optimizing SaaS integration for Valve Index VR Kit to enhance project management and streamline workflow for increased productivity. This VR Kit is essential for our team, and we aim to integrate it smoothly with our existing SaaS platform. Could use some guidance and recommendations to achieve this."}, {"role": "assistant", "content": "{\"queue\":\"Product Support\",\"priority\":\"medium\",\"type\":\"Change\"}"}]}
```

## Example 3 -- ticket `tkt_025969` (230 tokens, Qwen/Qwen2.5-1.5B-Instruct)

**User turn (ticket text):**

```
Report on Data Breach Attempt in Hospital Systems
Noted the data breach attempt in hospital systems. This might have occurred due to outdated software vulnerabilities. Upgrades have been implemented, including antivirus scans and enhanced firewall settings to prevent future incidents. We request your assistance in conducting a thorough investigation and providing recommendations to improve security measures.
```

**Assistant turn (minified JSON, fixed key order):**

```
{"queue":"Technical Support","priority":"medium","type":"Incident"}
```

Gold labels: queue='Technical Support', priority='medium', type='Incident'

**Raw JSONL line (exact bytes written to the file -- a message list, not a pre-rendered string; the target model's chat template is applied at training time, not baked in here):**

```json
{"messages": [{"role": "system", "content": "You are a support-ticket routing classifier. Given a ticket's text, output ONLY a single, compact JSON object (no extra whitespace) with exactly these three keys, in this order: queue, priority, type.\n\nqueue must be exactly one of: [\"Billing and Payments\", \"Customer Service\", \"General Inquiry\", \"Human Resources\", \"IT Support\", \"Product Support\", \"Returns and Exchanges\", \"Sales and Pre-Sales\", \"Service Outages and Maintenance\", \"Technical Support\"]\npriority must be exactly one of: [\"high\", \"low\", \"medium\"]\ntype must be exactly one of: [\"Change\", \"Incident\", \"Problem\", \"Request\"]"}, {"role": "user", "content": "Report on Data Breach Attempt in Hospital Systems\nNoted the data breach attempt in hospital systems. This might have occurred due to outdated software vulnerabilities. Upgrades have been implemented, including antivirus scans and enhanced firewall settings to prevent future incidents. We request your assistance in conducting a thorough investigation and providing recommendations to improve security measures."}, {"role": "assistant", "content": "{\"queue\":\"Technical Support\",\"priority\":\"medium\",\"type\":\"Incident\"}"}]}
```

## Example 4 -- ticket `tkt_007610` (194 tokens, Qwen/Qwen2.5-1.5B-Instruct)

**User turn (ticket text):**

```
Evaluation of Digital Campaigns
The digital marketing efforts by the agency are achieving the anticipated engagement levels, though ineffective targeting could be a contributing factor.
```

**Assistant turn (minified JSON, fixed key order):**

```
{"queue":"Technical Support","priority":"medium","type":"Incident"}
```

Gold labels: queue='Technical Support', priority='medium', type='Incident'

**Raw JSONL line (exact bytes written to the file -- a message list, not a pre-rendered string; the target model's chat template is applied at training time, not baked in here):**

```json
{"messages": [{"role": "system", "content": "You are a support-ticket routing classifier. Given a ticket's text, output ONLY a single, compact JSON object (no extra whitespace) with exactly these three keys, in this order: queue, priority, type.\n\nqueue must be exactly one of: [\"Billing and Payments\", \"Customer Service\", \"General Inquiry\", \"Human Resources\", \"IT Support\", \"Product Support\", \"Returns and Exchanges\", \"Sales and Pre-Sales\", \"Service Outages and Maintenance\", \"Technical Support\"]\npriority must be exactly one of: [\"high\", \"low\", \"medium\"]\ntype must be exactly one of: [\"Change\", \"Incident\", \"Problem\", \"Request\"]"}, {"role": "user", "content": "Evaluation of Digital Campaigns\nThe digital marketing efforts by the agency are achieving the anticipated engagement levels, though ineffective targeting could be a contributing factor."}, {"role": "assistant", "content": "{\"queue\":\"Technical Support\",\"priority\":\"medium\",\"type\":\"Incident\"}"}]}
```

## Example 5 -- ticket `tkt_000057` (263 tokens, Qwen/Qwen2.5-1.5B-Instruct)

**User turn (ticket text):**

```
Query Regarding Integration Resources
Dear Customer Support Team,\n\nI hope this message reaches you well. I am seeking detailed information about the available documentation, support tools, and procedures for connecting the SaaS platform with external devices and third-party services listed within the product environment.\n\nAs our organization aims to improve operational efficiency through platform integration, it is essential for us to fully understand the possibilities and limitations. We are particularly interested in official manuals, API documentation, SDKs, and developer resources.
```

**Assistant turn (minified JSON, fixed key order):**

```
{"queue":"Customer Service","priority":"medium","type":"Request"}
```

Gold labels: queue='Customer Service', priority='medium', type='Request'

**Raw JSONL line (exact bytes written to the file -- a message list, not a pre-rendered string; the target model's chat template is applied at training time, not baked in here):**

```json
{"messages": [{"role": "system", "content": "You are a support-ticket routing classifier. Given a ticket's text, output ONLY a single, compact JSON object (no extra whitespace) with exactly these three keys, in this order: queue, priority, type.\n\nqueue must be exactly one of: [\"Billing and Payments\", \"Customer Service\", \"General Inquiry\", \"Human Resources\", \"IT Support\", \"Product Support\", \"Returns and Exchanges\", \"Sales and Pre-Sales\", \"Service Outages and Maintenance\", \"Technical Support\"]\npriority must be exactly one of: [\"high\", \"low\", \"medium\"]\ntype must be exactly one of: [\"Change\", \"Incident\", \"Problem\", \"Request\"]"}, {"role": "user", "content": "Query Regarding Integration Resources\nDear Customer Support Team,\\n\\nI hope this message reaches you well. I am seeking detailed information about the available documentation, support tools, and procedures for connecting the SaaS platform with external devices and third-party services listed within the product environment.\\n\\nAs our organization aims to improve operational efficiency through platform integration, it is essential for us to fully understand the possibilities and limitations. We are particularly interested in official manuals, API documentation, SDKs, and developer resources."}, {"role": "assistant", "content": "{\"queue\":\"Customer Service\",\"priority\":\"medium\",\"type\":\"Request\"}"}]}
```

## Token-length summary (full train split)

**Target model (`Qwen/Qwen2.5-1.5B-Instruct`) -- this is what the recommendation below is based on:**

n=13070, min=167, p50=236, p95=277, p99=290, max=377. Recommended `max_seq_len` = **288** (p95 rounded up to the nearest 32).


**For comparison only -- OpenAI `gpt-4o-mini` via tiktoken (NOT the fine-tuning target, not used for the recommendation above):**

n=13070, min=165, p50=232, p95=274, p99=287, max=373.


Full histograms and per-split truncation counts are printed by the script and recorded in PROGRESS.md.
