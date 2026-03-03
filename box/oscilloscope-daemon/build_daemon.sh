#!/bin/bash
#
# Build script for the oscilloscope-daemon
#
# This script should be run on a Linux x86_64 system with:
# 1. Rust toolchain installed
# 2. PicoScope SDK installed at /opt/picoscope/
#
# Usage:
#   ./build_daemon.sh              # Build release binary
#   ./build_daemon.sh --install    # Build and install to box docker directory
#
# Prerequisites (run on box):
#   # Install Rust toolchain
#   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
#   source ~/.cargo/env
#
#   # Install PicoScope SDK (if not already installed)
#   wget -qO - https://labs.picotech.com/debian/dists/picoscope/Release.gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/picoscope-archive-keyring.gpg
#   echo "deb [signed-by=/usr/share/keyrings/picoscope-archive-keyring.gpg] https://labs.picotech.com/debian/ picoscope main" | sudo tee /etc/apt/sources.list.d/picoscope.list
#   sudo apt-get update
#   sudo apt-get install -y libps2000
#
#   # Install build dependencies
#   sudo apt-get install -y build-essential pkg-config libclang-dev
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "Building Oscilloscope Streamer Daemon"
echo "========================================"
echo ""

# Check for Rust toolchain
if ! command -v cargo &> /dev/null; then
    echo "ERROR: Rust toolchain not found!"
    echo ""
    echo "Install Rust with:"
    echo "  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    echo "  source ~/.cargo/env"
    exit 1
fi

# Check for PicoScope SDK
if [ ! -f /opt/picoscope/lib/libps2000.so ] && [ ! -f /usr/lib/x86_64-linux-gnu/libps2000.so ]; then
    echo "WARNING: PicoScope SDK not found at expected locations"
    echo "  Expected: /opt/picoscope/lib/libps2000.so"
    echo "  Or: /usr/lib/x86_64-linux-gnu/libps2000.so"
    echo ""
    echo "The build may fail. Install with:"
    echo "  sudo apt-get install -y libps2000"
    echo ""
fi

# Check for clang/libclang (needed for bindgen)
if ! command -v clang &> /dev/null; then
    echo "WARNING: clang not found (needed for bindgen)"
    echo "Install with: sudo apt-get install -y libclang-dev"
fi

echo "Building daemon (release mode)..."
echo ""

# Set library path for PicoScope
export LIBRARY_PATH="/opt/picoscope/lib:/usr/lib/x86_64-linux-gnu"
export LD_LIBRARY_PATH="/opt/picoscope/lib:/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH"

# Build the daemon
cd daemon
cargo build --release --features ps2000

if [ $? -eq 0 ]; then
    echo ""
    echo "Build successful!"
    echo "Binary: $SCRIPT_DIR/target/release/daemon"

    if [ "$1" == "--install" ]; then
        echo ""
        echo "Installing to box docker directory..."
        # Binary is named 'daemon' in the Cargo workspace
        cp "$SCRIPT_DIR/target/release/daemon" "$SCRIPT_DIR/../lager/docker/oscilloscope-daemon"
        echo "Installed to: $SCRIPT_DIR/../lager/docker/oscilloscope-daemon"
    fi
else
    echo ""
    echo "Build failed!"
    exit 1
fi

echo ""
echo "========================================"
echo "Build complete!"
echo "========================================"
echo ""
echo "To deploy to box:"
echo "  1. Copy the binary to the box:"
echo "     scp target/release/oscilloscope-daemon lagerdata@<box-ip>:~/box/lager/docker/"
echo ""
echo "  2. Rebuild the Docker container:"
echo "     ssh lagerdata@<box-ip> 'cd ~/box && ./start_box.sh'"
echo ""
