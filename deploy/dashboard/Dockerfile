FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create non-root user
RUN useradd -m -s /bin/bash dashboarduser \
    && chown dashboarduser:dashboarduser /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency files first (for Docker layer caching)
COPY --chown=dashboarduser:dashboarduser pyproject.toml uv.lock* ./

# Switch to non-root user for dependency installation
USER dashboarduser

# Install Python dependencies (will create .venv owned by dashboarduser)
RUN uv sync --frozen || uv sync

# Copy only necessary application files
COPY --chown=dashboarduser:dashboarduser main.py ./
COPY --chown=dashboarduser:dashboarduser lib/ ./lib/
COPY --chown=dashboarduser:dashboarduser pipeline-skills.yaml ./

# Set up Python path to find installed packages
ENV PYTHONPATH=/app
ENV PATH="/app/.venv/bin:${PATH}"

# Expose dashboard port
EXPOSE 5000

# Default command - run dashboard
CMD ["uv", "run", "python", "main.py", "dashboard", "--port", "5000", "--host", "0.0.0.0"]
