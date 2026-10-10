<?php

namespace Database\Seeders;

use Illuminate\Database\Seeder;

/**
 * Migrations already create everything a fresh install needs: the platform
 * state row (not halted). Each user's Beginner risk profile and trading state
 * (STOPPED, DEMO) are created at sign-up or by `php artisan tp:user`, and
 * strategies are registered by the trading engine on start-up — so there is
 * nothing to seed.
 */
class DatabaseSeeder extends Seeder
{
    public function run(): void {}
}
