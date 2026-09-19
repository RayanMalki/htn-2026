#!/usr/bin/env bash
set -euo pipefail
# Usage: scripts/deploy.sh root@VM_IP. Requires an existing Ubuntu VM with Docker Compose.
target="${1:?Provide user@host}"
if [[ ! "$target" =~ ^[a-zA-Z0-9_.-]+@[a-zA-Z0-9.-]+$ ]]; then
  echo 'Expected user@host (no shell expressions)' >&2
  exit 1
fi
test -f .env || { echo 'Create and configure .env first' >&2; exit 1; }
ssh "$target" 'mkdir -p /opt/hypecheck'
rsync -az --exclude '.git' --exclude '.venv' --exclude '.env' --exclude node_modules --exclude dist \
  --exclude data --exclude artifacts --exclude __pycache__ --exclude test-results ./ "$target:/opt/hypecheck/"
scp .env "$target:/opt/hypecheck/.env"
ssh "$target" 'cd /opt/hypecheck && chmod 600 .env && docker compose up -d --build && docker compose exec -T api python -m app.cli setup-elastic && docker compose exec -T api python -m app.cli preflight'
