#!/usr/bin/env bash
# Remote watchdog: pull forward-test logs (Python runner + EA trades) from the
# VPS over SSH and regenerate the 4-chart dashboard. Read-only on the VPS --
# never touches MetaTrader. Runs on a schedule (Task Scheduler -> FTWatchdog).
#
# Usage: bash scripts/vps_watchdog.sh   (or just run scripts/vps_watchdog.bat)

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$ROOT/.env.vps" ]; then
  set -a; . "$ROOT/.env.vps"; set +a
fi
KEY="${VPS_SSH_KEY:-$HOME/.ssh/id_ed25519_vps}"
PORT="${VPS_PORT:-22}"
: "${VPS_HOST:?set VPS_HOST in .env.vps}"
: "${VPS_USER:?set VPS_USER in .env.vps}"
TARGET="$VPS_USER@$VPS_HOST"
DEST="$ROOT/logs/forward_vps"
mkdir -p "$DEST"

echo "== watchdog $(date '+%Y-%m-%d %H:%M:%S') =="

# 1. is the VPS trading stack up?
ssh -i "$KEY" -p "$PORT" -o BatchMode=yes "$TARGET" \
  'tasklist | findstr /i "terminal64 python" || echo NOTHING-RUNNING' 2>/dev/null

# 2. pull the deal/equity logs (written by scripts/forward_test.py on the VPS;
#    it logs EA deals too, magic 930/940)
scp -i "$KEY" -P "$PORT" -o BatchMode=yes \
  "$TARGET:C:/FTTest/logs/forward/*.csv" "$DEST/" 2>/dev/null \
  || echo "no CSVs pulled yet (runner may not have started on the VPS)"

# 3. regenerate charts + dashboard from the pulled data
python "$ROOT/scripts/forward_charts.py" "$DEST"
echo "== watchdog done =="
