#!/usr/bin/env bash
set -euo pipefail

# Start the complete stack from either a local .env file or exported environment
# variables. Secrets stay outside Git; Compose receives them at runtime.
compose=(docker compose)
if [[ -n "${COMPOSE_BIN:-}" ]]; then
  compose=("$COMPOSE_BIN" compose)
fi

"${compose[@]}" up -d --build

# Provision the configured Elastic index when credentials are available. This is
# safe to repeat and lets a teammate run one command after pulling main.
if "${compose[@]}" exec -T api sh -c 'test -n "$ELASTICSEARCH_URL" && test -n "$ELASTICSEARCH_API_KEY"'; then
  "${compose[@]}" exec -T api python -m app.cli setup-elastic
fi

# Always report readiness. In mock/local mode this clearly identifies missing
# external services; in live mode it prevents a false successful startup.
"${compose[@]}" exec -T api python -m app.cli preflight
echo "HypeCheck is running at ${DOMAIN:-http://localhost}"
