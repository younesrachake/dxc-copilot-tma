# DXC Copilot — Operations Runbook

## Architecture (production, Docker Compose)

```
Internet → nginx (app container, TLS, :443)
             ├── /            Angular SPA (static)
             ├── /api/*       → backend:8000 (FastAPI)  [SSE unbuffered on /api/chat/stream]
             └── /api/metrics BLOCKED (scraped internally by Prometheus)
           backend → postgres:5432, redis:6379 (internal network only, never published)
           backup  → pg_dump daily → `backups` volume (rotation: BACKUP_KEEP)
```

Kubernetes path: `deploy/helm/dxc-copilot/` (external PostgreSQL/Redis required — see NOTES.txt).

## Deploy

- CI/CD: push to `main` → tests (backend + frontend + E2E) → images to GHCR → staging → manual approval → production.
- Manual on a host: `sh scripts/deploy.sh <tag>` — pulls, recreates with `--wait` health gating, smoke-tests through nginx, **rolls back automatically** on failure.
- First boot is slow (~2–4 min): alembic migrations + local ML model load. Healthcheck `start_period` accounts for it.

## Database

- **Migrations**: Alembic (`backend/migrations/`), applied automatically by the container entrypoint (`alembic upgrade head`). New schema changes = new alembic revision, never ad-hoc SQL.
- **Backups**: `backup` compose service dumps daily to the `backups` volume; also on-demand via admin UI (Maintenance → Sauvegarde) which calls pg_dump/SQLite online backup for real.
- **Restore (PostgreSQL)**:
  ```sh
  docker compose stop backend
  gunzip -c backups/backup-YYYYMMDD-HHMMSS.sql.gz | docker compose exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB
  docker compose start backend
  ```
- The Chroma vector store lives in the `chroma_data` volume; it can always be rebuilt (re-ingest KB documents + `POST /api/admin/knowledge/seed`), so DB backups are the critical path.

## Observability

- Enable the stack: `docker compose --profile observability up -d` → Grafana on :3000 (`GRAFANA_ADMIN_PASSWORD`), dashboard "DXC Copilot — API & RAG".
- Backend metrics: `/metrics` (blocked at nginx; Prometheus scrapes `backend:8000` internally). Custom metrics: `dxc_rag_routing_total`, `dxc_rag_latency_seconds`, `dxc_llm_errors_total`, `dxc_semantic_cache_hits_total`, `dxc_intent_total`.
- Alert rules (`observability/prometheus/alerts.yml`): backend down, 5xx >5%, P95 latency, LLM error spikes, RAG latency, "KB skipped >60%" (knowledge-gap signal).
- Logs: JSON to stdout (`LOG_JSON=1`) → Promtail → Loki; query `{container="dxc-copilot-backend"} |= "ERROR"` in Grafana.

## Tests

| Layer | Command | Count |
|---|---|---|
| Backend API/unit | `cd backend && pytest tests` | 50 |
| Angular unit | `npm run test:ci` | 15 |
| E2E (real stack) | `npx playwright test` | 8 |

Backend tests are hermetic (`DISABLE_LOCAL_ML=1`, `DISABLE_CHROMA=1`, temp SQLite) — no model downloads, no API keys.

## Security

- Secrets: never commit `.env` (gitignored, gitleaks scans every PR + history weekly). Rotate any key that leaks; the backend refuses to start in production with default JWT secret or SQLite.
- Postgres/Redis/backend are **not** published to the host — only nginx :80/:443.
- Images: non-root (backend UID 10001), `no-new-privileges`, Trivy blocks CRITICAL vulns in CI, CodeQL + Dependabot enabled.

## Common operations

| Task | How |
|---|---|
| Restart backend | `docker compose restart backend` (admin UI "restart" intentionally returns 501) |
| Clear semantic cache | Admin UI → Maintenance → Nettoyage du cache (real: clears cache + prunes 90d telemetry) |
| VACUUM/ANALYZE | Admin UI → Maintenance → Optimisation BD (real) |
| Tune RAG thresholds | Admin UI → Analytics → Seuils de routage (recommendation from feedback data, applied manually) |
| Rotate admin password | Admin UI → Users, or `INITIAL_ADMIN_PASSWORD` only seeds the FIRST admin |

## GitHub setup required (one-time)

1. Environments `staging` and `production` (production: required reviewers for manual approval gate).
2. Secrets: `STAGING_HOST/USER/SSH_KEY`, `PROD_HOST/USER/SSH_KEY`, `TEAMS_WEBHOOK_URL`.
3. Hosts: `/opt/dxc-copilot` = clone of this repo + `.env` from `.env.example` with real values.
