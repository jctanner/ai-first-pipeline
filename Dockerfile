FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.cargo/bin/uv /usr/local/bin/uv || \
    mv /root/.local/bin/uv /usr/local/bin/uv || true

ENV PATH="/root/.cargo/bin:/root/.local/bin:${PATH}"

# Copy project files
COPY . .

# Install Python dependencies
RUN uv sync

# Expose dashboard port
EXPOSE 5000

# Default command - run dashboard
CMD ["uv", "run", "python", "main.py", "dashboard", "--port", "5000", "--host", "0.0.0.0"]
