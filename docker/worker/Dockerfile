# ============================================
# TITAN WORKER DOCKERFILE
# ============================================
# This Dockerfile creates a production-ready worker 
# with XVFB for headful Chrome operation.
#
# Why Headful Chrome (via XVFB):
# - Bypasses many bot detection systems
# - navigator.webdriver returns undefined
# - Chrome behaves exactly like desktop browser
# ============================================

# --------- Builder Stage ---------
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies first (for better layer caching)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# Copy the project source code
COPY . /app

# Install the project in non-editable mode
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

# --------- Final Stage (Worker with XVFB + Chrome) ---------
FROM python:3.11-slim-bookworm

# ============================================
# Install XVFB, Chromium and Dependencies
# ============================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    # ===========================================
    # XVFB - X Virtual Framebuffer (CRITICAL)
    # Enables "headful" mode inside Docker
    # ===========================================
    xvfb \
    dbus \
    dbus-x11 \
    # ===========================================
    # Chromium Browser and Driver
    # ===========================================
    chromium \
    chromium-driver \
    # ===========================================
    # Chrome Dependencies
    # ===========================================
    libnss3 \
    libnss3-tools \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdrm2 \
    libgbm1 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libasound2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgtk-3-0 \
    # ===========================================
    # X11 Libraries (CRITICAL for XVFB)
    # ===========================================
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxext6 \
    libxrender1 \
    x11-utils \
    # ===========================================
    # Fonts for proper text rendering
    # ===========================================
    fonts-liberation \
    fonts-noto-color-emoji \
    fonts-freefont-ttf \
    fonts-dejavu-core \
    fontconfig \
    # ===========================================
    # Utilities
    # ===========================================
    wget \
    curl \
    ca-certificates \
    procps \
    && fc-cache -f -v \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# ============================================
# Environment Variables
# ============================================
# Chrome/Chromium paths
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# XVFB Display Settings
ENV DISPLAY=:99
ENV XVFB_RESOLUTION=1920x1080x24

# Chrome Flags (Base - Botasaurus may override)
ENV CHROMIUM_FLAGS="--no-sandbox --disable-dev-shm-usage"
ENV CHROME_NO_SANDBOX=true

# Botasaurus profile directory
ENV BOTASAURUS_PROFILE_DIR=/app/titan-profiles

# Python optimization
ENV PYTHONUNBUFFERED=1

# ============================================
# Create User and Directories
# ============================================
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --shell /bin/bash --create-home app \
    && mkdir -p /app/titan-profiles /app/logs /tmp/.X11-unix \
    && chmod 1777 /tmp/.X11-unix \
    && chown -R app:app /app

# ============================================
# Copy Virtual Environment (initially as root for pre-download)
# ============================================
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# ============================================
# Pre-download Botasaurus Dependencies (Warm Cache)
# ============================================
# Botasaurus downloads hrequests-cgo binary on first use.
# Pre-downloading here avoids 5-10s delay on first request.
# Must run as root and BEFORE changing ownership to app user.
# 
# The library is downloaded to:
#   /app/.venv/lib/python3.11/site-packages/botasaurus_requests/bin/
#
RUN mkdir -p /app/.venv/lib/python3.11/site-packages/botasaurus_requests/bin \
    && python -c "from botasaurus.request import request, Request; print('[Dockerfile] Botasaurus CFFI library downloaded successfully')" \
    && echo "[Dockerfile] Botasaurus warm-up complete"

# ============================================
# Fix Ownership for App User
# ============================================
# Now change ownership after pre-download is complete
RUN chown -R app:app /app/.venv

# ============================================
# Copy Startup Script
# ============================================
COPY --chown=app:app docker/worker/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# ============================================
# Switch to Non-Root User
# ============================================
USER app
WORKDIR /code

# ============================================
# Healthcheck
# ============================================
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD pgrep -x Xvfb > /dev/null || exit 1

# ============================================
# Entrypoint - XVFB initialization
# ============================================
ENTRYPOINT ["/app/start.sh"]
CMD ["arq", "app.core.worker.settings.WorkerSettings"]
