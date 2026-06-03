#!/bin/bash
set -e

LOG_FILE="/mnt/user/data/shopee_execute/logs/pipeline.log"

mkdir -p /mnt/user/data/shopee_execute/logs

echo "=== Shopee Pipeline Container ==="
echo "Mode: MANUAL (no auto-execution)"
echo "Timezone: ${TZ:-UTC}"
echo "Log: $LOG_FILE"
echo ""
echo "Execute manually with:"
echo "  docker exec shopee-pipeline python main.py"
echo "  docker exec shopee-pipeline python main.py --step 1"
echo "  docker exec shopee-pipeline python main.py --dry-run"
echo ""

# Keep container alive — no cron
tail -f /dev/null
