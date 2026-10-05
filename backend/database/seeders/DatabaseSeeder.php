<?php

namespace Database\Seeders;

use Illuminate\Database\Seeder;

/**
 * Migrations already create everything a fresh install needs: the system
 * state row (trading STOPPED) and the conservative default risk profile.
 * Strategies are registered by the trading engine on start-up, and users are
 * created with `php artisan fx:user` — so there is nothing to seed.
 */
class DatabaseSeeder extends Seeder
{
    public function run(): void {}
}
