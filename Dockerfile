FROM ghcr.io/astral-sh/uv:0.9.18-trixie-slim

RUN /usr/sbin/useradd --create-home --shell /bin/bash --user-group python
USER python

WORKDIR /app
COPY --chown=python:python .python-version pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE="1" \
    PYTHONUNBUFFERED="1" \
    TZ="America/Chicago"

LABEL org.opencontainers.image.authors="William Jackson <william@subtlecoolness.com>" \
    org.opencontainers.image.description="Journal" \
    org.opencontainers.image.source="https://github.com/williamjacksn/jour" \
    org.opencontainers.image.title="Jour"

COPY --chown=python:python cli.py package.json run.py ./
COPY --chown=python:python jour ./jour

ENTRYPOINT ["uv", "run", "--no-sync", "run.py"]
