"""Common interface shared by every retailer adapter.

Adding a new retailer means:
  1. Create `retailers/<name>.py` with a class subclassing `RetailerAdapter`.
  2. Register it in `retailers/__init__.py`.

Nothing in the core loop (monitor.py), filter, state, or notifier needs to
change — they all speak in terms of the `Product` dataclass below.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Product:
    """A single product, normalised across retailers."""

    retailer: str
    name: str
    url: str
    in_stock: bool
    price: float | None = None          # in EUR
    rating: str | None = None           # human-readable, e.g. "4.5/5 (6 avis)"
    # Stable identifier within a retailer (Shopify id, Hornbach article id...).
    # Falls back to the URL when the retailer exposes no id.
    product_id: str | None = None
    # Free-form spec hints (room size...) surfaced in the alert text.
    # Often already embedded in `name`, so this is optional.
    specs: str | None = None
    # Structured cooling capacity in BTU, when the retailer exposes it as a
    # parseable field (HiFi does). Used for the soft BTU floor in the filter.
    btu: int | None = None

    @property
    def key(self) -> str:
        """Globally unique, stable key used for de-duplication / state."""
        return f"{self.retailer}:{self.product_id or self.url}"

    def price_str(self) -> str:
        return f"{self.price:.2f} €" if self.price is not None else "prix ?"


class RetailerAdapter(ABC):
    """Base class for every retailer.

    Implementations must set `name` and implement `fetch()`. They should never
    raise for routine conditions (empty category, single product out of stock);
    a network/parse failure may raise and will be caught and logged by the core
    loop so one broken retailer can't take the whole run down.
    """

    name: str = "base"

    @abstractmethod
    def fetch(self) -> list[Product]:
        """Return every product currently listed in the watched category."""
        raise NotImplementedError
