#!/bin/bash
# ============================================
# XVFB Startup Script for Headful Chrome
# ============================================
# This script enables "headful" Chrome mode inside Docker
# using XVFB (X Virtual Framebuffer).
#
# Why Headful > Headless:
# - navigator.webdriver is not set
# - Chrome behaves exactly like desktop Chrome
# - Many bot detection scripts check for headless indicators

set -e

echo "[Titan Worker] ============================================"
echo "[Titan Worker] Starting Titan Worker with XVFB"
echo "[Titan Worker] ============================================"

# ============================================
# Start XVFB Virtual Display
# ============================================
echo "[Titan Worker] Starting XVFB virtual display..."

# Start XVFB in background
Xvfb :99 -screen 0 ${XVFB_RESOLUTION:-1920x1080x24} -ac +extension GLX +render -noreset &
XVFB_PID=$!

# Wait for XVFB to be ready
sleep 1

# Verify XVFB is running
if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "[Titan Worker] ERROR: XVFB failed to start"
    exit 1
fi

echo "[Titan Worker] XVFB started on display :99 (PID: $XVFB_PID)"

# Export display for Chrome
export DISPLAY=:99

# ============================================
# Start D-Bus (required for some Chrome features)
# ============================================
if [ -x /usr/bin/dbus-daemon ]; then
    echo "[Titan Worker] Starting D-Bus daemon..."
    mkdir -p /run/dbus 2>/dev/null || true
    dbus-daemon --system --fork 2>/dev/null || true
fi

# ============================================
# Cleanup Function
# ============================================
cleanup() {
    echo ""
    echo "[Titan Worker] ============================================"
    echo "[Titan Worker] Shutting down gracefully..."
    echo "[Titan Worker] ============================================"
    
    # Kill all Chrome instances (memory safety)
    echo "[Titan Worker] Killing Chrome instances..."
    pkill -f chromium 2>/dev/null || true
    pkill -f chrome 2>/dev/null || true
    pkill -f chromedriver 2>/dev/null || true
    
    # Stop XVFB
    if [ -n "$XVFB_PID" ]; then
        echo "[Titan Worker] Stopping XVFB (PID: $XVFB_PID)..."
        kill $XVFB_PID 2>/dev/null || true
    fi
    
    echo "[Titan Worker] Cleanup complete"
    exit 0
}

# Register cleanup handlers
trap cleanup EXIT SIGTERM SIGINT SIGQUIT

# ============================================
# Health Check Info
# ============================================
echo "[Titan Worker] Environment:"
echo "  - DISPLAY: $DISPLAY"
echo "  - CHROME_BIN: ${CHROME_BIN:-/usr/bin/chromium}"
echo "  - CHROMEDRIVER_PATH: ${CHROMEDRIVER_PATH:-/usr/bin/chromedriver}"
echo "  - XVFB_RESOLUTION: ${XVFB_RESOLUTION:-1920x1080x24}"
echo ""

# ============================================
# Start Main Process
# ============================================
echo "[Titan Worker] Starting ARQ worker..."
echo "[Titan Worker] ============================================"

# Execute the main command (ARQ worker)
exec "$@"
