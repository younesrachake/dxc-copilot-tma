#!/bin/sh
# Deploy DXC Copilot on a compose host with health gating and rollback.
#
# Usage:   deploy.sh [image-tag]        (default: latest)
# Expects: /opt/dxc-copilot/.env populated, docker compose v2, GHCR login done.
set -eu

TAG="${1:-latest}"
REGISTRY="${REGISTRY:-ghcr.io}"
IMAGE="${IMAGE_NAME:-dxc/dxc-copilot}"
COMPOSE="docker compose"
HEALTH_URL="${HEALTH_URL:-http://localhost/health}"
API_SMOKE_URL="${API_SMOKE_URL:-http://localhost/api/../healthz}"

echo "[deploy] Deploying ${REGISTRY}/${IMAGE}:${TAG}"

# Remember currently running image IDs for rollback
PREV_APP="$(docker inspect --format '{{.Image}}' dxc-copilot-app 2>/dev/null || echo '')"
PREV_BACKEND="$(docker inspect --format '{{.Image}}' dxc-copilot-backend 2>/dev/null || echo '')"

rollback() {
  echo "[deploy] ❌ Deployment failed — rolling back" >&2
  if [ -n "${PREV_APP}" ] && [ -n "${PREV_BACKEND}" ]; then
    docker tag "${PREV_APP}" dxc-copilot:latest || true
    docker tag "${PREV_BACKEND}" dxc-copilot-backend:latest || true
    ${COMPOSE} up -d --no-build app backend || true
    echo "[deploy] Rollback to previous images attempted — check ${COMPOSE} ps" >&2
  else
    echo "[deploy] No previous images recorded — manual intervention required" >&2
  fi
  exit 1
}

# Pull the new images and retag them for compose
docker pull "${REGISTRY}/${IMAGE}:${TAG}"
docker pull "${REGISTRY}/${IMAGE}-backend:${TAG}" 2>/dev/null || true
docker tag "${REGISTRY}/${IMAGE}:${TAG}" dxc-copilot:latest
docker image inspect "${REGISTRY}/${IMAGE}-backend:${TAG}" >/dev/null 2>&1 \
  && docker tag "${REGISTRY}/${IMAGE}-backend:${TAG}" dxc-copilot-backend:latest

# Recreate with health gating: --wait blocks until healthchecks pass (or timeout)
${COMPOSE} up -d --no-build --wait --wait-timeout 300 || rollback

# Post-deploy smoke tests through the public entrypoint
sleep 5
echo "[deploy] Smoke test: ${HEALTH_URL}"
curl -fsS --max-time 10 "${HEALTH_URL}" >/dev/null || rollback
echo "[deploy] Smoke test: backend /healthz through nginx"
curl -fsSk --max-time 10 "https://localhost/api/auth/me" -o /dev/null -w "%{http_code}" | grep -qE "401" || rollback
# 401 (not 5xx) proves nginx → backend → auth stack is alive

echo "[deploy] ✅ Deployment of ${TAG} healthy"
