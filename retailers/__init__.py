"""Retailer adapter registry.

To add a retailer: write `retailers/<name>.py` with a `RetailerAdapter`
subclass, import it here, and add an instance to `ADAPTERS`. Nothing else in
the project needs to change.
"""

from .base import Product, RetailerAdapter
from .hornbach import HornbachAdapter
from .mediamarkt import MediaMarktAdapter

# Order matters only for output readability. MediaMarkt is the reliable one.
ADAPTERS: list[RetailerAdapter] = [
    MediaMarktAdapter(),
    HornbachAdapter(),
]

__all__ = ["Product", "RetailerAdapter", "ADAPTERS"]
