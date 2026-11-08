# One image for every distributed role (api, scheduler, normalizer, workers). Decision 0070.
# Not built in the sandbox that wrote it: build and run it once before relying on it.
FROM python:3.13-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra distributed --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --extra distributed

FROM python:3.13-slim-bookworm
RUN groupadd --system --gid 10001 cc \
    && useradd --system --uid 10001 --gid cc --home-dir /home/cc --create-home cc \
    && mkdir /data \
    && chown cc:cc /data
COPY --from=build --chown=cc:cc /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 CC_DATA_DIR=/data
WORKDIR /app
USER cc
VOLUME ["/data"]
EXPOSE 8765
CMD ["command-center"]
