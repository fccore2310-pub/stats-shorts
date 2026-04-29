#!/bin/zsh
# Desinstala los launchd jobs de TikTok auto-upload.
# Usar cuando TikTok API esté conectada y schedule_batch.py gestione todo.

AGENTS_DIR="$HOME/Library/LaunchAgents"

for plist in com.fccore.tiktok.morning.plist com.fccore.tiktok.evening.plist com.fccore.analytics.plist; do
    if [[ -f "$AGENTS_DIR/$plist" ]]; then
        launchctl unload "$AGENTS_DIR/$plist" 2>/dev/null || true
        rm "$AGENTS_DIR/$plist"
        echo "✓ $plist desinstalado"
    fi
done
