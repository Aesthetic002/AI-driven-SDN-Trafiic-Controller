# ── Demo / Mock mode image ────────────────────────────────────────────────────
# Works on Mac, Windows, Linux. No Mininet or OvS needed.
# Runs the Flask API in --mock mode and serves synthetic live data.
#
# Build: docker compose build
# Run  : docker compose up
# Open : http://localhost:8080  (dashboard)
#        http://localhost:5000  (API)

FROM python:3.11-slim

WORKDIR /app

# Build deps for numpy/cryptography wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# PyTorch CPU-only wheel (~190 MB — much smaller than the default 750 MB GPU wheel)
RUN pip install --no-cache-dir torch \
        --index-url https://download.pytorch.org/whl/cpu

# App dependencies (no Ryu, no Mininet — not needed for mock mode)
COPY requirements-demo.txt .
RUN pip install --no-cache-dir -r requirements-demo.txt

# Copy source
COPY constants.py .
COPY agent/       agent/
COPY api/         api/
COPY collector/   collector/
COPY traffic/     traffic/

EXPOSE 5000

# Default: mock mode with live synthetic data
CMD ["python3", "api/app.py", "--mock", "--host", "0.0.0.0"]
