"""Persisted availability state for de-duplication.

State is a JSON file committed back to the repo by the GitHub Action so that a
notification fires only when a product flips out-of-stock -> in-stock, never on
every run. The very first run (empty/missing state) records everything silently
so you aren't spammed for the whole existing catalogue.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from retailers.base import Product

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "state.json")


@dataclass
class Transition:
    """A product that just became available."""

    product: Product


def load_state(path: str = DEFAULT_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict, path: str = DEFAULT_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def diff(products: list[Product], state: dict) -> tuple[list[Transition], dict]:
    """Compare current products against saved state.

    Returns the list of newly-in-stock transitions and the updated state to
    persist. `products` should already be the *filtered* set (real ACs only) so
    we only ever track and alert on relevant items.

    Rules:
      * empty incoming state  -> first run: record all, notify none.
      * known product, was out, now in -> notify.
      * new product (unseen), now in   -> notify (it just appeared in stock).
      * anything else -> just update the record.
    """
    first_run = len(state) == 0
    transitions: list[Transition] = []
    new_state = dict(state)  # preserve history for products not seen this run

    for p in products:
        prev = state.get(p.key)
        was_in_stock = bool(prev["in_stock"]) if prev else False
        seen_before = prev is not None

        if not first_run and p.in_stock and (not seen_before or not was_in_stock):
            transitions.append(Transition(product=p))

        new_state[p.key] = {
            "name": p.name,
            "retailer": p.retailer,
            "price": p.price,
            "in_stock": p.in_stock,
            "url": p.url,
        }

    return transitions, new_state
