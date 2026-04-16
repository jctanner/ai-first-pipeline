FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        nodejs \
        npm \
        git \
        ca-certificates \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create non-root user for agent
RUN useradd -m -s /bin/bash agent

# Create directories
RUN mkdir -p /home/agent/.claude \
             /home/agent/.config/gcloud \
             /home/agent/workspace

# Set proper ownership
RUN chown -R agent:agent /home/agent

# Environment variables
ENV HOME=/home/agent \
    GOOGLE_APPLICATION_CREDENTIALS=/home/agent/.config/gcloud/credentials.json \
    PATH="/home/agent/.local/bin:${PATH}"

# Switch to agent user
USER agent

# Set working directory
WORKDIR /home/agent/workspace

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD [ "test", "-f", "/home/agent/.config/gcloud/credentials.json" ] || exit 1

# Keep container alive for kubectl exec usage
CMD ["sleep", "infinity"]
