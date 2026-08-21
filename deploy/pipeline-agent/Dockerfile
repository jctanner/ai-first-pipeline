# ── Stage 1: Build arch-query with embedded architecture data ────
FROM golang:1.25-bookworm AS arch-query-builder

RUN apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone --depth 1 https://github.com/opendatahub-io/architecture-context.git && \
    cd architecture-context/src/arch-query && \
    GOTOOLCHAIN=auto make build-embedded && \
    cp ../../bin/arch-query /build/arch-query


# ── Stage 2: Build OpenCode from its source repository ──────────
FROM oven/bun:1.3.14-debian AS opencode-builder

ARG OPENCODE_REPO=https://github.com/anomalyco/opencode.git
ARG OPENCODE_REF=dev

RUN apt-get update && apt-get install -y --no-install-recommends git python3 make g++ && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN GIT_SSL_NO_VERIFY=true git clone --depth 1 --branch "${OPENCODE_REF}" "${OPENCODE_REPO}" .

RUN bun install --frozen-lockfile || bun install
ENV OPENCODE_CHANNEL=latest
ENV OPENCODE_VERSION=0.0.0-local
RUN cd packages/opencode && bun run script/build.ts --single --skip-embed-web-ui

RUN ARCH=$(uname -m | sed 's/x86_64/x64/' | sed 's/aarch64/arm64/') \
    && cp packages/opencode/dist/opencode-linux-${ARCH}/bin/opencode /build/opencode


# ── Stage 3: Pipeline agent ─────────────────────────────────────
FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    iproute2 \
    curl \
    nodejs \
    npm \
    ca-certificates \
    strace \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy OpenCode binary built from local source
COPY --from=opencode-builder /build/opencode /usr/local/bin/opencode
RUN chmod +x /usr/local/bin/opencode

WORKDIR /app

# Inject internal CA certificate (extracted at build time by 05b-build-agent.sh)
COPY internal-ca.crt /usr/local/share/ca-certificates/internal-ca.crt
RUN update-ca-certificates

# Copy arch-query binary from builder stage
COPY --from=arch-query-builder /build/arch-query /usr/local/bin/arch-query

# Create non-root user early
RUN useradd -m -s /bin/bash pipelineagent \
    && chown pipelineagent:pipelineagent /app \
    && mkdir -p /home/pipelineagent/.config/opencode \
    && echo '{"plugin":["@mlflow/opencode@0.2.0-rc.1"]}' > /home/pipelineagent/.config/opencode/opencode.json \
    && chown -R pipelineagent:pipelineagent /home/pipelineagent/.config

# Pre-install @mlflow/opencode plugin into OpenCode's cache so it loads instantly.
# The version spec here must match the config in opencode.json exactly — OpenCode
# uses the full spec (including version) as the cache directory name.
RUN mkdir -p "/home/pipelineagent/.cache/opencode/packages/@mlflow/opencode@0.2.0-rc.1" \
    && cd "/home/pipelineagent/.cache/opencode/packages/@mlflow/opencode@0.2.0-rc.1" \
    && echo '{"name":"mlflow-opencode-cache","private":true}' > package.json \
    && npm install --save @mlflow/opencode@0.2.0-rc.1 \
    && chown -R pipelineagent:pipelineagent /home/pipelineagent/.cache

# Install uv for faster Python dependency management
RUN pip install --no-cache-dir uv

# Copy dependency files first (for Docker layer caching)
COPY --chown=pipelineagent:pipelineagent pyproject.toml uv.lock* ./

# Switch to non-root user for dependency installation
USER pipelineagent

# Install Python dependencies (will create .venv owned by pipelineagent)
RUN uv sync --frozen || uv sync

# Install agentic-ci from its source repository.
ARG AGENTIC_CI_REPO=https://github.com/opendatahub-io/agentic-ci.git
ARG AGENTIC_CI_REF=main
RUN uv pip install "git+${AGENTIC_CI_REPO}@${AGENTIC_CI_REF}"

# Copy only necessary application files
COPY --chown=pipelineagent:pipelineagent main.py ./
COPY --chown=pipelineagent:pipelineagent src/ ./src/
COPY --chown=pipelineagent:pipelineagent scripts/ ./scripts/
COPY --chown=pipelineagent:pipelineagent .claude/ ./.claude/
COPY --chown=pipelineagent:pipelineagent var/ ./var/

# Set up Python path to find installed packages
ENV PYTHONPATH=/app
ENV PATH="/app/.venv/bin:${PATH}"

# Default command (will be overridden by K8s Job spec)
CMD ["python", "main.py", "--help"]
