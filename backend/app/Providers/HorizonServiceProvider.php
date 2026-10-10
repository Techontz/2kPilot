<?php

namespace App\Providers;

use App\Models\User;
use Illuminate\Support\Facades\Gate;
use Laravel\Horizon\Horizon;
use Laravel\Horizon\HorizonApplicationServiceProvider;

/**
 * Horizon (queue dashboard at /horizon). Queues: "default", "notifications"
 * and "backtests" (long-running, see config/horizon.php).
 */
class HorizonServiceProvider extends HorizonApplicationServiceProvider
{
    /** Only active administrators may open the dashboard — in every environment. */
    protected function gate(): void
    {
        Gate::define('viewHorizon', fn (?User $user = null) => $user !== null && $user->is_active && $user->isAdmin());
    }

    /** Unlike Horizon's default, the local environment is NOT open to everyone. */
    protected function authorization()
    {
        $this->gate();
        Horizon::auth(fn ($request) => Gate::check('viewHorizon', [$request->user()]));
    }
}
