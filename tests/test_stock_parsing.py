"""Regression tests for Hornbach stock-text parsing and the AC filter.

Run with pytest, or directly:  python tests/test_stock_parsing.py

These lock in the tricky case where "Non disponible en ligne" must read as
OUT even though it contains the substring "disponible en ligne".
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from retailers.hornbach import _parse_stock, parse_tiles_html  # noqa: E402
from retailers.hifi import parse_cards as hifi_parse_cards  # noqa: E402
from retailers.conforama import parse_grid as conf_parse  # noqa: E402
import filters  # noqa: E402
import notifier  # noqa: E402
from retailers.base import Product  # noqa: E402


# Exact phrasings observed live on hornbach.lu (June 2026).
def test_indisponible_is_out():
    assert _parse_stock("indisponible en ligne actuellement") is False


def test_non_disponible_is_out():
    # The bug: contains "disponible en ligne" as a substring but is OUT.
    assert _parse_stock("Non disponible en ligne") is False


def test_disponible_is_in():
    assert _parse_stock("Disponible en ligne") is True


def test_store_reservation_text_is_ignored():
    # Online OUT even though only reservation wording is negative-free elsewhere.
    chunk = "Non disponible en ligne. Réservation non disponible"
    assert _parse_stock(chunk) is False


def test_unknown_text_is_none():
    assert _parse_stock("blah blah pas de mention") is None


def test_filter_keeps_mobile_ac_under_ceiling():
    p = Product("Hornbach.lu", "Climatiseur mobile Hantech 9000 BTU", "u",
                in_stock=True, price=169.0)
    assert filters.passes(p) is True


def test_filter_drops_over_ceiling():
    p = Product("Hornbach.lu", "Climatiseur EcoFlow Wave 3", "u",
                in_stock=True, price=899.0)
    assert filters.passes(p) is False


def test_filter_drops_accessories():
    for name in [
        "Joint de fenêtre Hot Air Stop",
        "Ventilateur de sol BCIWM75CM",
        "Contrôleur Sensibo Sky Smart AC",
        "Boîtier de connexion du contrôleur Sensibo blanc",
        "MIELE Guard L1 AllFloor Flex Aspirateur avec sac",
    ]:
        p = Product("X", name, "u", in_stock=True, price=99.0)
        assert filters.passes(p) is False, name


def test_parse_tiles_handles_both_negations():
    # Minimal synthetic tile HTML exercising both OUT phrasings + one IN.
    html = (
        'x data-testid="article-card" '
        '<a href="/fr/p/a/1/"></a>'
        '<span data-testid="article-title">Climatiseur A</span>'
        'indisponible en ligne actuellement'
        'data-testid="article-card" '
        '<a href="/fr/p/b/2/"></a>'
        '<span data-testid="article-title">Climatiseur B</span>'
        'Non disponible en ligne'
        'data-testid="article-card" '
        '<a href="/fr/p/c/3/"></a>'
        '<span data-testid="article-title">Climatiseur C</span>'
        'Disponible en ligne'
    )
    prods = parse_tiles_html(html)
    by_name = {p.name: p.in_stock for p in prods}
    assert by_name == {
        "Climatiseur A": False,
        "Climatiseur B": False,
        "Climatiseur C": True,
    }


# --- HiFi: structured BTU + absence-based stock --------------------------
# Card records mirror what the browser extractor returns (href, alt, text).

_HIFI_CARDS = [
    {  # in stock (no OOS marker), single price
        "href": "/en/p/B8010304-mobile-air-conditioner-exm9b2",
        "alt": "Mobile air-conditioner EXM9b2",
        "text": "ESSENTIEL-B Mobile air-conditioner EXM9b2\n0 reviews\n€398.00\n"
                "Cooling capacity: 9000 | Noise level: 65",
    },
    {  # out of stock + on sale (must take the LOWER price)
        "href": "/en/p/13000532-domo-mobile-air-conditioner-do10161",
        "alt": "Mobile air conditioner DO10161 - 7000 BTU",
        "text": "Sales\nDOMO Mobile air conditioner DO10161 - 7000 BTU\n0 reviews\n"
                "€349.00\n€199.00\n-43%\nThis product is currently unavailable\n"
                "out of stock\nCooling capacity: 7000",
    },
]


def test_hifi_parses_btu_as_int_and_name():
    prods = {p.product_id: p for p in hifi_parse_cards(_HIFI_CARDS)}
    p = prods["B8010304"]
    assert p.btu == 9000 and isinstance(p.btu, int)
    assert p.price == 398.00
    assert p.name == "ESSENTIEL-B Mobile air-conditioner EXM9b2"  # not a badge


def test_hifi_stock_is_absence_of_oos_markers():
    prods = {p.product_id: p for p in hifi_parse_cards(_HIFI_CARDS)}
    assert prods["B8010304"].in_stock is True    # no OOS marker
    assert prods["13000532"].in_stock is False   # "out of stock"/"unavailable"


def test_hifi_uses_sale_price():
    prods = {p.product_id: p for p in hifi_parse_cards(_HIFI_CARDS)}
    assert prods["13000532"].price == 199.00     # lower of 349 / 199


# --- soft BTU floor -------------------------------------------------------

def test_underpowered_flagged_not_excluded():
    weak = Product("HiFi.lu", "Mobile air conditioner", "u",
                   in_stock=True, price=199.0, btu=7000)
    assert filters.is_underpowered(weak) is True
    assert filters.passes(weak) is True     # flagged, NOT excluded


def test_adequate_btu_not_flagged():
    ok = Product("HiFi.lu", "Mobile air conditioner", "u",
                 in_stock=True, price=398.0, btu=9000)
    assert filters.is_underpowered(ok) is False


def test_no_btu_not_flagged():
    p = Product("Hornbach.lu", "Climatiseur mobile Hantech", "u",
                in_stock=True, price=169.0)
    assert filters.is_underpowered(p) is False


def test_alert_text_shows_btu_and_underpowered_warning():
    weak = Product("HiFi.lu", "Mobile AC", "https://x", in_stock=True,
                   price=199.0, btu=7000)
    msg = notifier.format_message(weak)
    assert "7000 BTU" in msg and "underpowered" in msg


# --- Conforama grid parse -------------------------------------------------

def test_conforama_grid_parse():
    card = (
        '<div data-product-template-id="290662"><form>'
        '<a itemprop="url" href="/shop/0500598-climatiseur-mobile-x-290662?category=139">i</a>'
        '<a itemprop="website_name" title="Climatiseur mobile X" href="/shop/x">'
        'Climatiseur mobile X</a>'
        '<span itemprop="price">299.0</span></form></div>'
    )
    prods = conf_parse(card)
    assert len(prods) == 1
    assert prods[0].name == "Climatiseur mobile X"
    assert prods[0].price == 299.0
    assert prods[0].url.startswith("https://www.conforama.lu/shop/")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    print(f"\n{'ALL PASSED' if not failures else f'{failures} FAILED'}")
    sys.exit(1 if failures else 0)
