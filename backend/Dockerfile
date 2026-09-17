FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Шрифт с кириллицей нужен для PDF: встроенные шрифты reportlab её не содержат.
RUN apt-get update  && apt-get install -y --no-install-recommends fonts-dejavu-core  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Схему накатывает Alembic, затем стартует приложение (оно досеивает матрицу из ТЗ).
# --forwarded-allow-ips: без него uvicorn доверяет только 127.0.0.1 и отбрасывает
# X-Forwarded-For от nginx, из-за чего в журнал попадал бы адрес контейнера.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=\"${FORWARDED_ALLOW_IPS:-*}\""]
