# LastLift API + embedded FalkorDB in one container (Render free: 512 MB / 0.1 CPU).
# FalkorDB server 4.22.0 is built on redis:8.10.2; we copy redis-server + the module into a
# Python slim image instead of layering Python onto the FalkorDB image (which purges Python/perl).
FROM falkordb/falkordb-server:v4.22.0 AS falkordb

FROM python:3.14-slim-trixie
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 OMP_NUM_THREADS=1 PORT=10000 \
    APP_ENV=production FALKORDB_HOST=127.0.0.1 FALKORDB_PORT=6379 GRAPH_PREFIX=ll
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 tini \
 && rm -rf /var/lib/apt/lists/*
COPY --from=falkordb /usr/local/bin/redis-server /usr/local/bin/redis-cli /usr/local/bin/
COPY --from=falkordb /var/lib/falkordb/bin/falkordb.so /opt/falkordb/falkordb.so
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install -r requirements.txt
COPY lastlift/ lastlift/
COPY deploy/ deploy/
COPY data/ data/
RUN python -m compileall -q lastlift && sh deploy/bake_seed.sh
EXPOSE 10000
ENTRYPOINT ["tini", "-g", "--"]
CMD ["sh", "/app/deploy/start.sh"]
