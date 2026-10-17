#!/usr/bin/env bash
# Push FTTestEA + .set presets to the MT5 VPS over SSH -- fully headless,
# no window ever opens. This script only copies files and reads status.
# It NEVER launches, restarts, or closes MetaTrader.
#
# Usage:  bash scripts/vps_deploy.sh deploy|status
#
# Config in .env.vps at the repo root (git-ignored; copy .env.vps.example):
#   VPS_HOST=203.0.113.10
#   VPS_USER=vpsuser
#   VPS_PORT=22
#   VPS_SSH_KEY=~/.ssh/id_ed25519_vps     (optional)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE="$ROOT/vps/bundle"
ACTION="${1:-status}"

if [ -f "$ROOT/.env.vps" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env.vps"
  set +a
fi

KEY="${VPS_SSH_KEY:-$HOME/.ssh/id_ed25519_vps}"
PORT="${VPS_PORT:-22}"
: "${VPS_HOST:?set VPS_HOST in .env.vps (copy .env.vps.example)}"
: "${VPS_USER:?set VPS_USER in .env.vps (copy .env.vps.example)}"
TARGET="$VPS_USER@$VPS_HOST"

SSH=(ssh -i "$KEY" -p "$PORT" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
SCP=(scp -i "$KEY" -P "$PORT" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)

ps1() { "${SSH[@]}" "$TARGET" "powershell -NoProfile -Command \"$1\""; }

# MT5 data folder on the VPS, forward slashes so scp needs no quoting.
find_mql5() {
  "${SSH[@]}" "$TARGET" 'powershell -NoProfile -Command "(Get-ChildItem $env:APPDATA\MetaQuotes\Terminal\*\MQL5 | Sort-Object LastWriteTime | Select-Object -Last 1).FullName.Replace([char]92,[char]47)"' | tr -d '\r\n'
}

case "$ACTION" in
  deploy)
    [ -f "$BUNDLE/FTTestEA.ex5" ] || {
      echo "missing $BUNDLE/FTTestEA.ex5 - run scripts/make_presets.py and scripts/compile_ea.bat first"
      exit 1; }
    MQL5="$(find_mql5)"
    [ -n "$MQL5" ] || {
      echo "no MT5 data folder found on the VPS - install MT5 there first"
      exit 1; }
    echo "remote MQL5: $MQL5"
    ps1 "New-Item -ItemType Directory -Force -Path '$MQL5/Experts/FTTest','$MQL5/Presets' | Out-Null"
    "${SCP[@]}" "$BUNDLE/FTTestEA.ex5" "$BUNDLE/FTTestEA.mq5" "$TARGET:$MQL5/Experts/FTTest/"
    "${SCP[@]}" "$BUNDLE"/presets/*.set "$TARGET:$MQL5/Presets/"
    echo "deployed. next: bash scripts/vps_deploy.sh status"
    echo "then attach FTTestEA on the VPS (Navigator -> Refresh). MT5 is never"
    echo "restarted by this script."
    ;;
  status)
    echo "== MT5 process (0 rows = not running; start it manually on the VPS) =="
    ps1 "Get-Process terminal64 -ErrorAction SilentlyContinue | Select-Object Id,StartTime | Format-Table -AutoSize" || true
    MQL5="$(find_mql5)"
    echo "== deployed EA ($MQL5/Experts/FTTest) =="
    ps1 "Get-ChildItem '$MQL5/Experts/FTTest' -ErrorAction SilentlyContinue | Select-Object Name,Length,LastWriteTime | Format-Table -AutoSize" || true
    echo "== presets ($MQL5/Presets) =="
    ps1 "Get-ChildItem '$MQL5/Presets/FTTestEA*.set' -ErrorAction SilentlyContinue | Select-Object Name | Format-Table -AutoSize" || true
    ;;
  *)
    echo "usage: bash scripts/vps_deploy.sh deploy|status"
    exit 1 ;;
esac
