FROM php:8.4-cli

RUN apt-get update && apt-get install -y --no-install-recommends git unzip libzip-dev libicu-dev \
    && docker-php-ext-install pdo_mysql bcmath intl zip pcntl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer

WORKDIR /app
COPY composer.json composer.lock ./
RUN composer install --no-dev --no-scripts --no-autoloader --no-interaction
COPY . .
RUN composer dump-autoload --optimize --no-dev && useradd --create-home --uid 10001 fxrobot && chown -R fxrobot storage bootstrap/cache
USER fxrobot

EXPOSE 8421
# Migrations run first; then the API. Queue worker and scheduler run as separate services.
CMD ["sh", "-c", "php artisan migrate --force && php artisan serve --host=0.0.0.0 --port=8421"]
