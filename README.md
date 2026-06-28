# ac-stock-monitor

Watches **mobile (hose-type) air conditioners** across two Luxembourg retailers
and pings you on **Telegram** the moment a matching unit comes into stock.
Runs on **GitHub Actions** every 10 minutes; also runnable locally.

## Retailers

| Retailer | Source | How stock is read |
|----------|--------|-------------------|
| **MediaMarkt.lu** | Shopify `products.json` feed | `variants[].available` boolean (reliable) |
| **Hornbach.lu** | Category page (JS-rendered, bot-walled) | French text per tile: *"indisponible en ligne actuellement"* = out, *"Disponible en ligne"* = in. Plain HTTP first, Playwright headless fallback. |

## What gets alerted

Only products that are **real mobile ACs** (window seals, fans, controllers,
dehumidifiers and other accessories are excluded by name) **and priced ≤ €450**.
The filter is deliberately permissive — the alert carries name, price, BTU/room
size (from the title) and rating so you make the final call. Tune the keyword
lists and price ceiling at the top of [`filters.py`](filters.py).

You're notified **only when a product flips out-of-stock → in-stock**. The first
run records a silent baseline so you aren't spammed for the existing catalogue.
Availability is tracked in [`state.json`](state.json), committed back by the
Action each run.

## Architecture

```
monitor.py            # core loop: fetch → filter → diff → notify → persist
filters.py            # "is this a real mobile AC ≤ €450?"
state.py              # JSON state load/save + out→in diff
notifier.py           # Telegram sendMessage
retailers/
  base.py             # Product dataclass + RetailerAdapter interface
  mediamarkt.py       # Shopify JSON adapter
  hornbach.py         # Playwright/HTML adapter
  __init__.py         # ADAPTERS registry
```

**Adding a retailer** = write `retailers/<name>.py` with a `RetailerAdapter`
subclass returning `Product`s, then add it to `ADAPTERS` in
[`retailers/__init__.py`](retailers/__init__.py). The core loop, filter, state
and notifier are untouched.

## Local usage

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

cp .env.example .env        # fill in your bot token + chat id

python monitor.py --list    # just show the current matched AC list
python monitor.py --dry-run # fetch + show what would alert; no send, no write
python monitor.py           # real run: alert + persist state
```

## Telegram setup

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the **token**.
2. Send any message to your new bot, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy
   `result[].message.chat.id` — that's your **chat id**.

## GitHub Actions

Add two repository secrets (Settings → Secrets and variables → Actions):

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

The workflow ([.github/workflows/monitor.yml](.github/workflows/monitor.yml))
runs every 10 minutes and on manual dispatch, installs deps + Chromium, runs the
monitor, and commits the updated `state.json`. It needs `contents: write`
permission (already set in the workflow) so it can push state back.
