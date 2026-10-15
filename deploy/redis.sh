#!/bin/sh
# Shared redis-server launcher for bake_seed.sh and start.sh. Localhost only; no persistence forks.
mkdir -p /data
# shellcheck disable=SC2046
exec redis-server --bind 127.0.0.1 --port 6379 --protected-mode yes --dir /data \
  --save "" --appendonly no --maxmemory 256mb --maxmemory-policy noeviction \
  --loadmodule /opt/falkordb/falkordb.so $(cat /app/deploy/falkordb.args) "$@"
