"""Regression tests for Hornbach stock-text parsing and the AC filter.

Run with pytest, or directly:  python tests/test_stock_parsing.py

These lock in the tricky case where "Non disponible en ligne" must read as
OUT even though it contains the substring "disponible en ligne".
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from retailers.hornbach import _parse_stock, parse_tiles_html  # noqa: E402
import filters  # noqa: E402
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
