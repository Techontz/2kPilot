FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY alembic.ini ./
RUN pip install .

RUN useradd --create-home --uid 10001 fxrobot
USER fxrobot

EXPOSE 8000
# Apply migrations, then serve. Readiness (/api/v1/health/ready) fails if
# the schema is behind, so a half-migrated deploy never receives traffic.
CMD ["sh", "-c", "alembic upgrade head && uvicorn fxrobot.main:create_app --factory --host 0.0.0.0 --port 8000 --no-proxy-headers"]
