#!/bin/sh
# Image build step: start FalkorDB, load the committed snapshot (once M2 lands), save an RDB.
set -e
sh /app/deploy/redis.sh --daemonize yes
i=0; until redis-cli -p 6379 ping >/dev/null 2>&1; do i=$((i+1)); [ $i -gt 50 ] && echo "redis did not start" && exit 1; sleep 0.2; done
redis-cli -p 6379 MODULE LIST
if [ -f /app/lastlift/seed.py ]; then python -m lastlift.seed --all --verify; fi
redis-cli -p 6379 SAVE
redis-cli -p 6379 shutdown nosave || true
test -s /data/dump.rdb
echo "baked /data/dump.rdb"
