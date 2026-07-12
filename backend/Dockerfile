FROM python:3.10-slim

# Security: non-root user with a fixed numeric UID (k8s runAsNonRoot needs it)
RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download local ML models (~1 GB) so containers don't fetch them at first request
ENV HF_HOME=/app/.hf_cache
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
    SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2'); \
    CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1')"

# Copy application code
COPY . .

# Entrypoint runs alembic migrations before starting the server
RUN chmod +x /app/entrypoint.sh

# Set ownership
RUN chown -R appuser:appuser /app

# Switch to non-root user (numeric — verifiable by kubelet runAsNonRoot)
USER 10001

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

# Start server (entrypoint applies DB migrations first)
ENTRYPOINT ["/app/entrypoint.sh"]
