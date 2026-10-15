#!/bin/sh
# Container boot: FalkorDB loads the baked RDB, then the API starts on $PORT.
set -e
sh /app/deploy/redis.sh &
i=0; until redis-cli -p 6379 ping >/dev/null 2>&1; do i=$((i+1)); [ $i -gt 100 ] && echo "redis did not start" && exit 1; sleep 0.2; done
if [ -f /app/lastlift/seed.py ]; then python -m lastlift.seed --if-missing || echo "seed check failed; serving degraded"; fi
exec python -m uvicorn lastlift.main:app --host 0.0.0.0 --port "${PORT:-10000}" --workers 1 --no-access-log
