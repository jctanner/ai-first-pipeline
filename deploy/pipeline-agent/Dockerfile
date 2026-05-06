# ── Stage 1: Build arch-query with embedded architecture data ────
FROM golang:1.25-bookworm AS arch-query-builder

RUN apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone --depth 1 https://github.com/opendatahub-io/architecture-context.git && \
    cd architecture-context/src/arch-query && \
    GOTOOLCHAIN=auto make build-embedded && \
    cp ../../bin/arch-query /build/arch-query


# ── Stage 2: Pipeline agent ─────────────────────────────────────
FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    nodejs \
    npm \
    ca-certificates \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Inject internal CA certificate (extracted at build time by 05b-build-agent.sh)
COPY internal-ca.crt /usr/local/share/ca-certificates/internal-ca.crt
RUN update-ca-certificates

# Copy arch-query binary from builder stage
COPY --from=arch-query-builder /build/arch-query /usr/local/bin/arch-query

# Create non-root user early
RUN useradd -m -s /bin/bash pipelineagent \
    && chown pipelineagent:pipelineagent /app

# Install uv for faster Python dependency management
RUN pip install --no-cache-dir uv

# Copy dependency files first (for Docker layer caching)
COPY --chown=pipelineagent:pipelineagent pyproject.toml uv.lock* ./

# Switch to non-root user for dependency installation
USER pipelineagent

# Install Python dependencies (will create .venv owned by pipelineagent)
RUN uv sync --frozen || uv sync

# Copy only necessary application files
COPY --chown=pipelineagent:pipelineagent main.py ./
COPY --chown=pipelineagent:pipelineagent lib/ ./lib/
COPY --chown=pipelineagent:pipelineagent scripts/ ./scripts/
COPY --chown=pipelineagent:pipelineagent .claude/ ./.claude/
COPY --chown=pipelineagent:pipelineagent pipeline-skills.yaml ./
COPY --chown=pipelineagent:pipelineagent skills-registry/ ./skills-registry/

# Set up Python path to find installed packages
ENV PYTHONPATH=/app
ENV PATH="/app/.venv/bin:${PATH}"

# Default command (will be overridden by K8s Job spec)
CMD ["python", "main.py", "--help"]
