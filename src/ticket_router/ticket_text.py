"""Step 26 -- the ONE place that turns a ticket's subject + body into the model
input text. make_dataset.py builds the `text` column with it (so every
training, evaluation and SFT example went through it), and the serving API
calls it for live requests, so a served ticket is built exactly like a
training ticket.

Rule (unchanged from step-02): `subject + "\\n" + body` when there is a
subject, otherwise `body` alone. "No subject" means None, NaN (pandas' null),
an empty string, or whitespace only. The processed splits contain no empty or
whitespace-only subjects (only nulls), so treating those as "no subject" did
not change any existing row -- verified in step-26 by regenerating the splits
byte-identically.
"""

from __future__ import annotations


def has_subject(subject: object) -> bool:
    # NaN (pandas' null for a missing string) is a float, so it fails the isinstance check.
    return isinstance(subject, str) and subject.strip() != ""


def build_ticket_text(subject: object, body: str) -> str:
    if has_subject(subject):
        return f"{subject}\n{body}"
    return body
