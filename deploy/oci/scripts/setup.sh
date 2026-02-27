#!/bin/bash
# TinyOraClaw OCI Instance Setup Script
# Runs via cloud-init on first boot - fully unattended
set -euo pipefail
exec > >(tee -a /var/log/tinyoraclaw-setup.log) 2>&1

echo "=== TinyOraClaw setup started at $(date) ==="

ORACLE_MODE="${ORACLE_MODE:-freepdb}"
ORACLE_PWD="${ORACLE_PWD:-TinyOraClaw2026}"
ADB_DSN="${ADB_DSN:-}"
ADB_WALLET_BASE64="${ADB_WALLET_BASE64:-}"

# -- 1. System packages --
echo "--- Installing system packages ---"
dnf install -y oracle-epel-release-el9
dnf install -y docker-engine docker-compose-plugin git gcc gcc-c++ make wget curl unzip python3 python3-pip
systemctl enable --now docker
usermod -aG docker opc

# -- 2. Install Node.js 22 --
echo "--- Installing Node.js 22 ---"
curl -fsSL https://rpm.nodesource.com/setup_22.x | bash -
dnf install -y nodejs
node --version
npm --version

# -- 3. Clone TinyOraClaw --
echo "--- Cloning TinyOraClaw ---"
git clone https://github.com/jasperan/tinyoraclaw.git /opt/tinyoraclaw
cd /opt/tinyoraclaw

# -- 4. Oracle Database Setup --
echo "--- Setting up Oracle Database (mode: $ORACLE_MODE) ---"

if [ "$ORACLE_MODE" = "freepdb" ]; then
  # Create .env for Docker Compose
  cat > /opt/tinyoraclaw/.env <<ENVEOF
ORACLE_MODE=freepdb
ORACLE_HOST=oracle-db
ORACLE_PORT=1521
ORACLE_SERVICE=FREEPDB1
ORACLE_USER=tinyoraclaw
ORACLE_PASSWORD=${ORACLE_PWD}
ORACLE_POOL_MIN=2
ORACLE_POOL_MAX=10
AUTO_INIT=true
TINYORACLAW_SERVICE_PORT=8100
ENVEOF

  # Start Oracle DB + Sidecar via Docker Compose
  echo "--- Starting Docker Compose (Oracle DB + Sidecar) ---"
  docker compose up oracle-db tinyoraclaw-service -d

  echo "Waiting for Oracle DB to be ready..."
  TIMEOUT=300
  ELAPSED=0
  while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' tinyoraclaw-oracle 2>/dev/null || echo "starting")
    if [ "$STATUS" = "healthy" ]; then
      echo "Oracle DB is healthy"
      break
    fi
    sleep 10
    ELAPSED=$((ELAPSED + 10))
    echo "  Waiting... ${ELAPSED}s"
  done

  if [ "$STATUS" != "healthy" ]; then
    echo "ERROR: Oracle DB timed out after ${TIMEOUT}s"
    docker compose logs oracle-db --tail 50
    exit 1
  fi

  # Wait for sidecar to auto-init schema
  sleep 10
  echo "Sidecar health:"
  curl -s http://localhost:8100/api/health || echo "(sidecar still starting)"

elif [ "$ORACLE_MODE" = "adb" ]; then
  # ADB mode - wallet and DSN provided by Terraform
  WALLET_DIR="/opt/tinyoraclaw/wallet"
  if [ -n "$ADB_WALLET_BASE64" ]; then
    mkdir -p "$WALLET_DIR"
    echo "$ADB_WALLET_BASE64" | base64 -d > "$WALLET_DIR/wallet.zip"
    cd "$WALLET_DIR" && unzip -o wallet.zip && cd /opt/tinyoraclaw
  fi

  cat > /opt/tinyoraclaw/.env <<ENVEOF
ORACLE_MODE=adb
ORACLE_USER=ADMIN
ORACLE_PASSWORD=${ORACLE_PWD}
ORACLE_DSN=${ADB_DSN}
ORACLE_WALLET_LOCATION=${WALLET_DIR}
ORACLE_POOL_MIN=2
ORACLE_POOL_MAX=10
AUTO_INIT=true
TINYORACLAW_SERVICE_PORT=8100
ENVEOF

  # Start sidecar only (no local Oracle container)
  docker compose --profile adb up tinyoraclaw-service-adb -d
  sleep 10
fi

# -- 5. Build TinyClaw TypeScript --
echo "--- Building TinyClaw (npm install + build) ---"
cd /opt/tinyoraclaw
npm install
npm run build

# -- 6. Create systemd service for queue processor --
echo "--- Installing queue processor service ---"
cat > /etc/systemd/system/tinyoraclaw-queue.service <<'UNIT'
[Unit]
Description=TinyOraClaw Queue Processor
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=opc
WorkingDirectory=/opt/tinyoraclaw
ExecStart=/usr/bin/node /opt/tinyoraclaw/dist/queue-processor.js
Restart=on-failure
RestartSec=10
Environment=HOME=/home/opc
Environment=TINYORACLAW_SERVICE_URL=http://localhost:8100

[Install]
WantedBy=multi-user.target
UNIT

# Don't start yet - user needs to run setup wizard first
systemctl daemon-reload
systemctl enable tinyoraclaw-queue

# -- 7. Set ownership --
chown -R opc:opc /opt/tinyoraclaw

# -- 8. Done --
echo ""
echo "=== TinyOraClaw setup completed at $(date) ==="
echo ""
echo "Next steps:"
echo "  1. SSH in: ssh opc@<public-ip>"
echo "  2. Run setup wizard: cd /opt/tinyoraclaw && ./tinyclaw.sh setup"
echo "  3. Start the queue: systemctl start tinyoraclaw-queue"
echo ""
touch /var/log/tinyoraclaw-setup-complete
