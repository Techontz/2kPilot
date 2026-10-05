<?php

namespace App\Console\Commands;

use App\Models\AppNotification;
use App\Models\StrategyEvaluation;
use Illuminate\Console\Command;

/**
 * Scheduled daily. Removes high-volume, low-value rows only:
 * per-bar "no setup" evaluations and read notifications older than the
 * retention window. Trades, orders, the journal and the audit log are never pruned.
 */
class PruneRecords extends Command
{
    protected $signature = 'fx:prune {--days=90}';

    protected $description = 'Prune old strategy evaluations and read notifications';

    public function handle(): int
    {
        $cutoff = now()->subDays(max(7, (int) $this->option('days')));
        $evaluations = StrategyEvaluation::query()->where('outcome', '!=', 'SIGNAL')->where('created_at', '<', $cutoff)->delete();
        $notifications = AppNotification::query()->whereNotNull('read_at')->where('created_at', '<', $cutoff)->delete();
        $this->info("Pruned {$evaluations} evaluations and {$notifications} read notifications older than {$cutoff->toDateString()}.");

        return self::SUCCESS;
    }
}
