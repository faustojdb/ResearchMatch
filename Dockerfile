# Research Match — Cloud Run Dockerfile
# Multi-stage build: dependencies pinned by uv.lock, CPU-only PyTorch, model pre-downloaded

# Stage 1: Install dependencies
FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./

# Install the exact versions from uv.lock — the ones the test-suite runs against — instead
# of whatever PyPI serves on build day: an unpinned install once pulled mcp 2.x, whose
# renamed FastMCP import kept the container from starting. torch and its CUDA companions
# (nvidia-*, triton, cuda-*) are dropped from the list and replaced by the CPU-only build of the same locked torch
# version (~200MB instead of ~3GB).
RUN uv export --frozen --no-dev --no-emit-project --no-hashes -o /tmp/requirements.txt \
 && grep -v -E '^(torch==|nvidia-|triton==|cuda-)' /tmp/requirements.txt > /tmp/requirements-cpu.txt \
 && TORCH_VERSION="$(sed -n 's/^torch==\([^ ;]*\).*/\1/p' /tmp/requirements.txt)" \
 && echo "torch ${TORCH_VERSION} (cpu build)" \
 && uv pip install --system --no-cache "torch==${TORCH_VERSION}" --index-url https://download.pytorch.org/whl/cpu \
 && uv pip install --system --no-cache -r /tmp/requirements-cpu.txt

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
