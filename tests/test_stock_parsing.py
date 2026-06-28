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
from retailers.batiself import parse_category as bati_parse, resolve_stock  # noqa: E402
from retailers.venteunique import in_scope as vu_in_scope, parse_product as vu_parse  # noqa: E402
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


# --- Batiself: WooCommerce tiles + per-page stock/store/delivery ----------

def _bati_tile(pid, slug, name, price):
    return (
        f'data-product-id="{pid}">'
        f'<a href="https://batiself.lu/produit/{slug}/" class="product-card__media"></a>'
        f'<a href="https://batiself.lu/produit/{slug}/" class="product-card__title">{name}</a>'
        f'<span class="woocommerce-Price-amount"><bdi>{price}&nbsp;'
        f'<span class="woocommerce-Price-currencySymbol">€</span></bdi></span>'
    )


def test_batiself_tile_parse_and_dehumidifier_exclusion():
    html = (
        _bati_tile("111", "climatiseur-mobile-x", "Climatiseur mobile X 9000 BTU", "299,00")
        + _bati_tile("222", "deshumidificateur-y", "Déshumidificateur Y 20L", "149,00")
    )
    prods = bati_parse(html)
    assert len(prods) == 1                         # dehumidifier excluded
    assert prods[0].name == "Climatiseur mobile X 9000 BTU"
    assert prods[0].price == 299.00
    assert prods[0].product_id == "111"
    assert prods[0].url.endswith("/produit/climatiseur-mobile-x/")


def _resolve(html):
    p = Product("Batiself.lu", "Climatiseur mobile X", "u", in_stock=False)
    resolve_stock(p, html)
    return p


def test_batiself_in_stock_requires_store_and_no_oos():
    # store with stock>0 and no OOS string + delivery line -> in stock
    p = _resolve('data-stocks=\'{"131":{"name":"Alzingen","stock":3},'
                 '"903":{"name":"Schifflange","stock":0}}\' '
                 'Délais de livraison: 7 jours')
    assert p.in_stock is True
    assert p.delivery_days == 7


def test_batiself_out_when_oos_string_present():
    p = _resolve('data-stocks=\'{"131":{"name":"Alzingen","stock":3}}\' '
                 "Ce produit n'est pas disponible pour l'instant")
    assert p.in_stock is False     # OOS string overrides store stock


def test_batiself_out_when_no_store_has_stock():
    p = _resolve('data-stocks=\'{"131":{"name":"Alzingen","stock":0},'
                 '"903":{"name":"Schifflange","stock":0}}\'')
    assert p.in_stock is False     # no store in stock -> not purchase-worthy


# --- Vente-unique: scope filter + marketplace product parse ---------------

def test_vu_scope_keeps_portables():
    for name in [
        "Climatiseur Inverter Comfee CF 9000 BTU avec Wi-Fi, Réversible, Déshumidificateur",
        "Climatiseur portable IceCove pour tentes d'extérieur",
        "Olimpia Splendid Peler 4T Climatiseur portatif",
        "Climatiseur mobile 2 en 1 fonction déshumidificateur - CODILAM",
        "Olimpia Splendid Unico Easy S2 HP Climatiseur portatif",
    ]:
        assert vu_in_scope(name) is True, name


def test_vu_scope_drops_mural_split_brands_and_evap():
    for name in [
        "Climatiseur Mural Baxi Sidera 9000 Btu",
        "Daikin Bluevolution Inverter Emura Black III 18000 BTU",
        "Daikin Siesta Pro Era 18000 Btu",
        "Climatiseur Inverter Candy Pura 18000 Btu",
        "Climatiseur Inverter Aermec SPG 9000 BTU",
        "Climatiseur Inverter Aufit Freedom F4 9000 Btu",
        "Climatiseur split à fixer au mur",
        "Rafraîchisseur d'air évaporatif",
        "Déshumidificateur 20L",                       # pure dehumidifier
    ]:
        assert vu_in_scope(name) is False, name


def test_vu_scope_keeps_portasplit_and_split_mobile():
    assert vu_in_scope("Olimpia Splendid PortaSplit climatiseur") is True
    assert vu_in_scope("Climatiseur split mobile monobloc") is True


def _vu_page(price_jsonld, availability, extra=""):
    return (
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"X","offers":{"@type":"Offer","price":"'
        + price_jsonld + '","availability":"https://schema.org/' + availability
        + '"}}</script>' + extra
    )


def test_vu_product_uses_main_price_not_recommended():
    # main product (climatisation category) = 239.31; a recommended glass = 3.08
    extra = ('"category":"Climatisation, Ventilation","variant":"Blanc","price":239.31,'
             '"category":"Verre","variant":"Beige","price":3.08,')
    price, in_stock, days, raw = vu_parse(_vu_page("279.99", "OutOfStock", extra))
    assert price == 239.31          # not 3.08, not the 279.99 list price
    assert in_stock is False        # schema OutOfStock


def test_vu_product_in_stock_and_delivery_days():
    extra = '<span>Expédié sous 12 jours</span>'
    price, in_stock, days, raw = vu_parse(_vu_page("412.78", "InStock", extra))
    assert in_stock is True
    assert days == 12


def test_dehumidifier_nuance_in_core_filter():
    # AC with dehumidify *function* is kept; a pure dehumidifier is dropped.
    assert filters.is_mobile_ac(
        "Climatiseur Inverter Comfee CF 9000 BTU Déshumidificateur") is True
    assert filters.is_mobile_ac("TRISTAR DH-5424 Déshumidificateur") is False


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
