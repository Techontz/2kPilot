FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install .

RUN useradd --create-home --uid 10001 fxrobot
USER fxrobot

# Internal API for Laravel + the trading loop. The schema is created by Laravel
# (php artisan migrate), never by this service.
EXPOSE 8431
CMD ["fxrobot", "serve", "--host", "0.0.0.0", "--port", "8431"]
