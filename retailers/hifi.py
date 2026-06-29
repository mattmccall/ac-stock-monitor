"""HiFi.lu adapter.

HiFi.lu sits behind Akamai bot protection: plain HTTP and bundled headless
Chromium both get a cached HTTP 500. Only a *real* Google Chrome (driven by
Playwright via channel="chrome", headless is fine) is served the real page —
so this adapter is LOCAL-ONLY (it needs Chrome installed and an allowed
network; it is disabled in CI via DISABLE_RETAILERS).

Each product card exposes: name (brand + model), price (€, possibly a struck
original + sale price), a spec line "Cooling capacity: N" (BTU), and a stock
string.

Stock logic (per project decision): we do NOT match a positive in-stock
string. A product is IN STOCK when the known out-of-stock markers are ABSENT
("out of stock" / "currently unavailable"). The raw status is logged for every
product on every run so a real restock is captured even if wording shifts.
"""

from __future__ import annotations

import re

from .base import Product, RetailerAdapter

CATEGORY_URL = (
    "https://www.hifi.lu/en/c/A30-B30100-C070/"
    "big-appliances-and-household/air-conditioning/mobile-air-conditioner"
)
BASE = "https://www.hifi.lu"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

OOS_MARKERS = ("out of stock", "currently unavailable")

# Browser-side extraction: one record per product card (href, img alt, text).
_EXTRACT_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  for (const a of document.querySelectorAll('a[href^="/en/p/"]')) {
    const href = a.getAttribute('href');
    if (seen.has(href)) continue;
    let el = a;
    for (let i = 0; i < 7 && el.parentElement; i++) {
      el = el.parentElement;
      if (el.innerText && /€/.test(el.innerText)) break;
    }
    const img = el.querySelector('img');
    seen.add(href);
    out.push({href, alt: img ? img.getAttribute('alt') : null, text: el.innerText});
  }
  return out;
}
"""

_PRICE_RE = re.compile(r"€\s*([\d.,]+)")
_BTU_RE = re.compile(r"Cooling capacity:\s*(\d{3,6})", re.I)
_REVIEWS_RE = re.compile(r"^\d+\s+reviews?$", re.I)
_PCT_RE = re.compile(r"^-?\d+%$")
_BADGES = {"sales", "new", "promo", "soldes", "sale"}


def _card_name(text: str, alt: str | None) -> str:
    """First meaningful line of the card (brand + model)."""
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or len(line) <= 4:
            continue
        low = line.lower()
        if (low in _BADGES or low.startswith("€") or low.startswith("this product")
                or _REVIEWS_RE.match(line) or _PCT_RE.match(line)):
            continue
        return line
    return (alt or "").strip() or "Mobile air conditioner"


def _card_price(text: str) -> float | None:
    """Lowest € amount on the card = the actual (possibly sale) price."""
    prices = []
    for raw in _PRICE_RE.findall(text or ""):
        raw = raw.strip().rstrip(".")
        if "," in raw and "." in raw:
            raw = (raw.replace(".", "").replace(",", ".")
                   if raw.rfind(",") > raw.rfind(".") else raw.replace(",", ""))
        elif "," in raw:
            raw = raw.replace(",", ".")
        try:
            prices.append(float(raw))
        except ValueError:
            continue
    return min(prices) if prices else None


def _card_stock(text: str) -> bool:
    low = (text or "").lower()
    return not any(m in low for m in OOS_MARKERS)


def _article_id(href: str) -> str:
    m = re.search(r"/en/p/([^-/]+)", href)
    return m.group(1) if m else href.rstrip("/").split("/")[-1]


def parse_cards(cards: list[dict]) -> list[Product]:
    """Pure parse of browser-extracted card records into Products."""
    products: list[Product] = []
    for c in cards:
        href = c.get("href") or ""
        if "/en/p/" not in href:
            continue
        text = c.get("text") or ""
        name = _card_name(text, c.get("alt"))
        price = _card_price(text)
        btu_m = _BTU_RE.search(text)
        btu = int(btu_m.group(1)) if btu_m else None
        in_stock = _card_stock(text)
        url = BASE + href if href.startswith("/") else href
        raw_status = ("in stock" if in_stock
                      else next(m for m in OOS_MARKERS if m in text.lower()))
        print(f"  [HiFi] {name[:48]:48} | raw_status={raw_status:20} "
              f"-> in_stock={in_stock} | btu={btu} | €{price}")
        products.append(
            Product(
                retailer=HifiAdapter.name,
                name=name,
                url=url,
                in_stock=in_stock,
                price=price,
                btu=btu,
                specs=f"{btu} BTU" if btu else None,
                product_id=_article_id(href),
            )
        )
    return products


def _fetch_cards() -> list[dict]:
    """Drive real Chrome (Playwright) to get past Akamai; return card records."""
    from playwright.sync_api import sync_playwright

    from ._browser import run_in_thread

    def _do() -> list[dict]:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_context(
                    locale="en-US", user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 900},
                ).new_page()
                page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                return page.evaluate(_EXTRACT_JS)
            finally:
                browser.close()

    # Run in a fresh thread so Playwright's sync API has a clean event loop
    # even when another adapter (Hornbach) already used it this process.
    return run_in_thread(_do)


class HifiAdapter(RetailerAdapter):
    name = "HiFi.lu"

    def fetch(self) -> list[Product]:
        try:
            cards = _fetch_cards()
        except Exception as exc:
            # Chrome missing (e.g. CI), Akamai block, or network error.
            print(f"  [HiFi] fetch failed ({exc.__class__.__name__}: {exc}); "
                  f"skipping. Needs Google Chrome + an allowed network.")
            return []
        return parse_cards(cards)
