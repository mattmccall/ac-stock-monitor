"""HiFi.lu adapter.

Plain HTTP, no JS. Each product tile exposes: name, price ("€398.00"), a spec
line "Cooling capacity: 9000" (BTU), and a stock string. Product links are
absolute under /en/p/.

IMPORTANT — stock logic (per project decision):
We do NOT match a positive "in stock" string, because no in-stock example was
available to confirm its exact markup. Instead a product is considered IN STOCK
when the known out-of-stock marker ("Out of stock") is ABSENT from its tile.
The raw stock text we extracted is logged for every product on every run, so
the first real restock is captured even if the positive markup differs from a
guess — and we can refine from the logged output.

NOTE: hifi.lu geo/IP-blocks some networks with a cached HTTP 500 (it was
unreachable from the dev sandbox). The adapter degrades gracefully: on any
non-200 or parse failure it logs and returns [] so the other retailers keep
working. Tile-markup details below are therefore best-effort until validated
against real logged output.
"""

from __future__ import annotations

import html as ihtml
import re

import requests

from .base import Product, RetailerAdapter

CATEGORY_URL = (
    "https://www.hifi.lu/en/c/A30-B30100-C070/"
    "big-appliances-and-household/air-conditioning/mobile-air-conditioner"
)
BASE = "https://www.hifi.lu"
TIMEOUT = 25
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

OOS_MARKER = "out of stock"

_LINK_RE = re.compile(r'href="(?:https?://www\.hifi\.lu)?(/en/p/[^"#?]+)"')
_PRICE_RE = re.compile(r"€\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)")
_BTU_RE = re.compile(r"Cooling capacity:\s*(\d{3,6})", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_ATTR_RE = re.compile(r'title="([^"]+)"')


def _clean(s: str) -> str:
    return ihtml.unescape(_TAG_RE.sub(" ", s)).strip()


def _parse_price(seg: str) -> float | None:
    m = _PRICE_RE.search(seg)
    if not m:
        return None
    raw = m.group(1)
    # European formats: "398.00" / "398,00" / "1.398,00" / "1,398.00"
    if "," in raw and "." in raw:
        # last separator is the decimal one
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _slug_to_name(path: str) -> str:
    tail = path.rstrip("/").split("/")[-1]
    tail = re.sub(r"-?\d+$", "", tail)  # drop trailing id if present
    return tail.replace("-", " ").strip().title() or path


def _segment_tiles(html: str) -> list[tuple[str, str]]:
    """Return (product_path, tile_html) for each product on the page.

    We don't know HiFi's exact tile container, so we segment the page by
    product-link positions: a tile spans from one product's first link to the
    next product's first link. Consecutive links to the same product (image +
    title) are collapsed.
    """
    points: list[tuple[str, int]] = []
    for m in _LINK_RE.finditer(html):
        path = m.group(1)
        if points and points[-1][0] == path:
            continue
        points.append((path, m.start()))
    tiles: list[tuple[str, str]] = []
    for i, (path, pos) in enumerate(points):
        end = points[i + 1][1] if i + 1 < len(points) else len(html)
        tiles.append((path, html[pos:end]))
    return tiles


def _tile_name(seg: str, path: str) -> str:
    m = _TITLE_ATTR_RE.search(seg)
    if m and len(m.group(1)) > 3:
        return ihtml.unescape(m.group(1)).strip()
    # first non-trivial anchor/text content
    txt = _clean(seg)
    first = txt.split("  ")[0].strip()
    if len(first) > 3:
        return first
    return _slug_to_name(path)


def parse_tiles_html(html: str) -> list[Product]:
    products: list[Product] = []
    seen: set[str] = set()
    for path, seg in _segment_tiles(html):
        if path in seen:
            continue
        seen.add(path)
        low = seg.lower()
        raw_status = "Out of stock" if OOS_MARKER in low else "(no OOS marker)"
        in_stock = OOS_MARKER not in low
        name = _tile_name(seg, path)
        btu_m = _BTU_RE.search(seg)
        btu = int(btu_m.group(1)) if btu_m else None
        url = BASE + path
        # Per-product raw status logging (every run) for later refinement.
        print(f"  [HiFi] {name[:50]:50} | raw_status={raw_status:18} "
              f"-> in_stock={in_stock} | btu={btu}")
        products.append(
            Product(
                retailer=HifiAdapter.name,
                name=name,
                url=url,
                in_stock=in_stock,
                price=_parse_price(seg),
                btu=btu,
                specs=f"{btu} BTU" if btu else None,
                product_id=path.rstrip("/").split("/")[-1],
            )
        )
    return products


class HifiAdapter(RetailerAdapter):
    name = "HiFi.lu"

    def fetch(self) -> list[Product]:
        try:
            resp = requests.get(CATEGORY_URL, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as exc:
            print(f"  [HiFi] request failed: {exc}")
            return []
        if resp.status_code != 200:
            # hifi.lu serves a cached 500 to blocked networks — log and skip.
            print(f"  [HiFi] HTTP {resp.status_code} (site may be geo/IP-blocking "
                  f"this runner); skipping.")
            return []
        return parse_tiles_html(resp.text)
