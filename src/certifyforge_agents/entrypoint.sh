#!/bin/sh
set -e

echo "CertifyForge container starting..."

# Start the readiness server immediately (as pid 1 via exec) so platform health/readiness probes pass without delay.
# Run the (optional) demo in background so its rich logs appear in container output without blocking server start.
# This prevents startup readiness timeouts that lead to "unhealthy" status after deploys.
if [ "${RUN_DEMO_ON_START:-0}" = "1" ]; then
  echo "Running demo orchestration (for startup logs) in background..."
  timeout 120 python -m certifyforge_agents || true &
fi

echo "Starting Responses server on port ${PORT:-8088} (POST /responses, GET /readiness)..."
export PYTHONUNBUFFERED=1
exec python -u -m certifyforge_agents.readiness_server