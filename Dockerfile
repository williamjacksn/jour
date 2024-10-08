FROM python:3.13-slim

RUN /usr/sbin/useradd --create-home --shell /bin/bash --user-group python

USER python
RUN /usr/local/bin/python -m venv /home/python/venv

COPY --chown=python:python requirements.txt /home/python/jour/requirements.txt
RUN /home/python/venv/bin/pip install --no-cache-dir --requirement /home/python/jour/requirements.txt

ENV PATH="/home/python/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE="1" \
    PYTHONUNBUFFERED="1" \
    TZ="America/Chicago"

WORKDIR /home/python/jour
ENTRYPOINT ["/home/python/venv/bin/python"]
CMD ["/home/python/jour/run.py"]

LABEL org.opencontainers.image.authors="William Jackson <william@subtlecoolness.com>" \
      org.opencontainers.image.description="Journal" \
      org.opencontainers.image.source="https://github.com/williamjacksn/jour" \
      org.opencontainers.image.title="Jour"

COPY --chown=python:python run.py /home/python/jour/run.py
COPY --chown=python:python jour /home/python/jour/jour
