"""Typed label schema for ticket predictions.

`TicketLabels` is built dynamically from `data/processed/label_map.json` (the
label contract produced by `make_dataset.py`) so the allowed values can never
drift out of sync with the dataset: if `label_map.json` changes, this schema
changes with it automatically, with no hand-maintained enum to update.

`Literal[tuple(values)]` is exactly equivalent to `Literal[v1, v2, ...]` --
subscripting a generic with a tuple is the same as subscripting it with
comma-separated arguments -- which is what lets the Literal be built from a
runtime list instead of being spelled out by hand.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]
LABEL_MAP_PATH = REPO_ROOT / "data" / "processed" / "label_map.json"

if not LABEL_MAP_PATH.exists():
    raise FileNotFoundError(
        f"{LABEL_MAP_PATH} not found. Run src/ticket_router/make_dataset.py first "
        "to generate the label contract."
    )

_label_map: dict[str, list[str]] = json.loads(LABEL_MAP_PATH.read_text(encoding="utf-8"))

QueueLabel = Literal[tuple(_label_map["queue"])]
PriorityLabel = Literal[tuple(_label_map["priority"])]
TypeLabel = Literal[tuple(_label_map["type"])]


class TicketLabels(BaseModel):
    """The three routing targets for one ticket, each restricted to the exact
    value set observed in the training data (see label_map.json)."""

    queue: QueueLabel
    priority: PriorityLabel
    type: TypeLabel
