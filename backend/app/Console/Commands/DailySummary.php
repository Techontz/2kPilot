<?php

namespace App\Console\Commands;

use App\Models\Trade;
use App\Models\TradingAccount;
use App\Services\Notifier;
use Illuminate\Console\Command;

/** Scheduled each evening (UTC): one notification per account that traded today. */
class DailySummary extends Command
{
    protected $signature = 'fx:daily-summary';

    protected $description = 'Post a daily P/L summary notification per account';

    public function handle(Notifier $notifier): int
    {
        $start = now()->startOfDay();
        foreach (TradingAccount::query()->get() as $account) {
            $closed = Trade::query()->where('account_id', $account->id)->where('status', 'CLOSED')->where('exit_time', '>=', $start)->whereNotNull('net_pnl');
            $count = (clone $closed)->count();
            if ($count === 0) {
                continue;
            }
            $net = round((float) (clone $closed)->sum('net_pnl'), 2);
            $wins = (clone $closed)->where('net_pnl', '>', 0)->count();
            $label = $account->isPaper() ? "{$account->label} (PAPER)" : "{$account->label} ({$account->environment->value})";
            $notifier->notify('report.daily', "{$label}: {$count} closed trade(s), {$wins} winner(s), net ".($net >= 0 ? '+' : '')."{$net} {$account->currency} today.", $account->id);
        }

        return self::SUCCESS;
    }
}
