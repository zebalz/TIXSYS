FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN useradd --create-home --uid 1000 tixsys

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Static files are collected into the image at build time.
RUN SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && mkdir -p /data/media \
    && chown -R tixsys:tixsys /data /app \
    && chmod +x /app/docker/entrypoint.sh

USER tixsys
EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-"]
