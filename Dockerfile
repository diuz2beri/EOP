FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
COPY pyproject.toml ./
COPY config ./config
COPY src ./src
COPY scripts ./scripts
RUN uv sync --no-dev
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src
CMD ["uvicorn", "pacificeo.main:app", "--host", "0.0.0.0", "--port", "8080"]
