# syntax=docker/dockerfile:1

# --- 1. Front-end assets: Tailwind build + vendored Alpine.js and DM Sans ------
FROM node:22-slim AS assets
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY scripts ./scripts
COPY frontend ./frontend
COPY static ./static
# Tailwind scans templates and Python files for class names.
COPY templates ./templates
COPY apps ./apps
RUN npm run build

# --- 2. Application --------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN useradd --create-home --uid 1000 app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
COPY --from=assets /app/static ./static
# collectstatic needs settings to load; the key is only used for this build step.
RUN DJANGO_SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput

USER app
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
