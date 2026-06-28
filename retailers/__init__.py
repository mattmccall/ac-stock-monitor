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

# Order matters only for output readability. MediaMarkt is the most reliable;
# Conforama is low-priority/low-yield and sits last.
ADAPTERS: list[RetailerAdapter] = [
    MediaMarktAdapter(),
    HornbachAdapter(),
    HifiAdapter(),
    BatiselfAdapter(),
    ConforamaAdapter(),
]

__all__ = ["Product", "RetailerAdapter", "ADAPTERS"]
