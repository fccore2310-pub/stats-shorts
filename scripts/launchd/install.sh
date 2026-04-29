#!/bin/zsh
# Instala los launchd jobs para auto-upload a TikTok 10:00 y 18:00.
# Para desinstalar: ./uninstall.sh

set -e

AGENTS_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS_DIR"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

for plist in com.fccore.tiktok.morning.plist com.fccore.tiktok.evening.plist com.fccore.analytics.plist; do
    cp "$SCRIPT_DIR/$plist" "$AGENTS_DIR/$plist"
    launchctl unload "$AGENTS_DIR/$plist" 2>/dev/null || true
    launchctl load "$AGENTS_DIR/$plist"
    echo "✓ $plist instalado"
done

echo ""
echo "Jobs programados:"
launchctl list | grep fccore || echo "  (ninguno encontrado — revisa logs)"
echo ""
echo "Logs en: data/logs/launchd_*.log"
