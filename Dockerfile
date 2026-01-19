# syntax=docker/dockerfile:1

# =============================================================================
# Multi-stage Dockerfile for json-rpc-scan
# Supports: linux/amd64, linux/arm64
# =============================================================================

ARG PYTHON_VERSION=3.13

# -----------------------------------------------------------------------------
# Stage: UV binary
# -----------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:0.9.26 AS uv

# -----------------------------------------------------------------------------
# Stage 1: Build stage
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# Install uv from the uv stage
COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app

# Copy files needed for build (README.md required by hatchling)
COPY pyproject.toml README.md uv.lock* ./
COPY src/ ./src/

# Create virtual environment and install the package
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install .

# -----------------------------------------------------------------------------
# Stage 2: Production stage
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS production

# Labels for OCI image spec
LABEL org.opencontainers.image.title="json-rpc-scan" \
      org.opencontainers.image.description="Scans Ethereum (EVM) Blocks via JSON-RPC and looks for client diffs" \
      org.opencontainers.image.source="https://github.com/chase/json-rpc-scan" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.authors="Chase Wright"

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Create non-root user for security
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

# Copy virtual environment from builder (use --link for efficiency)
COPY --link --from=builder /opt/venv /opt/venv

WORKDIR /app

# Create output directory with correct ownership
RUN mkdir -p /app/outputs && chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Default command
ENTRYPOINT ["json-rpc-scan"]
CMD ["--help"]

# -----------------------------------------------------------------------------
# Stage 3: Development stage (optional, for local development)
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS development

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

# Install uv
COPY --from=uv /uv /usr/local/bin/uv

# Install development tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy all source files
COPY . .

# Create virtual environment and install all dependencies including dev
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install -e ".[dev]"

# Default command for development
CMD ["bash"]
