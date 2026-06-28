"""Quality filter: keep only real mobile (hose-type) air conditioners.

The category on both retailers is tiny and noisy — it mixes in window seals,
fans, smart-AC controllers, dehumidifiers and other accessories. Rather than
hard-filtering on BTU/rating (too aggressive for such a small list), we:

  * keep anything that looks like a mobile AC by name, and
  * drop obvious accessories / wrong product types, and
  * enforce a price ceiling.

Both keyword lists are intentionally at the top of the file so they are easy to
eyeball and tweak. The alert text still carries name + price + rating so the
final judgement call is yours.
"""

from __future__ import annotations

import re

from retailers.base import Product

MAX_PRICE = 650.0  # EUR, inclusive

# Soft BTU floor: units below this are FLAGGED as underpowered in the alert
# text, not excluded. Only applied when a retailer exposes structured BTU
# (HiFi); for the others we eyeball capacity via the name.
BTU_SOFT_FLOOR = 8000

# A product must match at least one of these to be considered an AC at all.
INCLUDE_KEYWORDS = [
    "climatiseur",       # FR: air conditioner
    "climatisation mobile",
    "air conditioner",
    "portable ac",
    "pinguino",          # DeLonghi mobile AC line
    "btu",               # spec that effectively only mobile ACs advertise here
]

# If any of these appear, it's an accessory / wrong type — exclude it even if it
# also matched an include keyword (exclusions win).
EXCLUDE_KEYWORDS = [
    "joint",             # window/door seal
    "étanchéité",        # sealing kit
    "etancheite",
    "hot air stop",      # seal product line
    "ventilateur",       # fan
    "fan",
    "fixation",          # mounting bracket
    "support",
    "contrôleur",        # smart-AC controller
    "controleur",
    "sensibo",           # smart-AC controller brand
    "boîtier",           # connection box
    "boitier",
    "télécommande seule",
    "filtre",            # replacement filter
    "roulette",          # casters
    "aspirateur",        # vacuum (mis-categorised on MediaMarkt)
]

# "déshumidificateur" is handled conditionally, not as a blanket exclude: many
# real ACs advertise a dehumidify *function* in the name (e.g. Comfee, CODILAM
# at Vente-unique). Only a *pure* dehumidifier (no AC keyword) is excluded.
_DEHUMID = ("déshumidificateur", "deshumidificateur")

# Evaporative / tent / outdoor "coolers" masquerading as portable ACs. A real
# monobloc vents hot air out a window via a hose, so it can't work in a tent or
# outdoors — that framing is the tell. Word boundaries keep "tente" from
# matching "attente"/"contente"; "sans évacuation" (no exhaust) is matched but
# plain "évacuation" (a hose-vented AC HAS one) is NOT. Applies to every
# retailer as a general safeguard.
_EVAP_RE = re.compile(
    r"\btentes?\b|\btents?\b|ext[ée]rieur|rafra[îi]chisseur|"
    r"[ée]vaporatif|evaporative|sans\s+[ée]vacuation", re.I)


def is_mobile_ac(name: str) -> bool:
    low = name.lower()
    if any(bad in low for bad in EXCLUDE_KEYWORDS):
        return False
    if _EVAP_RE.search(name):
        return False  # evaporative / tent / outdoor cooler, not a real AC
    # HiFi writes "air-conditioner" (hyphen); normalise so it matches the
    # "air conditioner" keyword. Excludes are checked on the raw name above.
    norm = low.replace("-", " ")
    is_ac = any(good in norm for good in INCLUDE_KEYWORDS)
    if any(d in low for d in _DEHUMID) and not is_ac:
        return False  # pure dehumidifier
    return is_ac


def is_underpowered(product: Product) -> bool:
    """True if we have a structured BTU and it's below the soft floor.

    Does NOT exclude the product — it's surfaced as a warning in the alert so
    you can judge whether the capacity suits your room.
    """
    return product.btu is not None and product.btu < BTU_SOFT_FLOOR


def passes(product: Product) -> bool:
    """True if the product is a real mobile AC within the price ceiling."""
    if not is_mobile_ac(product.name):
        return False
    if product.price is None:
        # Can't verify the price ceiling -> don't alert (avoids surprises).
        return False
    return product.price <= MAX_PRICE


def filter_products(products: list[Product]) -> list[Product]:
    return [p for p in products if passes(p)]
