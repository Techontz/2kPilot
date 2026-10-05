# 2kFX backend (Laravel)

The primary application: REST API for the dashboard, sign-in with MFA, policies, validation, audit log, Broker Center (encrypted credentials, Deriv OAuth), risk profiles, strategy versions and assignments, analytics, journal, notifications, queue jobs (backtests) and the scheduler (engine watchdog, daily summary, pruning). It owns the MySQL schema.

```bash
php artisan migrate              # schema
php artisan fx:user              # create a login
php artisan fx:keys              # shared secrets for backend + trading engine
php artisan serve --port=8421    # API
php artisan queue:work           # backtests
php artisan schedule:work        # watchdog, summaries, pruning
php artisan test                 # tests (MySQL database twokfx_test, see phpunit.xml)
```

Where things are: `routes/api.php`, `app/Http/Controllers/Api`, `app/Services` (Engine client, Brokers, Trading control, Analytics, MFA, Audit), `app/Policies`, `config/fx.php`, `config/brokers.php`. See `../docs/`.
