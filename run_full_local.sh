#!/bin/bash
# Full local stock check — ALL retailers (incl. HiFi, which is cloud-blocked).
#
# Shares the committed state.json + heartbeat.json with the GitHub Action via
# git, so the two paths never send duplicate alerts: whichever run sees a
# stock flip first records it, and the other then sees it already recorded.
#
# Flow: sync latest state from origin -> run the full pipeline -> commit & push
# state/heartbeat if they changed (retry on a race with the cloud). Driven by
# the launchd agent every 15 min while the Mac is awake; the cloud remains the
# always-on backup for when it's asleep.
set -uo pipefail
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 1
GIT="git -c user.name=ac-monitor-local -c user.email=local@ac-stock-monitor"

# 1. Sync latest committed state (public repo: fetch needs no auth). Never get
#    stuck mid-rebase — abort cleanly and proceed on the local copy if needed.
if ! $GIT pull --rebase --autostash -q origin main 2>/dev/null; then
  $GIT rebase --abort 2>/dev/null || true
fi

# 2. Run the full pipeline (no DISABLE_RETAILERS -> all six retailers).
#    Don't let a non-zero exit (a retailer error) abort the commit/push below.
"$DIR/.venv/bin/python" monitor.py || true

# 3. Persist shared state if it changed, retrying once against a cloud push.
if [[ -n "$($GIT status --porcelain state.json heartbeat.json)" ]]; then
  $GIT add state.json heartbeat.json
  $GIT commit -q -m "chore: update stock state (local) [skip ci]"
  for _ in 1 2 3; do
    $GIT push -q origin main && break
    $GIT pull --rebase --autostash -q origin main 2>/dev/null || $GIT rebase --abort 2>/dev/null || true
  done
fi
