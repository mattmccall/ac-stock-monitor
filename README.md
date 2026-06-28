# ac-stock-monitor

Watches **mobile (hose-type) air conditioners** across two Luxembourg retailers
and pings you on **Telegram** the moment a matching unit comes into stock.
Runs on **GitHub Actions** every 10 minutes; also runnable locally.

## Retailers

| Retailer | Source | How stock is read |
|----------|--------|-------------------|
| **MediaMarkt.lu** | Shopify `products.json` feed | `variants[].available` boolean (reliable) |
| **Hornbach.lu** | Category page (JS-rendered, bot-walled) | French text per tile: *"indisponible / non disponible en ligne"* = out, *"Disponible en ligne"* = in. Plain HTTP first, Playwright headless fallback. |
| **HiFi.lu** | Category page via **real Google Chrome** (Playwright `channel="chrome"`, headless) | Behind Akamai bot protection: plain HTTP and bundled Chromium get a cached 500; only real Chrome is served the page. Cards parsed from the DOM: name, lowest € (sale-aware) price, structured BTU (`Cooling capacity: N` → int), and **in stock = absence of "out of stock" / "currently unavailable"** (no positive string assumed). Raw status logged per product. ⚠️ **Local-only**: needs Google Chrome installed + an allowed network. Disabled in CI; runs via the local launchd agent (see below). |
| **Conforama.lu** | Odoo grid + `?search=climatiseur` (plain HTTP) | Grid gives name/price/URL; stock read from the **product page** (absence of OOS markers). Low-priority/low-yield, fully isolated. |
| **Batiself.lu** | WooCommerce category + product pages (plain HTTP) | Tiles give name/price/URL (dehumidifiers excluded by name). Per **product page**: OOS string `"Ce produit n'est pas disponible pour l'instant"` (presence = out), per-store stock from a `data-stocks` JSON, and delivery lead time `"Délais de livraison: N jours"` → captured + shown in the alert. **In stock only if** the OOS string is absent **and** ≥1 store has stock. (Category may be "coming soon"/empty → 0 products.) |
| **Vente-unique.lu** | JSON-LD `ItemList` category + product pages (plain HTTP) | Marketplace. Tiles give name/`/p/` URL. **Scope filter** keeps only portable/monobloc units — drops "mural"/"split" (unless split-mobile/portasplit), the mural-unit brands (Daikin/Emura/Siesta/Baxi Sidera/Aermec/Candy Pura/Aufit), evaporative coolers and pure dehumidifiers. Per **product page** (JSON-LD `Product`): price (viewed-product price, sale-aware, ignoring recommended items), `availability` (schema.org InStock/OutOfStock), and delivery lead time where shown → `delivery_days`. Lower-priority breadth; isolated. |

> The core filter treats "déshumidificateur" conditionally: a real AC that
> merely advertises a dehumidify *function* (Comfee, CODILAM) is kept; only a
> *pure* dehumidifier (no AC keyword) is excluded.

The soft BTU floor (`BTU_SOFT_FLOOR`, default 8000) does not exclude units —
sub-floor ACs are **flagged "underpowered"** in the alert. Only HiFi exposes
structured BTU today; for the others, capacity is judged from the name.

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

# HiFi.lu only works from an allowed (Luxembourg) network. It runs by default
# locally; in CI it's skipped via DISABLE_RETAILERS (set in the workflow).
# To skip a retailer in any run:
DISABLE_RETAILERS="HiFi.lu,Conforama.lu" python monitor.py --dry-run
```

### Running HiFi.lu locally (it can't run in CI)

From an allowed network, check **only** HiFi against its **own** state file
(`STATE_PATH`) so it never collides with the `state.json` the Action commits:

```bash
DISABLE_RETAILERS="MediaMarkt.lu,Hornbach.lu,Conforama.lu" \
STATE_PATH=hifi_state.json \
python monitor.py
```

`*_state.json` is gitignored. Alerts go to the same Telegram chat.

Requires **Google Chrome** installed (HiFi is fetched via real Chrome to get
past Akamai bot protection).

#### Automated locally with launchd (every 15 min)

`run_hifi_local.sh` + a launchd agent run the HiFi check every 15 minutes while
the Mac is awake. Because the project lives under `~/Documents` (a macOS
privacy-protected folder), the launchd-spawned process needs **Full Disk
Access** granted to `/bin/bash` (System Settings → Privacy & Security → Full
Disk Access). The agent runs `/bin/bash run_hifi_local.sh` (no `exec`, so bash
stays the responsible process and its grant covers the Python + Chrome it
launches).

```bash
# install / reload the agent
launchctl bootout  gui/$(id -u)/com.mattmccall.ac-hifi-monitor 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.mattmccall.ac-hifi-monitor.plist
launchctl kickstart -k gui/$(id -u)/com.mattmccall.ac-hifi-monitor   # run now
# logs: hifi_local.log
```
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
