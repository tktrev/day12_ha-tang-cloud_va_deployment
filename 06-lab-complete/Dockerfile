# ============================================================
# Production Dockerfile — Multi-stage build
# Stage 1 (builder): installs all dependencies
# Stage 2 (runtime): copies only what it needed to run
# ============================================================

# ── Stage 1: Builder ──────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Build dependencies (needed to compile some Python packages like numpy, psycopg2)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages to /app (standard site-packages, not --user)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the whole app (builder stage is throwaway)
COPY app/ ./app/
COPY utils/ ./utils/

# ── Stage 2: Runtime ─────────────────────────────────
FROM python:3.11-slim AS runtime

# Create non-root user (security best practice)
RUN groupadd -r agent && useradd -r -g agent -d /app agent

WORKDIR /app

# Copy everything from builder — packages + app code
COPY --from=builder /app /app

# Set ownership
RUN chown -R agent:agent /app

USER agent

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
    || exit 1

# Use python -m uvicorn so Python finds uvicorn in /app/site-packages
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]