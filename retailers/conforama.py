"""Conforama.lu adapter (Odoo e-commerce).

Plain HTTP. The product grid (theme class `tp-product-item`) gives name, price
and URL reliably, but NOT stock — Odoo doesn't render availability on the grid
here. So for products that look like an AC we fetch the product page and read
stock there.

Stock logic mirrors HiFi's decision: we key on the ABSENCE of known
out-of-stock markers rather than a positive in-stock string, and log the raw
status for every checked product so we can refine once a real unit appears.

Conforama is explicitly low-priority / low-yield (often no AC units listed).
Everything here is wrapped so its quirks can't block the other retailers.
"""

from __future__ import annotations

import html as ihtml
import re

import requests

from .base import Product, RetailerAdapter

BASE = "https://www.conforama.lu"
CATEGORY_URL = (
    "https://www.conforama.lu/shop/category/"
    "petit-electromenager-confort-de-la-maison-traitement-de-l-air-139"
)
SEARCH_URL = "https://www.conforama.lu/shop?search=climatiseur"
TIMEOUT = 25
MAX_STOCK_CHECKS = 12  # cap product-page fetches per run

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

# Markers that mean OUT of stock on a product page (FR Odoo + English fallback).
OOS_MARKERS = [
    "rupture de stock",
    "épuisé",
    "produit épuisé",
    "indisponible",
    "out of stock",
    "schema.org/outofstock",
]

# Cheap, local "is this maybe an AC?" gate to limit product-page fetches.
_AC_HINT = re.compile(r"climatiseur|air\s*condition|btu", re.I)

_CARD_RE = re.compile(r'data-product-template-id="(\d+)"(.*?)</form>', re.S)
_NAME_RE = re.compile(r'itemprop="website_name"[^>]*title="([^"]+)"')
_HREF_RE = re.compile(r'itemprop="url"[^>]*href="(/shop/[^"]+)"')
_HREF_FALLBACK_RE = re.compile(r'href="(/shop/[^"?]+-\d+)(?:\?[^"]*)?"')
_PRICE_ITEMPROP_RE = re.compile(r'itemprop="price"[^>]*>\s*([\d.]+)')
_PRICE_CUR_RE = re.compile(r'oe_currency_value">\s*([\d.,]+)')


def _parse_price(card: str) -> float | None:
    m = _PRICE_ITEMPROP_RE.search(card)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    m = _PRICE_CUR_RE.search(card)
    if m:
        try:
            return float(m.group(1).replace(".", "").replace(",", "."))
        except ValueError:
            pass
    return None


def parse_grid(html: str) -> list[Product]:
    products: list[Product] = []
    for pid, card in _CARD_RE.findall(html):
        name_m = _NAME_RE.search(card)
        name = ihtml.unescape(name_m.group(1)).strip() if name_m else None
        href_m = _HREF_RE.search(card) or _HREF_FALLBACK_RE.search(card)
        if not name or not href_m:
            continue
        url = BASE + href_m.group(1)
        products.append(
            Product(
                retailer=ConforamaAdapter.name,
                name=name,
                url=url,
                in_stock=False,          # provisional; resolved per product page
                price=_parse_price(card),
                product_id=pid,
            )
        )
    return products


def _check_stock(session: requests.Session, product: Product) -> None:
    """Fetch the product page and set in_stock from absence of OOS markers."""
    try:
        resp = session.get(product.url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as exc:
        print(f"  [Conforama] stock check failed for {product.name[:40]}: {exc}")
        product.in_stock = False
        return
    low = resp.text.lower()
    hit = next((m for m in OOS_MARKERS if m in low), None)
    product.in_stock = hit is None
    raw = f"OOS marker '{hit}'" if hit else "(no OOS marker)"
    print(f"  [Conforama] {product.name[:45]:45} | raw_status={raw} "
          f"-> in_stock={product.in_stock}")


class ConforamaAdapter(RetailerAdapter):
    name = "Conforama.lu"

    def fetch(self) -> list[Product]:
        session = requests.Session()
        by_id: dict[str, Product] = {}
        for url in (CATEGORY_URL, SEARCH_URL):
            try:
                resp = session.get(url, headers=HEADERS, timeout=TIMEOUT)
                if resp.status_code != 200:
                    print(f"  [Conforama] HTTP {resp.status_code} for {url}")
                    continue
                for p in parse_grid(resp.text):
                    by_id.setdefault(p.product_id or p.url, p)
            except requests.RequestException as exc:
                print(f"  [Conforama] fetch failed for {url}: {exc}")

        products = list(by_id.values())
        # Only resolve stock for likely ACs, capped to avoid hammering.
        candidates = [p for p in products if _AC_HINT.search(p.name)][:MAX_STOCK_CHECKS]
        for p in candidates:
            _check_stock(session, p)
        return products
