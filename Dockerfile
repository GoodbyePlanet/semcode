FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install Python dependencies (fails loudly on lockfile drift instead of silently re-resolving)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-editable

# Copy server source. config.yaml is intentionally not baked in — mount it at
# runtime (see docker-compose.yaml) if you use it; without one, load_services()
# treats "no config.yaml" as zero configured services, and self-registered (ad-hoc)
# services still work.
COPY server/ ./server/

FROM python:3.12-slim AS runtime

WORKDIR /app

COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8090

CMD ["python", "-m", "server.main"]
