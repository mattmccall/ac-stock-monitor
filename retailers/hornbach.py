"""Hornbach.lu adapter.

The category page is partly JS-rendered and sits behind a "Client Challenge"
bot wall, so a plain HTTP fetch usually returns only the challenge shell. We
therefore:

  1. Try a plain HTTP GET first (cheap). If the rendered product tiles happen to
     be present in the raw HTML, parse them directly — no browser needed.
  2. Otherwise fall back to Playwright headless Chromium, which clears the
     challenge, then parse the rendered HTML.

Both paths feed the *same* `parse_tiles_html()` so there is a single source of
truth for how a tile is read. Stock is taken from the French text on each tile
("indisponible en ligne" = out, "disponible en ligne" = in), exactly as shown
to a shopper.
"""

from __future__ import annotations

import html as ihtml
import re

import requests

from .base import Product, RetailerAdapter

CATEGORY_URL = (
    "https://www.hornbach.lu/fr/c/"
    "chauffage-climatisation-aeration/climatiseurs/S10590/"
)
TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# --- tile parsing -----------------------------------------------------------

_PRICE_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*€")
_TAG_RE = re.compile(r"<[^>]+>")
_RATING_RE = re.compile(r"Moyenne des avis\s*:\s*([\d,]+)\s*de\s*5", re.I)
_RATING_COUNT_RE = re.compile(r"(\d+)\s*Avis", re.I)
_HREF_RE = re.compile(r'href="((?:/fr/p/|https://www\.hornbach\.lu/fr/p/)[^"]+)"')
_TITLE_RE = re.compile(r'data-testid="article-title"[^>]*>\s*([^<]+)')


def _parse_price(chunk: str) -> float | None:
    m = _PRICE_RE.search(chunk)
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))


def _parse_title(chunk: str) -> str | None:
    m = _TITLE_RE.search(chunk)
    if not m:
        return None
    return ihtml.unescape(m.group(1)).strip() or None


def _parse_rating(chunk: str) -> str | None:
    m = _RATING_RE.search(chunk)
    if not m:
        return None
    value = m.group(1).replace(",", ".")
    cnt = _RATING_COUNT_RE.search(chunk)
    return f"{value}/5 ({cnt.group(1)} avis)" if cnt else f"{value}/5"


def _parse_stock(chunk: str) -> bool | None:
    """Read the online-availability text on a tile.

    Hornbach uses several phrasings, and crucially TWO negative forms:
      * "indisponible en ligne actuellement"  -> OUT
      * "Non disponible en ligne"             -> OUT
      * "Disponible en ligne"                 -> IN
    Note that "non disponible en ligne" *contains* the substring
    "disponible en ligne", so negatives MUST be checked first.
    Only the online signal counts; store-reservation text is ignored.
    """
    low = chunk.lower()
    if re.search(r"(?:indisponible|non\s+disponible)\s+en\s+ligne", low):
        return False
    if re.search(r"disponible\s+en\s+ligne", low):
        return True
    return None


def _article_id(url: str) -> str | None:
    m = re.search(r"/p/.+?/(\d+)/?$", url)
    return m.group(1) if m else None


def parse_tiles_html(html: str) -> list[Product]:
    """Parse rendered Hornbach category HTML into Products.

    Tiles are delimited by the `data-testid="article-card"` marker; everything
    between two markers is one tile. Robust to minor markup changes because it
    only relies on stable test ids and the visible French stock text.
    """
    products: list[Product] = []
    for chunk in html.split('data-testid="article-card"')[1:]:
        href = _HREF_RE.search(chunk)
        if not href:
            continue
        url = href.group(1)
        if url.startswith("/"):
            url = "https://www.hornbach.lu" + url
        stock = _parse_stock(chunk)
        if stock is None:
            # No recognisable stock text -> skip rather than guess.
            continue
        name = _parse_title(chunk)
        if not name:
            continue
        products.append(
            Product(
                retailer=HornbachAdapter.name,
                name=name,
                url=url,
                in_stock=stock,
                price=_parse_price(chunk),
                rating=_parse_rating(chunk),
                product_id=_article_id(url),
            )
        )
    return products


def has_tiles(html: str) -> bool:
    return 'data-testid="article-card"' in html


# --- fetch strategies -------------------------------------------------------


def _fetch_raw() -> str | None:
    try:
        resp = requests.get(CATEGORY_URL, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return None
    if resp.ok and has_tiles(resp.text):
        return resp.text
    return None


def _fetch_rendered() -> str:
    # Imported lazily so the plain-HTTP path doesn't require Playwright.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            locale="fr-FR",
            user_agent=HEADERS["User-Agent"],
        )
        page = ctx.new_page()
        page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector('[data-testid="article-card"]', timeout=30000)
        except Exception:
            pass  # parse whatever rendered; may legitimately be empty
        page.wait_for_timeout(2000)
        html = page.content()
        browser.close()
        return html


class HornbachAdapter(RetailerAdapter):
    name = "Hornbach.lu"

    def fetch(self) -> list[Product]:
        html = _fetch_raw()
        if html is None:
            html = _fetch_rendered()
        return parse_tiles_html(html)
