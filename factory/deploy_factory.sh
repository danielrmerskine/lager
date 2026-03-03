#!/bin/bash
#
# Deploy Factory Dashboard to a Lager Box
#
# This script deploys the factory webapp as a Docker container on a Lager box,
# accessible at http://<box-tailscale-ip>:5001.
#
# Prerequisites:
#   - SSH access to the box (key-based, as the box user)
#   - Docker and docker compose installed on the box
#   - The lager container already running on the box
#
# Usage:
#   ./deploy_factory.sh <BOX_IP>
#
# Example:
#   ./deploy_factory.sh <BOX-IP>
#

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

BOX_IP="${1:?Usage: $0 <BOX_IP>}"
BOX_USER="${BOX_USER:-lagerdata}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE_DIR="/home/${BOX_USER}/factory"

ssh_cmd() {
    ssh -o StrictHostKeyChecking=accept-new "${BOX_USER}@${BOX_IP}" "$@"
}

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Deploy Factory Dashboard${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ──────────────────────────────────────────────
# Step 1: Verify prerequisites
# ──────────────────────────────────────────────
echo -e "${BLUE}[1/6] Verifying prerequisites...${NC}"

# SSH access
if ! ssh_cmd "echo ok" &>/dev/null; then
    echo -e "${RED}[FAIL] Cannot SSH to ${BOX_USER}@${BOX_IP}${NC}"
    echo -e "  Ensure SSH key access is configured for the box."
    exit 1
fi
echo -e "${GREEN}  [OK] SSH access${NC}"

# Docker
if ! ssh_cmd "command -v docker" &>/dev/null; then
    echo -e "${RED}[FAIL] Docker not installed on box${NC}"
    exit 1
fi
echo -e "${GREEN}  [OK] Docker installed${NC}"

# docker compose
if ! ssh_cmd "docker compose version" &>/dev/null; then
    echo -e "${RED}[FAIL] docker compose not available on box${NC}"
    exit 1
fi
echo -e "${GREEN}  [OK] docker compose available${NC}"

# lager container running
if ! ssh_cmd "docker ps -q -f name=^lager$" 2>/dev/null | grep -q .; then
    echo -e "${YELLOW}[WARNING] lager container not running -- factory will deploy but box SSH may not work${NC}"
else
    echo -e "${GREEN}  [OK] lager container running${NC}"
fi

echo ""

# ──────────────────────────────────────────────
# Step 2: Configure SSH self-access
# ──────────────────────────────────────────────
echo -e "${BLUE}[2/6] Configuring SSH self-access on box...${NC}"

ssh_cmd bash <<'REMOTE_SSH_SETUP'
set -e
KEY_FILE="$HOME/.ssh/id_ed25519"

# Generate key if it does not exist
if [ ! -f "$KEY_FILE" ]; then
    ssh-keygen -t ed25519 -f "$KEY_FILE" -N "" -q
    echo "  Generated new ed25519 key"
else
    echo "  SSH key already exists"
fi

# Ensure the public key is in authorized_keys
PUB=$(cat "${KEY_FILE}.pub")
AUTH="$HOME/.ssh/authorized_keys"
touch "$AUTH"
if ! grep -qF "$PUB" "$AUTH"; then
    echo "$PUB" >> "$AUTH"
    echo "  Added public key to authorized_keys"
else
    echo "  Public key already authorized"
fi

# Accept localhost host key if not already known
if ! ssh -o StrictHostKeyChecking=no -o BatchMode=yes localhost "echo ok" &>/dev/null; then
    echo "  WARNING: SSH self-connect test failed (may need manual check)"
else
    echo "  SSH self-connect test passed"
fi
REMOTE_SSH_SETUP

echo -e "${GREEN}  [OK] SSH self-access configured${NC}"
echo ""

# ──────────────────────────────────────────────
# Step 3: Detect box configuration
# ──────────────────────────────────────────────
echo -e "${BLUE}[3/6] Detecting box configuration...${NC}"

BOX_HOSTNAME=$(ssh_cmd "hostname" 2>/dev/null)
echo -e "${GREEN}  Hostname: ${BOX_HOSTNAME}${NC}"

TAILSCALE_IP=$(ssh_cmd "tailscale ip -4 2>/dev/null || echo ''")
if [ -n "$TAILSCALE_IP" ]; then
    echo -e "${GREEN}  Tailscale IP: ${TAILSCALE_IP}${NC}"
else
    echo -e "${YELLOW}  Tailscale IP: not detected (using ${BOX_IP})${NC}"
    TAILSCALE_IP="$BOX_IP"
fi

echo ""

# ──────────────────────────────────────────────
# Step 4: Deploy files to box
# ──────────────────────────────────────────────
echo -e "${BLUE}[4/6] Deploying files to box...${NC}"

# Create remote directory
ssh_cmd "mkdir -p ${REMOTE_DIR}"

# Rsync factory directory (webapp + lager + docker-compose)
rsync -az --delete \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='data/' \
    --exclude='FACTORY_CONTAINER_PLAN.md' \
    --exclude='test_scripts/' \
    "${SCRIPT_DIR}/webapp/" "${BOX_USER}@${BOX_IP}:${REMOTE_DIR}/webapp/"

rsync -az --delete \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    "${SCRIPT_DIR}/lager/" "${BOX_USER}@${BOX_IP}:${REMOTE_DIR}/lager/"

# Copy docker-compose.yml
scp -q "${SCRIPT_DIR}/docker-compose.yml" "${BOX_USER}@${BOX_IP}:${REMOTE_DIR}/docker-compose.yml"

echo -e "${GREEN}  [OK] Files synced to ${REMOTE_DIR}${NC}"

# Generate boxes.json with detected box name
echo -e "  Generating boxes.json with hostname '${BOX_HOSTNAME}'..."
ssh_cmd "cat > ${REMOTE_DIR}/webapp/boxes.json" <<EOF
{
  "local": {
    "name": "${BOX_HOSTNAME}",
    "ip": "host.docker.internal",
    "ssh_user": "${BOX_USER}",
    "container": "lager"
  }
}
EOF

echo -e "${GREEN}  [OK] boxes.json generated${NC}"
echo ""

# ──────────────────────────────────────────────
# Step 5: Build and start container
# ──────────────────────────────────────────────
echo -e "${BLUE}[5/6] Building and starting factory container...${NC}"

ssh_cmd "cd ${REMOTE_DIR} && docker compose up -d --build" 2>&1

# Verify container is running
sleep 2
if ssh_cmd "docker ps -q -f name=^factory$" 2>/dev/null | grep -q .; then
    echo -e "${GREEN}  [OK] Factory container is running${NC}"
else
    echo -e "${RED}  [FAIL] Factory container failed to start${NC}"
    echo -e "  Check logs with: ssh ${BOX_USER}@${BOX_IP} 'docker logs factory'"
    exit 1
fi

echo ""

# ──────────────────────────────────────────────
# Step 6: Configure firewall
# ──────────────────────────────────────────────
echo -e "${BLUE}[6/6] Configuring firewall for port 5001...${NC}"

ssh_cmd bash <<'REMOTE_FW'
set -e
if command -v ufw &>/dev/null && sudo ufw status | grep -q "Status: active"; then
    # Add rules only if not already present
    for IFACE in lo docker0 tailscale0; do
        if ip link show "$IFACE" &>/dev/null 2>&1 || [ "$IFACE" = "lo" ]; then
            if ! sudo ufw status | grep -q "5001.*ALLOW.*on $IFACE"; then
                sudo ufw allow in on "$IFACE" to any port 5001 comment "Factory dashboard"
                echo "  Added UFW rule: allow 5001 on $IFACE"
            else
                echo "  UFW rule already exists: 5001 on $IFACE"
            fi
        fi
    done
else
    echo "  UFW not active, skipping firewall configuration"
fi
REMOTE_FW

echo -e "${GREEN}  [OK] Firewall configured${NC}"
echo ""

# ──────────────────────────────────────────────
# Done
# ──────────────────────────────────────────────
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Factory Dashboard Deployed${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "  Dashboard URL: ${BLUE}http://${TAILSCALE_IP}:5001${NC}"
echo ""
echo -e "  Useful commands:"
echo -e "    View logs:      ssh ${BOX_USER}@${BOX_IP} 'docker logs -f factory'"
echo -e "    Restart:        ssh ${BOX_USER}@${BOX_IP} 'cd ${REMOTE_DIR} && docker compose restart'"
echo -e "    Rebuild:        ssh ${BOX_USER}@${BOX_IP} 'cd ${REMOTE_DIR} && docker compose up -d --build'"
echo -e "    Stop:           ssh ${BOX_USER}@${BOX_IP} 'cd ${REMOTE_DIR} && docker compose down'"
echo ""
