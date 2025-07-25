FROM ghcr.io/astral-sh/uv:0.8.3-bookworm-slim

RUN /usr/sbin/useradd --create-home --shell /bin/bash --user-group python
USER python

WORKDIR /app
COPY --chown=python:python .python-version pyproject.toml uv.lock ./
RUN /usr/local/bin/uv sync --frozen

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE="1" \
    PYTHONUNBUFFERED="1" \
    TZ="America/Chicago"

LABEL org.opencontainers.image.authors="William Jackson <william@subtlecoolness.com>" \
    org.opencontainers.image.description="Journal" \
    org.opencontainers.image.source="https://github.com/williamjacksn/jour" \
    org.opencontainers.image.title="Jour"

COPY --chown=python:python package.json run.py ./
COPY --chown=python:python jour ./jour

ENTRYPOINT ["/usr/local/bin/uv", "run", "run.py"]
