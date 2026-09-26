---
title: Support Ticket Router
emoji: 💻
colorFrom: pink
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
license: cc-by-nc-4.0
short_description: Classify support tickets by queue, priority and type
---

I serve the TF-IDF baseline from my support-ticket routing project here as a small API: `GET /health`, and `POST /predict` with `{"subject": ..., "body": ...}`, which returns `queue`, `priority` and `type`.
It is the exact model behind the published TF-IDF numbers, not a refit.
The code is at https://github.com/Omar-Mohsen22/support-ticket-router (private for now).
The model is trained on [Tobi-Bueck/customer-support-tickets](https://huggingface.co/datasets/Tobi-Bueck/customer-support-tickets) (CC-BY-NC-4.0), so the model and this Space are for non-commercial use only; the source code itself is MIT.
