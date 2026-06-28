"""Vente-unique.lu adapter (marketplace).

Plain HTTP. The category page embeds a JSON-LD ItemList (name + /p/ URL per
product); price and stock are NOT on the grid, so for each in-scope candidate
we fetch the product page and read its JSON-LD Product (price + availability)
plus any delivery lead time.

CRITICAL scope filter (this catalog mixes installed wall-split units in with
portable monoblocs): keep only portable/monobloc ACs. Drop names containing
"mural" or "split" (unless "split mobile"/"portasplit"), the known mural-unit
brands (Daikin/Emura/Siesta/Baxi Sidera/Aermec/Candy Pura/Aufit), evaporative
coolers ("rafraîchisseur"/"sans évacuation") and pure dehumidifiers. In-scope
examples: Comfee CF monobloc, Olimpia Splendid (Unico Easy, Peler), IceCove
portable, CODILAM.

It's a marketplace (partner sellers, often shipped from France), so we capture
the delivery lead time where shown — it feeds the ≤10-day judgement. Lower
priority / breadth; fully isolated so its quirks can't block other adapters.
"""

from __future__ import annotations

import json
import re

import requests

from .base import Product, RetailerAdapter

BASE = "https://www.vente-unique.lu"
CATEGORY_URL = "https://www.vente-unique.lu/c/climatiseur-mobile"
TIMEOUT = 25
MAX_STOCK_CHECKS = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

_LDJSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)

# Scope exclusions (installed wall units / wrong type) for this catalog.
_EXCLUDE_TERMS = (
    "mural", "daikin", "emura", "siesta", "baxi sidera", "aermec",
    "candy pura", "aufit", "rafraîchisseur", "rafraichisseur",
    "sans évacuation", "sans evacuation",
)
# Tent / outdoor framing => almost certainly an evaporative cooler or spot
# cooler, not a hose-vented monobloc (you can't vent hot air out of a tent).
# Word boundaries so "tente" doesn't match inside "attente"/"contente" etc.
_EVAP_NAME_RE = re.compile(r"\btentes?\b|\btents?\b|ext[ée]rieur", re.I)

_BTU_RE = re.compile(r"(\d{3,5})\s*BTU", re.I)
_DELIVERY_RE = re.compile(
    r"(?:exp[ée]di[ée]|livr[ée]e?|livraison)\s+(?:sous|en|entre[^.\d]*?)\s*"
    r"(\d+)(?:\s*(?:à|-|et)\s*(\d+))?\s*jours?", re.I)
# The viewed product's dataLayer entry (category "Climatisation, Ventilation")
# carries the actual selling price. Recommended products on the page have other
# categories, so anchoring on the category avoids grabbing their prices.
_MAIN_PRICE_RE = re.compile(
    r'category"\s*:\s*"[^"]*(?:limatis|entilation)[^"]*"[^}]{0,80}?'
    r'"price"\s*:\s*"?([\d.]+)', re.I)


def in_scope(name: str) -> bool:
    """True if the name is a portable/monobloc AC we care about."""
    low = name.lower()
    if any(t in low for t in _EXCLUDE_TERMS):
        return False
    if _EVAP_NAME_RE.search(name):
        return False  # tent/outdoor cooler, not a real monobloc AC
    if "split" in low and not ("split mobile" in low or "portasplit" in low):
        return False
    # pure dehumidifier (dehumidify only, not an AC)
    if ("shumidificateur" in low) and "climatiseur" not in low:
        return False
    return True


def parse_listing(html: str) -> list[tuple[str, str]]:
    """Return (name, url) for each product from the category JSON-LD ItemList."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for block in _LDJSON_RE.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if node.get("@type") != "ItemList":
                continue
            for it in node.get("itemListElement", []):
                name = (it.get("name") or "").strip()
                url = it.get("url") or ""
                if name and "/p/" in url and url not in seen:
                    seen.add(url)
                    out.append((name, url))
    return out


def _product_jsonld(html: str) -> dict | None:
    for block in _LDJSON_RE.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if "Product" in str(node.get("@type")):
                return node
    return None


def parse_product(html: str) -> tuple[float | None, bool, int | None, str]:
    """Return (price, in_stock, delivery_days, raw_status) from a product page."""
    node = _product_jsonld(html)
    list_price = None
    availability = ""
    if node:
        offers = node.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        try:
            list_price = float(offers.get("price"))
        except (TypeError, ValueError):
            pass
        availability = str(offers.get("availability") or "")
    # Prefer the viewed product's actual (often discounted) price from the
    # dataLayer; fall back to the JSON-LD list price.
    price = list_price
    m = _MAIN_PRICE_RE.search(html)
    if m:
        try:
            price = float(m.group(1))
        except ValueError:
            pass

    low = html.lower()
    if availability:
        in_stock = "instock" in availability.lower()
    else:  # fallback to visible labels
        in_stock = ("en stock" in low and not any(
            x in low for x in ("rupture", "épuisé", "epuisé", "indisponible",
                               "victime de son succès")))

    dm = _DELIVERY_RE.search(html)
    delivery_days = int(dm.group(2) or dm.group(1)) if dm else None

    avail_label = availability.rsplit("/", 1)[-1] if availability else "?"
    raw = f"availability={avail_label} | delivery_days={delivery_days}"
    return price, in_stock, delivery_days, raw


class VenteUniqueAdapter(RetailerAdapter):
    name = "Vente-unique.lu"

    def fetch(self) -> list[Product]:
        session = requests.Session()
        try:
            resp = session.get(CATEGORY_URL, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as exc:
            print(f"  [Vente-unique] category fetch failed: {exc}")
            return []
        if resp.status_code != 200:
            print(f"  [Vente-unique] category HTTP {resp.status_code}")
            return []

        candidates = [(n, u) for (n, u) in parse_listing(resp.text) if in_scope(n)]
        products: list[Product] = []
        for name, url in candidates[:MAX_STOCK_CHECKS]:
            pid = url.rstrip("/").split("/p/")[-1][:60]
            try:
                pr = session.get(url, headers=HEADERS, timeout=TIMEOUT)
                if pr.status_code != 200:
                    print(f"  [Vente-unique] product HTTP {pr.status_code}: {url}")
                    continue
                price, in_stock, delivery_days, raw = parse_product(pr.text)
            except requests.RequestException as exc:
                print(f"  [Vente-unique] product fetch failed for {name[:40]}: {exc}")
                continue
            btu_m = _BTU_RE.search(pr.text)
            btu = int(btu_m.group(1)) if btu_m else None
            print(f"  [Vente-unique] {name[:46]:46} | {raw} | btu={btu} | €{price} "
                  f"-> in_stock={in_stock}")
            products.append(
                Product(
                    retailer=self.name, name=name, url=url, in_stock=in_stock,
                    price=price, delivery_days=delivery_days, btu=btu,
                    specs=f"{btu} BTU" if btu else None, product_id=pid,
                )
            )
        return products
