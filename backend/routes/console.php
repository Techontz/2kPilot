<?php

use Illuminate\Support\Facades\Schedule;

/*
| Scheduler — run `php artisan schedule:work` (make dev does this for you).
| The trading engine itself ticks every couple of seconds; these jobs are
| the supervision and housekeeping around it.
*/

Schedule::command('fx:engine-watchdog')->everyMinute()->withoutOverlapping();
Schedule::command('fx:daily-summary')->dailyAt('21:05')->timezone('UTC');
Schedule::command('fx:prune')->dailyAt('03:30')->timezone('UTC');
Schedule::command('queue:prune-failed --hours=720')->weekly();
