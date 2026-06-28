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

from retailers.base import Product

MAX_PRICE = 450.0  # EUR, inclusive

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
    "déshumidificateur", # dehumidifier
    "dehumidificateur",
    "filtre",            # replacement filter
    "roulette",          # casters
    "aspirateur",        # vacuum (mis-categorised on MediaMarkt)
]


def is_mobile_ac(name: str) -> bool:
    low = name.lower()
    if any(bad in low for bad in EXCLUDE_KEYWORDS):
        return False
    return any(good in low for good in INCLUDE_KEYWORDS)


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
