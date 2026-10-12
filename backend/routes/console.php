<?php

use Illuminate\Support\Facades\Schedule;

/*
| Scheduler — run `php artisan schedule:work` (make dev does this for you).
| The trading engine itself ticks every couple of seconds; these jobs are
| the supervision and housekeeping around it.
*/

Schedule::command('tp:engine-watchdog')->everyMinute()->withoutOverlapping();
// Phone pushes for notifications the trading engine writes itself (no-op until FCM is configured).
Schedule::command('tp:push-notifications')->everyFifteenSeconds()->withoutOverlapping();
Schedule::command('tp:daily-summary')->dailyAt('21:05')->timezone('UTC');
Schedule::command('tp:prune')->dailyAt('03:30')->timezone('UTC');
Schedule::command('queue:prune-failed --hours=720')->weekly();
