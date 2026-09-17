# Единый образ портала: собранный фронтенд отдаётся тем же приложением, что и API.
# Одна служба вместо двух — не нужен ни отдельный веб-сервер, ни CORS.
# Используется Railway; для локального запуска с разделением есть docker-compose.yml.

FROM node:22-alpine AS frontend
WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Шрифт с кириллицей нужен для PDF: встроенные шрифты reportlab её не содержат.
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend /build/dist ./static

# Приложение не пишет в файловую систему, поэтому работает под обычным пользователем.
RUN useradd --create-home --uid 10001 portal && chown -R portal:portal /app
USER portal

EXPOSE 8000

# PORT задаёт платформа. --proxy-headers нужен, чтобы в журнал попадал адрес
# сотрудника, а не обратного прокси платформы.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=\"${FORWARDED_ALLOW_IPS:-*}\""]
