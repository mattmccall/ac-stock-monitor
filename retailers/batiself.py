"""Batiself.lu adapter (WooCommerce).

Plain HTTP, no JS. The category page lists product tiles (custom theme on top
of WooCommerce); stock, per-store availability and delivery lead time live on
each product page, not the grid — so for every AC candidate we fetch the
product page.

Per-product page we read three things:
  1. The out-of-stock string "Ce produit n'est pas disponible pour l'instant"
     (its presence = OUT).
  2. Per-store stock. The page carries a structured `data-stocks` JSON
     ({store_id: {name, stock}}) — the robust source; we also fall back to the
     visible "...is-available">En stock" lines.
  3. The delivery lead time "Délais de livraison: N jours" -> int, captured on
     the Product and surfaced in the alert (feeds the ≤10-day judgement).

A unit counts as purchase-worthy IN STOCK only when the out-of-stock string is
ABSENT *and* at least one store has stock. Raw status is logged per product.

The category mixes in dehumidifiers; those are excluded by name. Note: the
climatiseur-mobile category may be empty ("Bientôt en rayon") — that yields 0
products, not an error. Everything is isolated so its quirks can't block the
other retailers.
"""

from __future__ import annotations

import html as ihtml
import json
import re

import requests

from .base import Product, RetailerAdapter

BASE = "https://batiself.lu"
CATEGORY_URL = (
    "https://batiself.lu/categorie-produit/"
    "traitement-de-lair/climatisation/climatiseur-mobile/"
)
TIMEOUT = 25
MAX_STOCK_CHECKS = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

# OOS string (presence => out of stock). Tolerant of straight/curly apostrophes.
_OOS_RE = re.compile(r"n['’]est pas disponible pour l['’]instant", re.I)
_DELIVERY_RE = re.compile(r"D[ée]lais?\s+de\s+livraison\s*:?\s*(\d+)\s*jours?", re.I)
_DATA_STOCKS_RE = re.compile(r"data-stocks='([^']+)'")
_STORE_AVAIL_RE = re.compile(r'is-available">\s*En stock', re.I)

# Dehumidifiers to exclude from the category (per spec).
_DEHUMID_RE = re.compile(r"d[ée]shumidificateur", re.I)

# --- category tile parsing --------------------------------------------------

_TILE_RE = re.compile(r'data-product-id="(\d+)"(.*?)(?=data-product-id="|\Z)', re.S)
_LINK_RE = re.compile(r'href="(https://batiself\.lu/produit/[^"?]+)"')
_NAME_ANCHOR_RE = re.compile(
    r'href="https://batiself\.lu/produit/[^"]+"[^>]*>\s*([^<]{4,}?)\s*<')
_ARIA_NAME_RE = re.compile(r'aria-label="Ajouter\s+(.+?)\s+aux favoris"', re.I)
_PRICE_RE = re.compile(r'woocommerce-Price-amount[^>]*>\s*(?:<bdi>)?\s*([\d.,]+)')


def _parse_euro(raw: str) -> float | None:
    raw = raw.strip().replace("\xa0", "").rstrip(".")
    if "," in raw and "." in raw:
        raw = (raw.replace(".", "").replace(",", ".")
               if raw.rfind(",") > raw.rfind(".") else raw.replace(",", ""))
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _tile_name(chunk: str) -> str | None:
    # Prefer the natural-cased title-anchor text; fall back to the aria-label.
    for m in _NAME_ANCHOR_RE.finditer(chunk):
        txt = ihtml.unescape(m.group(1)).strip()
        if txt and not txt.lower().startswith("ajouter"):
            return txt
    m = _ARIA_NAME_RE.search(chunk)
    return ihtml.unescape(m.group(1)).strip() if m else None


def parse_category(html: str) -> list[Product]:
    """Parse category tiles into Products (stock resolved later per page)."""
    products: list[Product] = []
    for pid, chunk in _TILE_RE.findall(html):
        link = _LINK_RE.search(chunk)
        name = _tile_name(chunk)
        if not link or not name:
            continue
        if _DEHUMID_RE.search(name):
            continue  # exclude dehumidifiers per spec
        price_m = _PRICE_RE.search(chunk)
        products.append(
            Product(
                retailer=BatiselfAdapter.name,
                name=name,
                url=link.group(1),
                in_stock=False,  # provisional; resolved from the product page
                price=_parse_euro(price_m.group(1)) if price_m else None,
                product_id=pid,
            )
        )
    return products


# --- product-page stock parsing ---------------------------------------------

def _store_stock(html: str) -> tuple[bool, str]:
    """Return (any_store_in_stock, human summary) using data-stocks JSON,
    falling back to the visible 'En stock' lines."""
    m = _DATA_STOCKS_RE.search(html)
    if m:
        try:
            stocks = json.loads(ihtml.unescape(m.group(1)))
            in_any = any(int(s.get("stock", 0)) > 0 for s in stocks.values())
            summary = ", ".join(
                f"{s.get('name')}:{s.get('stock')}" for s in stocks.values()) or "none"
            return in_any, summary
        except (ValueError, AttributeError):
            pass
    n = len(_STORE_AVAIL_RE.findall(html))
    return n > 0, f"{n} store(s) 'En stock' (text)"


def resolve_stock(product: Product, html: str) -> None:
    """Set in_stock + delivery_days on `product` from its product-page HTML."""
    oos = bool(_OOS_RE.search(html))
    has_store, summary = _store_stock(html)
    product.in_stock = (not oos) and has_store
    dm = _DELIVERY_RE.search(html)
    product.delivery_days = int(dm.group(1)) if dm else None
    raw = f"oos_string={oos} | stores=[{summary}] | delivery_days={product.delivery_days}"
    print(f"  [Batiself] {product.name[:42]:42} | {raw} -> in_stock={product.in_stock}")


class BatiselfAdapter(RetailerAdapter):
    name = "Batiself.lu"

    def fetch(self) -> list[Product]:
        session = requests.Session()
        try:
            resp = session.get(CATEGORY_URL, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as exc:
            print(f"  [Batiself] category fetch failed: {exc}")
            return []
        if resp.status_code != 200:
            print(f"  [Batiself] category HTTP {resp.status_code}")
            return []

        products = parse_category(resp.text)
        for p in products[:MAX_STOCK_CHECKS]:
            try:
                pr = session.get(p.url, headers=HEADERS, timeout=TIMEOUT)
                if pr.status_code == 200:
                    resolve_stock(p, pr.text)
                else:
                    print(f"  [Batiself] product HTTP {pr.status_code}: {p.url}")
            except requests.RequestException as exc:
                print(f"  [Batiself] product fetch failed for {p.name[:40]}: {exc}")
        return products
