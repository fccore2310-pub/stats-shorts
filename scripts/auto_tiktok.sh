#!/bin/zsh
# Auto-publicación diaria a TikTok via Selenium
# Ejecutado por launchd a las 10:00 y 18:00 (hora Madrid).
# Cuando TikTok API esté conectada (post-warm-up), desinstalar con:
#   launchctl unload ~/Library/LaunchAgents/com.fccore.tiktok.*.plist

set -e

export PATH="/opt/homebrew/bin:/Users/fatimaabajo/Library/Python/3.9/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

cd "$(dirname "$0")/.."

LOG_DIR="data/logs"
mkdir -p "$LOG_DIR"

STAMP=$(date +"%Y%m%d_%H%M%S")
LOG="$LOG_DIR/auto_tiktok_${STAMP}.log"

{
    echo "=== $(date) === Auto TikTok publish ==="

    # 1. Generar post fresco
    echo ">> Generando post..."
    POST_OUTPUT=$(python3 scripts/library.py post 2>&1)
    echo "$POST_OUTPUT"

    # 2. Extraer el post_id del output
    POST_ID=$(echo "$POST_OUTPUT" | grep -oE "Post ready: [a-z0-9_]+" | awk '{print $3}')

    if [[ -z "$POST_ID" ]]; then
        echo "ERROR: no se pudo extraer POST_ID"
        exit 1
    fi
    echo ">> Post generado: $POST_ID"

    # 3. Subir a TikTok via Selenium
    echo ">> Subiendo a TikTok..."
    python3 scripts/library.py tiktok-post "$POST_ID"

    echo "=== $(date) === Fin ==="
} >> "$LOG" 2>&1
