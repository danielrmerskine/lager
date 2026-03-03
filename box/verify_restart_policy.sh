#!/bin/bash

# Script to verify Docker restart policies are properly configured
# This ensures containers will automatically restart on reboot or failure

set -e

echo "========================================"
echo "Verifying Docker Restart Configuration"
echo "========================================"
echo ""

# New setup uses single 'lager' container
CONTAINERS=("lager")
ALL_GOOD=true

# Check if Docker service is enabled
echo "[1/2] Checking Docker service..."
if systemctl is-enabled docker.service >/dev/null 2>&1; then
    echo "[OK] Docker service is enabled (will start on boot)"
else
    echo "[WARNING] Docker service is NOT enabled"
    echo "  Run: sudo systemctl enable docker"
    ALL_GOOD=false
fi
echo ""

# Check restart policies for each container
echo "[2/2] Checking container restart policies..."
for container in "${CONTAINERS[@]}"; do
    if docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
        RESTART_POLICY=$(docker inspect --format='{{.HostConfig.RestartPolicy.Name}}' "$container" 2>/dev/null)
        if [ "$RESTART_POLICY" = "always" ]; then
            echo "[OK] Container '$container' has restart policy: $RESTART_POLICY"
        else
            echo "[FAIL] Container '$container' has incorrect restart policy: $RESTART_POLICY"
            echo "  Expected: always"
            ALL_GOOD=false
        fi
    else
        echo "[WARNING] Container '$container' not found (may not be started yet)"
        ALL_GOOD=false
    fi
done
echo ""

echo "========================================"
if [ "$ALL_GOOD" = true ]; then
    echo "[OK] All checks passed!"
    echo "========================================"
    echo ""
    echo "Your containers will automatically:"
    echo "  • Restart if they crash or exit"
    echo "  • Start when Docker daemon starts"
    echo "  • Start automatically on system reboot"
    echo ""
    echo "To test, try:"
    echo "  docker stop lager        # Container will restart automatically"
    echo "  sudo reboot              # Containers will start on boot"
else
    echo "[FAIL] Some checks failed!"
    echo "========================================"
    echo ""
    echo "To fix:"
    echo "  1. Enable Docker: sudo systemctl enable docker"
    echo "  2. Restart containers: cd box && ./start_box.sh"
    exit 1
fi
