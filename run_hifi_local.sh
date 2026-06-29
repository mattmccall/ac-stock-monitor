#!/bin/bash
# Local HiFi.lu stock check.
#
# HiFi.lu geo/IP-blocks cloud runners, so it can't run on GitHub Actions. This
# script runs ONLY HiFi, from your (allowed) local network, against its own
# state file so it never collides with the state.json the Action commits.
#
# Used by the launchd agent (every 15 min) and runnable by hand.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

export DISABLE_RETAILERS="MediaMarkt.lu,Hornbach.lu,Conforama.lu"
export STATE_PATH="$DIR/hifi_state.json"
# The daily heartbeat is the cloud's job (full pipeline). Don't let the
# HiFi-only local agent send its own (misleading counts / duplicate).
export DISABLE_HEARTBEAT=1

# No `exec`: keep bash as the launchd "responsible" process so the Full Disk
# Access grant on /bin/bash also covers the Python child it spawns.
"$DIR/.venv/bin/python" monitor.py
