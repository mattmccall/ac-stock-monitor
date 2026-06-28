"""Retailer adapter registry.

To add a retailer: write `retailers/<name>.py` with a `RetailerAdapter`
subclass, import it here, and add an instance to `ADAPTERS`. Nothing else in
the project needs to change.
"""

from .base import Product, RetailerAdapter
from .batiself import BatiselfAdapter
from .conforama import ConforamaAdapter
from .hifi import HifiAdapter
from .hornbach import HornbachAdapter
from .mediamarkt import MediaMarktAdapter
from .venteunique import VenteUniqueAdapter

# Order matters only for output readability. MediaMarkt is the most reliable;
# Conforama and Vente-unique are low-priority/breadth and sit last.
ADAPTERS: list[RetailerAdapter] = [
    MediaMarktAdapter(),
    HornbachAdapter(),
    HifiAdapter(),
    BatiselfAdapter(),
    ConforamaAdapter(),
    VenteUniqueAdapter(),
]

__all__ = ["Product", "RetailerAdapter", "ADAPTERS"]
