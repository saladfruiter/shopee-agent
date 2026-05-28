#!/bin/bash
set -e

CRON_SCHEDULE="${CRON_SCHEDULE:-0 8 * * *}"
LOG_FILE="/mnt/user/data/shopee-agent/logs/pipeline.log"

mkdir -p /mnt/user/data/shopee-agent/logs

echo "=== Shopee Pipeline Container ==="
echo "Cron schedule: $CRON_SCHEDULE"
echo "Timezone: ${TZ:-UTC}"
echo "Log: $LOG_FILE"
echo ""

# Exporta env vars para o cron poder usar
printenv | grep -E '^(SHOPEE_|RETRY_|TZ|PATH|PYTHONPATH)' > /app/.cronenv

# Monta a crontab
echo "$CRON_SCHEDULE root cd /app && . /app/.cronenv && python main.py >> $LOG_FILE 2>&1" > /etc/cron.d/shopee-pipeline
echo "" >> /etc/cron.d/shopee-pipeline
chmod 0644 /etc/cron.d/shopee-pipeline
crontab /etc/cron.d/shopee-pipeline

echo "[$(date)] Container started. Waiting for cron or manual trigger..."
echo "[$(date)] Manual: docker exec shopee-pipeline python main.py"
echo ""

# Inicia cron em foreground (mantém container vivo)
cron -f
