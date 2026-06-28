#!/usr/bin/env python3
"""AC stock monitor — core loop.

Fetch every retailer, filter to real mobile ACs within budget, diff against the
committed state, and send a Telegram alert for anything that just came into
stock. Designed to run once per invocation (GitHub Actions cron) but is equally
runnable locally with a .env file.

Usage:
  python monitor.py            # fetch, alert, persist state
  python monitor.py --dry-run  # fetch + show what would alert; no send, no write
  python monitor.py --list     # just print the current filtered AC list
"""

from __future__ import annotations

import argparse
import sys

import filters
import notifier
import state as state_mod
from retailers import ADAPTERS, Product

# Load .env if present (no-op in CI where vars come from Secrets).
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def collect() -> tuple[list[Product], list[str]]:
    """Run every adapter; collect products and any per-adapter errors."""
    products: list[Product] = []
    errors: list[str] = []
    for adapter in ADAPTERS:
        try:
            found = adapter.fetch()
            products.extend(found)
            print(f"  {adapter.name}: {len(found)} product(s) listed")
        except Exception as exc:  # one broken retailer must not kill the run
            errors.append(f"{adapter.name}: {exc}")
            print(f"  {adapter.name}: ERROR {exc}", file=sys.stderr)
    return products, errors


def print_table(products: list[Product]) -> None:
    if not products:
        print("  (none)")
        return
    for p in sorted(products, key=lambda x: (x.retailer, x.name)):
        flag = "IN " if p.in_stock else "OUT"
        rating = f" · {p.rating}" if p.rating else ""
        print(f"  [{flag}] {p.price_str():>9} · {p.retailer:12} · {p.name}{rating}")


def smoke_test() -> int:
    """Send a single, clearly-labelled test alert to verify Telegram delivery.

    Does not scrape any retailer and never writes state — purely a check that
    the bot token / chat id work end-to-end (e.g. from GitHub Actions).
    """
    if not notifier.is_configured():
        print("Telegram not configured (set TELEGRAM_BOT_TOKEN / "
              "TELEGRAM_CHAT_ID).", file=sys.stderr)
        return 1
    probe = Product(
        retailer="SMOKE TEST",
        name="🧪 TEST — ignore. Telegram delivery check, not a real product.",
        url="https://github.com/mattmccall/ac-stock-monitor",
        in_stock=True,
        price=0.0,
    )
    notifier.send(probe)
    print("Smoke-test alert sent.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Mobile AC stock monitor")
    parser.add_argument("--dry-run", action="store_true",
                        help="don't send Telegram or write state")
    parser.add_argument("--list", action="store_true",
                        help="just print the current filtered AC list and exit")
    parser.add_argument("--smoke-test", action="store_true",
                        help="send one labelled test Telegram alert and exit "
                             "(no scraping, no state changes)")
    args = parser.parse_args()

    if args.smoke_test:
        return smoke_test()

    print("Fetching retailers...")
    products, errors = collect()

    ac_products = filters.filter_products(products)
    print(f"\nMatched {len(ac_products)} mobile AC(s) ≤ €{filters.MAX_PRICE:.0f} "
          f"(of {len(products)} listed):")
    print_table(ac_products)

    if args.list:
        return 0

    saved = state_mod.load_state()
    first_run = len(saved) == 0
    transitions, new_state = state_mod.diff(ac_products, saved)

    if first_run:
        print("\nFirst run: recording baseline, no alerts will be sent.")
    print(f"\nNewly in stock: {len(transitions)}")
    for t in transitions:
        print(f"  -> {t.product.name} ({t.product.price_str()}, {t.product.retailer})")

    if args.dry_run:
        print("\n[dry-run] not sending Telegram, not writing state.")
        return 1 if errors else 0

    # Send notifications.
    if transitions:
        if notifier.is_configured():
            for t in transitions:
                try:
                    notifier.send(t.product)
                    print(f"  sent: {t.product.name}")
                except Exception as exc:
                    errors.append(f"telegram send: {exc}")
                    print(f"  telegram ERROR: {exc}", file=sys.stderr)
        else:
            print("  Telegram not configured; skipping sends.", file=sys.stderr)

    # Persist state (even on first run, to establish the baseline).
    state_mod.save_state(new_state)
    print("\nState saved.")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
