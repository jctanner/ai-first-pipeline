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

# The dashboard talks to the OpenShell gateway through its Python SDK. The
# SDK's generated protobuf modules are intentionally not committed upstream;
# generate them from the pinned checkout during the image build.
COPY --chown=dashboarduser:dashboarduser checkouts/openshell/python/ /opt/openshell/python/
COPY --chown=dashboarduser:dashboarduser checkouts/openshell/proto/ /opt/openshell/proto/
COPY --chown=dashboarduser:dashboarduser checkouts/openshell/tasks/scripts/generate_python_proto.py /opt/openshell/tasks/scripts/generate_python_proto.py
RUN cd /opt/openshell && /app/.venv/bin/python /opt/openshell/tasks/scripts/generate_python_proto.py

# Copy only necessary application files
COPY --chown=dashboarduser:dashboarduser main.py ./
COPY --chown=dashboarduser:dashboarduser src/ ./src/
COPY --chown=dashboarduser:dashboarduser scripts/ ./scripts/
COPY --chown=dashboarduser:dashboarduser var/ ./var/

# Set up Python path to find installed packages
ENV PYTHONPATH=/app:/opt/openshell/python
ENV PATH="/app/.venv/bin:${PATH}"

# Expose dashboard port
EXPOSE 5000

# Default command - run dashboard
CMD ["uv", "run", "python", "main.py", "dashboard", "--port", "5000", "--host", "0.0.0.0"]
