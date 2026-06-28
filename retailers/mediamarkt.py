"""MediaMarkt.lu adapter.

MediaMarkt runs on Shopify, which exposes a clean JSON feed for any collection
at `<collection>/products.json`. Each product has variants with an `available`
boolean — the reliable in-stock signal. We paginate until Shopify returns an
empty `products` array.
"""

from __future__ import annotations

import requests

from .base import Product, RetailerAdapter

COLLECTION_URL = "https://mediamarkt.lu/collections/climatiseur-mobile/products.json"
PRODUCT_URL = "https://mediamarkt.lu/products/{handle}"
MAX_PAGES = 20  # safety stop; the category is tiny
TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


class MediaMarktAdapter(RetailerAdapter):
    name = "MediaMarkt.lu"

    def fetch(self) -> list[Product]:
        products: list[Product] = []
        session = requests.Session()
        for page in range(1, MAX_PAGES + 1):
            resp = session.get(
                COLLECTION_URL,
                params={"page": page},
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            batch = resp.json().get("products", [])
            if not batch:
                break  # no more pages
            for raw in batch:
                products.append(self._to_product(raw))
        return products

    @staticmethod
    def _to_product(raw: dict) -> Product:
        variants = raw.get("variants", []) or []
        in_stock = any(v.get("available") for v in variants)

        # Cheapest variant price; Shopify gives price as a string in EUR.
        prices = []
        for v in variants:
            try:
                prices.append(float(v["price"]))
            except (KeyError, TypeError, ValueError):
                continue
        price = min(prices) if prices else None

        handle = raw.get("handle", "")
        return Product(
            retailer=MediaMarktAdapter.name,
            name=raw.get("title", "").strip(),
            url=PRODUCT_URL.format(handle=handle),
            in_stock=in_stock,
            price=price,
            rating=None,  # not exposed in the Shopify feed
            product_id=str(raw.get("id")) if raw.get("id") is not None else None,
        )
