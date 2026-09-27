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

This demo routes a support ticket to a queue, priority and type with two models side by side: my TF-IDF baseline on the CPU, and Qwen2.5-1.5B-Instruct with my fine-tuned LoRA adapter on a shared ZeroGPU GPU.
Here the adapter runs on an unquantized bf16 base; the published numbers used a 4-bit base on a T4, so a few predictions can differ.
The code is at https://github.com/Omar-Mohsen22/support-ticket-router (private for now).
The model and data are CC-BY-NC-4.0 (trained on [Tobi-Bueck/customer-support-tickets](https://huggingface.co/datasets/Tobi-Bueck/customer-support-tickets)), so this demo is for non-commercial use only.
