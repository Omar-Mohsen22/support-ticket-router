---
title: Support Ticket Router Demo
emoji: 📈
colorFrom: red
colorTo: gray
sdk: gradio
sdk_version: 6.28.0
python_version: 3.12.12
app_file: app.py
pinned: false
license: cc-by-nc-4.0
short_description: Fine-tuned Qwen2.5-1.5B vs TF-IDF on support tickets
---

This demo routes a support ticket to a queue, priority and type: my TF-IDF baseline runs on the CPU, and Qwen2.5-1.5B-Instruct with my fine-tuned 4-bit NF4 LoRA adapter runs on a shared ZeroGPU GPU. For the example tickets it also shows gpt-4o-mini's stored zero-shot output from my evaluation run (no live API call).
The adapter runs with the same inference config as the evaluated run (4-bit NF4, adapter not merged, float16 compute, greedy decoding); in batches of 8 it matched the published predictions on 1,623 of 1,633 test tickets.
The code is at https://github.com/Omar-Mohsen22/support-ticket-router, and the adapter is at [Omar-Mohsen22/ticket-router-qwen2.5-1.5b-qlora](https://huggingface.co/Omar-Mohsen22/ticket-router-qwen2.5-1.5b-qlora).

**Data and licence.** The model was trained on, and the example tickets are taken from, the [Tobi-Bueck/customer-support-tickets](https://huggingface.co/datasets/Tobi-Bueck/customer-support-tickets) dataset, licensed [CC-BY-NC-4.0](https://creativecommons.org/licenses/by-nc/4.0/). The adapter is a derived work under the same licence, so this demo is for non-commercial use only. The three "custom" example tickets are mine and not from the dataset.
