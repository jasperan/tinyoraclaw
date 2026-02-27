#!/bin/bash
# TinyOraClaw — One-command Oracle setup
#
# Starts Oracle 26ai Free container + TinyOraClaw sidecar service.
# The sidecar auto-initializes the schema on first boot.

set -e

echo "=== TinyOraClaw Oracle Setup ==="
echo ""

# Check .env exists
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo "Copying .env.example to .env..."
        cp .env.example .env
    else
        echo "ERROR: No .env file found. Copy .env.example to .env first."
        exit 1
    fi
fi

echo "Starting Oracle 26ai Free + TinyOraClaw sidecar..."
docker compose up oracle-db tinyoraclaw-service -d

echo ""
echo "Waiting for Oracle to become healthy (this may take ~2 minutes on first run)..."
echo "You can monitor progress with: docker compose logs -f oracle-db"
echo ""

# Wait for healthcheck
MAX_WAIT=300
ELAPSED=0
while [ $ELAPSED -lt $MAX_WAIT ]; do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' tinyoraclaw-oracle 2>/dev/null || echo "starting")
    if [ "$STATUS" = "healthy" ]; then
        echo "Oracle is healthy!"
        break
    fi
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    echo "  Waiting... ($ELAPSED s)"
done

if [ "$STATUS" != "healthy" ]; then
    echo "WARNING: Oracle did not become healthy within ${MAX_WAIT}s."
    echo "Check logs: docker compose logs oracle-db"
    exit 1
fi

echo ""
echo "Checking sidecar health..."
sleep 3
HEALTH=$(curl -s http://localhost:8100/api/health 2>/dev/null || echo '{"status":"unavailable"}')
echo "Sidecar: $HEALTH"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Oracle DB:  localhost:1521/FREEPDB1"
echo "Sidecar:    http://localhost:8100"
echo ""
echo "Next steps:"
echo "  npm install && npm run build"
echo "  ./tinyclaw.sh setup"
echo "  npm run queue"
