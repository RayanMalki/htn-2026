# Vultr deployment

## VM setup

Create an Ubuntu 24.04 VM with 4 vCPU and 8 GB RAM in a nearby region, using your SSH key. Allow inbound TCP 22 only from your team IPs and TCP 80/443 publicly; UDP 443 is optional for HTTP/3. Do not expose PostgreSQL, Redis, or the API port.

Install Docker Engine with the official Ubuntu installation instructions: https://docs.docker.com/engine/install/ubuntu/. Install the Compose plugin. The deployment script assumes Docker and Compose already work and `/opt/hypecheck` is writable by the SSH user.

Point a DNS A record to the VM's IPv4 address. Configure `.env` locally with `DOMAIN`, Elastic credentials, model keys, Sentry DSNs, and a random hex `POSTGRES_PASSWORD` (the init script generates a URL-safe value). Set `SENTRY_ENVIRONMENT=production` and `VITE_SENTRY_ENVIRONMENT=production`.

```bash
bash scripts/deploy.sh root@YOUR_VM_IP
```

The script synchronizes project files, explicitly copies `.env` with mode 600, builds and starts the stack, creates/validates the Elastic index, and runs preflight. It does not create a VM or change DNS. Service keys are not displayed. Deployment stops on a failed preflight rather than reporting success.

## Operational commands

```bash
cd /opt/hypecheck
docker compose ps
docker compose logs --tail=100 api worker beat
docker compose exec api python -m app.cli preflight
docker compose exec api python -m app.cli setup-elastic
docker compose exec worker celery -A app.queue.celery inspect ping
```

Keep all services on the same Compose network. Only Caddy publishes ports. FastAPI trusts forwarded headers because it is reachable only through that network; do not publish port 8000 without tightening trusted proxy configuration.

The backend runs as UID 10001. Docker initializes the media volume from a directory owned by that user. PostgreSQL and Redis use persistent named volumes. Logs rotate at 10 MB. `docker compose down` preserves volumes; do not use `down -v` for a normal restart.

The first iteration uses SQLAlchemy schema creation for its initial schema. Later schema changes must use an explicit migration; `create_all` does not upgrade existing tables. Before upgrading, back up PostgreSQL:

```bash
docker compose exec -T db pg_dump -U hypecheck hypecheck > backup.sql
```

## Public verification

1. Open `https://YOUR_DOMAIN/healthz` and `/readyz` from a phone on venue Wi-Fi.
2. Submit each selected public Reel; verify genuine audio transcription before evaluating medical conclusions.
3. Test file fallback when Instagram blocks a download.
4. Open every cited passage and its original paper. Record mismatches and insufficient-evidence cases.
5. Submit three cases at once; confirm IDs are returned without waiting for the workers and queue state remains visible.
6. Restart the worker during research; expect resumption from a checkpoint after the recovery window (up to three minutes).
7. Download a completed HTML replay and open it with Wi-Fi disabled. It is labeled as a recording.

## Demo readiness

Do not make the demo depend on fresh service provisioning. Configure/warm Elastic inference before timing runs. Keep a local copy of each chosen video and a completed offline replay. Keep failed and degraded runs in the benchmark report. Cached-paper timing is reported separately from fresh imports.

The VM is one failure domain by design for the hackathon; this setup is not a highly available production deployment.
