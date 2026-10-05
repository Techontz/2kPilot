<?php

namespace App\Services\Strategies;

use App\Enums\AssignmentStatus;
use App\Exceptions\DomainException;
use App\Models\Strategy;
use App\Models\StrategyAssignment;
use App\Models\StrategyVersion;
use App\Models\TradingAccount;
use App\Models\User;
use App\Services\Audit\AuditLogger;
use App\Services\Engine\EngineClient;
use App\Services\Engine\EngineException;
use App\Services\Notifier;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\DB;

/**
 * Strategies, immutable versions and assignments.
 *
 *  - Versions are never edited: changing parameters creates version N+1.
 *  - Parameters are validated by the trading engine (it owns each schema).
 *  - Assignments are created PAUSED and enabled deliberately.
 *  - Switching an assignment to another version pauses it again.
 *  - Enabling needs a risk profile on the account.
 */
class StrategyService
{
    public function __construct(
        private readonly EngineClient $engine,
        private readonly AuditLogger $audit,
        private readonly Notifier $notifier,
    ) {}

    /** Implementation catalogue (parameter schemas) from the engine; cached briefly. */
    public function catalog(): array
    {
        try {
            return Cache::remember('fx.strategy_catalog', 300, fn () => $this->engine->get('/internal/strategies'));
        } catch (EngineException) {
            return [];
        }
    }

    public function createVersion(Strategy $strategy, array $parameters, string $notes, User $actor): StrategyVersion
    {
        $validated = $this->engine->post("/internal/strategies/{$strategy->key}/validate", ['parameters' => (object) $parameters]);
        $version = DB::transaction(function () use ($strategy, $validated, $notes, $actor) {
            $next = (int) StrategyVersion::query()->where('strategy_id', $strategy->id)->lockForUpdate()->max('version') + 1;

            return StrategyVersion::query()->create([
                'strategy_id' => $strategy->id,
                'version' => $next,
                'code_version' => $validated['code_version'],
                'parameters' => $validated['parameters'],
                'notes' => mb_substr($notes, 0, 500),
                'created_by' => $actor->id,
            ]);
        });
        $this->audit->record('strategy.version_created', actor: $actor, targetType: 'strategy', targetId: $strategy->id,
            details: ['version' => $version->version]);

        return $version;
    }

    public function assign(StrategyVersion $version, TradingAccount $account, string $symbol, User $actor): StrategyAssignment
    {
        $symbol = trim($symbol);
        $exists = StrategyAssignment::query()->where('account_id', $account->id)
            ->where('strategy_id', $version->strategy_id)->where('symbol', $symbol)->exists();
        if ($exists) {
            throw DomainException::conflict('This strategy already runs on that symbol for this account.');
        }
        $assignment = StrategyAssignment::query()->create([
            'strategy_id' => $version->strategy_id,
            'strategy_version_id' => $version->id,
            'account_id' => $account->id,
            'symbol' => $symbol,
            'status' => AssignmentStatus::Paused, // never trades merely because it was created
            'status_reason' => 'Created paused — enable it deliberately',
        ]);
        $this->audit->record('strategy.assigned', actor: $actor, targetType: 'strategy_assignment', targetId: $assignment->id,
            details: ['account' => $account->label, 'symbol' => $symbol, 'version' => $version->version]);

        return $assignment;
    }

    public function setStatus(StrategyAssignment $assignment, AssignmentStatus $status, User $actor, string $reason = ''): StrategyAssignment
    {
        if ($status === AssignmentStatus::Enabled && $assignment->account?->risk_profile_id === null) {
            throw DomainException::forbidden('Assign a risk profile to the account first.', 'risk_profile_required');
        }
        $assignment->forceFill([
            'status' => $status,
            'status_reason' => mb_substr($reason ?: (($status === AssignmentStatus::Enabled ? 'Enabled' : 'Paused')." by {$actor->email}"), 0, 300),
        ])->save();
        $this->audit->record('strategy.'.($status === AssignmentStatus::Enabled ? 'enabled' : 'paused'),
            actor: $actor, targetType: 'strategy_assignment', targetId: $assignment->id, details: ['symbol' => $assignment->symbol]);
        if ($status === AssignmentStatus::Paused) {
            $this->notifier->notify('strategy.paused', "{$assignment->symbol}: {$assignment->status_reason}", $assignment->account_id);
        }

        return $assignment;
    }

    public function switchVersion(StrategyAssignment $assignment, StrategyVersion $version, User $actor): StrategyAssignment
    {
        if ($version->strategy_id !== $assignment->strategy_id) {
            throw new DomainException('That version belongs to a different strategy.');
        }
        $assignment->forceFill([
            'strategy_version_id' => $version->id,
            'status' => AssignmentStatus::Paused, // a new configuration must be re-enabled deliberately
            'status_reason' => "Switched to v{$version->version} — enable it again to trade",
        ])->save();
        $this->audit->record('strategy.modified', actor: $actor, targetType: 'strategy_assignment', targetId: $assignment->id,
            details: ['version' => $version->version]);

        return $assignment;
    }

    public function unassign(StrategyAssignment $assignment, User $actor): void
    {
        $this->audit->record('strategy.unassigned', actor: $actor, targetType: 'strategy_assignment', targetId: $assignment->id,
            details: ['symbol' => $assignment->symbol]);
        $assignment->delete();
    }
}
