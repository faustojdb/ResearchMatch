# Research Match v3.0.0 — Cloud Run Dockerfile
# Multi-stage build: CPU-only PyTorch + sentence-transformers model pre-download

# Stage 1: Install dependencies
FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml README.md ./

# Install CPU-only PyTorch first (~200MB vs ~3GB with CUDA)
RUN uv pip install --system --no-cache torch --index-url https://download.pytorch.org/whl/cpu

# Install remaining dependencies (torch already satisfied, skips CUDA)
RUN uv pip install --system --no-cache .

# Pre-download sentence-transformers model (~90MB)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages and cached model from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /root/.cache/huggingface /root/.cache/huggingface

# Copy application code
COPY src/ src/
COPY pyproject.toml README.md ./

# Cloud Run sets PORT env var (default 8080)
ENV PORT=8080
ENV RESEARCH_MATCH_BACKEND=firestore
ENV RESEARCH_MATCH_LOG_FORMAT=json
ENV RESEARCH_MATCH_LOG_LEVEL=INFO

EXPOSE 8080

CMD ["python", "-m", "src.research_match_server"]
