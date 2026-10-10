<?php

namespace App\Services\Strategies;

use App\Enums\AssignmentStatus;
use App\Exceptions\DomainException;
use App\Models\Backtest;
use App\Models\Signal;
use App\Models\Strategy;
use App\Models\StrategyAssignment;
use App\Models\StrategyVersion;
use App\Models\Trade;
use App\Models\TradingAccount;
use App\Models\User;
use App\Services\Audit\AuditLogger;
use App\Services\Engine\EngineClient;
use App\Services\Engine\EngineException;
use App\Services\Notifier;
use App\Support\ContractSpec;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\DB;
use Illuminate\Validation\ValidationException;

/**
 * Strategies, immutable versions and assignments.
 *
 *  - Versions are never edited: changing parameters creates version N+1.
 *  - Parameters are validated by the trading engine (it owns each schema).
 *  - Assignments are created PAUSED and enabled deliberately.
 *  - Switching an assignment to another version pauses it again.
 *  - Enabling needs a risk profile on the account.
 *  - Contract settings (App\Support\ContractSpec) are checked against the
 *    broker by the engine; changing them pauses the assignment too.
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
            return Cache::remember('tp.strategy_catalog', 300, fn () => $this->engine->get('/internal/strategies'));
        } catch (EngineException) {
            return [];
        }
    }

    /**
     * What the visual builder offers (indicators, operators, limits) and whether
     * plain-English drafting is configured. Cached; the engine owns it.
     */
    public function rulesCatalog(): array
    {
        return Cache::remember('tp.rules_catalog', 300, fn () => $this->engine->get('/internal/strategies/catalog'));
    }

    /**
     * Ask the engine to validate parameters (a rule set for "rules" strategies).
     * Invalid → EngineException 422 whose problems() list every issue in plain English.
     *
     * @return array{parameters: array, code_version: string, rules_text: ?string, notes: array}
     */
    public function validateParameters(string $key, array $parameters): array
    {
        $validated = $this->engine->post("/internal/strategies/{$key}/validate", ['parameters' => (object) $parameters]);

        return $validated + ['rules_text' => null, 'notes' => []];
    }

    /** A new rule-based strategy owned by $actor, with version 1. */
    public function createRules(User $actor, string $name, string $description, array $rules, string $source, ?string $notes = null): Strategy
    {
        $validated = $this->validateParameters(Strategy::RULES, $rules);
        $strategy = DB::transaction(function () use ($actor, $name, $description, $validated, $source, $notes) {
            $strategy = Strategy::query()->create([
                'user_id' => $actor->id,
                'key' => Strategy::RULES,
                'name' => mb_substr(trim($name), 0, 120),
                'description' => mb_substr($description, 0, 2000),
                'summary' => mb_substr((string) $validated['rules_text'], 0, 300),
                'source' => $source,
            ]);
            $this->insertVersion($strategy, 1, $validated, $notes ?? match ($source) {
                'ai' => 'Drafted from a plain-English description, reviewed by the user',
                'import' => 'Imported',
                default => 'Created in the rule builder',
            }, $actor);

            return $strategy;
        });
        $this->audit->record('strategy.created', actor: $actor, targetType: 'strategy', targetId: $strategy->id,
            details: ['source' => $source, 'name' => $strategy->name]);

        return $strategy;
    }

    public function createVersion(Strategy $strategy, array $parameters, string $notes, User $actor): StrategyVersion
    {
        $validated = $this->validateParameters($strategy->key, $parameters);
        $version = DB::transaction(function () use ($strategy, $validated, $notes, $actor) {
            $next = (int) StrategyVersion::query()->where('strategy_id', $strategy->id)->lockForUpdate()->max('version') + 1;

            return $this->insertVersion($strategy, $next, $validated, $notes, $actor);
        });
        $this->audit->record('strategy.version_created', actor: $actor, targetType: 'strategy', targetId: $strategy->id,
            details: ['version' => $version->version]);

        return $version;
    }

    private function insertVersion(Strategy $strategy, int $version, array $validated, string $notes, User $actor): StrategyVersion
    {
        return StrategyVersion::query()->create([
            'strategy_id' => $strategy->id,
            'version' => $version,
            'code_version' => $validated['code_version'],
            'parameters' => $validated['parameters'],
            'rules_text' => $validated['rules_text'] ?? null,
            'notes' => mb_substr($notes, 0, 500),
            'created_by' => $actor->id,
        ]);
    }

    public function rename(Strategy $strategy, array $changes, User $actor): Strategy
    {
        $before = $strategy->only(['name', 'description']);
        $strategy->fill(array_intersect_key($changes, array_flip(['name', 'description'])))->save();
        $this->audit->record('strategy.updated', actor: $actor, targetType: 'strategy', targetId: $strategy->id,
            details: ['from' => $before['name'], 'to' => $strategy->name]);

        return $strategy;
    }

    /**
     * Delete a strategy, or archive it when history points at it (trades,
     * signals, backtests). Refused while one of its assignments is enabled.
     *
     * @return 'deleted'|'archived'
     */
    public function remove(Strategy $strategy, User $actor): string
    {
        if ($strategy->assignments()->where('status', AssignmentStatus::Enabled)->exists()) {
            throw DomainException::conflict('Pause every assignment of this strategy before deleting it.', 'strategy_in_use');
        }
        $versionIds = $strategy->versions()->pluck('id');
        $hasHistory = Trade::query()->whereIn('strategy_version_id', $versionIds)->exists()
            || Signal::query()->whereIn('strategy_version_id', $versionIds)->exists()
            || Backtest::query()->whereIn('strategy_version_id', $versionIds)->exists();
        $outcome = $hasHistory ? 'archived' : 'deleted';
        DB::transaction(function () use ($strategy, $hasHistory) {
            if ($hasHistory) {
                // Free the name for a new strategy; the history keeps the exact versions.
                $suffix = ' (archived '.now()->utc()->format('Y-m-d H:i').')';
                $strategy->forceFill([
                    'archived_at' => now(),
                    'name' => mb_substr($strategy->name, 0, 120 - mb_strlen($suffix)).$suffix,
                ])->save();

                return;
            }
            $strategy->assignments()->delete(); // paused ones (enabled ones were refused above)
            $strategy->delete();
        });
        $this->audit->record("strategy.{$outcome}", actor: $actor, targetType: 'strategy', targetId: $strategy->id,
            details: ['name' => $strategy->name]);

        return $outcome;
    }

    /** A user's own copy of a strategy: same implementation, v1 = the source's latest parameters. */
    public function copy(Strategy $source, string $name, User $actor): Strategy
    {
        $latest = $source->versions()->reorder('version', 'desc')->firstOrFail();
        $copy = DB::transaction(function () use ($source, $name, $actor, $latest) {
            $copy = Strategy::query()->create([
                'user_id' => $actor->id,
                'key' => $source->key,
                'name' => mb_substr(trim($name), 0, 120),
                'description' => $source->description,
                'summary' => $source->summary,
                'details' => $source->details,
                'source' => 'copy',
                'copied_from_id' => $source->id,
            ]);
            StrategyVersion::query()->create([
                'strategy_id' => $copy->id,
                'version' => 1,
                'code_version' => $latest->code_version,
                'parameters' => $latest->parameters,
                'rules_text' => $latest->rules_text,
                'notes' => mb_substr("Copied from {$source->name} v{$latest->version}", 0, 500),
                'created_by' => $actor->id,
            ]);

            return $copy;
        });
        $this->audit->record('strategy.copied', actor: $actor, targetType: 'strategy', targetId: $copy->id,
            details: ['from' => $source->id, 'version' => $latest->version]);

        return $copy;
    }

    /**
     * Ask the engine whether the broker offers this contract on the symbol.
     * Returns [spec, check]: a broker refusal is a validation error; when the
     * engine cannot answer, the spec is kept unverified (the assignment stays
     * PAUSED and the engine re-checks before every trade). SPOT is not checked.
     *
     * @return array{0: array, 1: array{verified: bool, detail?: string}|null}
     */
    public function checkContract(TradingAccount $account, string $symbol, array $spec): array
    {
        if (ContractSpec::isSpot($spec)) {
            return [$spec, null];
        }
        try {
            $result = $this->engine->post("/internal/accounts/{$account->id}/contracts/validate", ['symbol' => trim($symbol), 'contract' => (object) $spec]);
        } catch (EngineException $e) {
            if ($e->status === 422) {
                throw ValidationException::withMessages(['contract_family' => $e->getMessage()]);
            }

            return [$spec, ['verified' => false, 'detail' => $e->getMessage()]];
        }
        $checked = $result['contract'] ?? null;
        if (is_array($checked) && ($checked['contract_family'] ?? null) === $spec['contract_family']) {
            $spec = ContractSpec::normalize($checked); // the broker's rounding (e.g. stake precision)
        }

        return [$spec, ['verified' => true]];
    }

    public function assign(StrategyVersion $version, TradingAccount $account, string $symbol, User $actor, array $contract): StrategyAssignment
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
        ] + $contract);
        $this->audit->record('strategy.assigned', actor: $actor, targetType: 'strategy_assignment', targetId: $assignment->id,
            details: ['account' => $account->label, 'symbol' => $symbol, 'version' => $version->version, 'contract' => $contract['contract_family']]);

        return $assignment;
    }

    /**
     * Create or update the assignment of $strategy's LATEST version on
     * account + symbol with $contract, then enable it (same rules as
     * setStatus: the account needs a risk profile).
     */
    public function activate(Strategy $strategy, TradingAccount $account, string $symbol, array $contract, User $actor, string $reason = ''): StrategyAssignment
    {
        if ($account->risk_profile_id === null) {
            throw DomainException::forbidden('Assign a risk profile to the account first.', 'risk_profile_required');
        }
        $version = $strategy->versions()->reorder('version', 'desc')->firstOrFail();
        $symbol = trim($symbol);
        $assignment = DB::transaction(function () use ($strategy, $account, $symbol, $contract, $version) {
            $assignment = StrategyAssignment::query()->where('account_id', $account->id)
                ->where('strategy_id', $strategy->id)->where('symbol', $symbol)->lockForUpdate()->first();
            $values = ['strategy_version_id' => $version->id] + $contract;

            if ($assignment !== null) {
                $assignment->forceFill($values)->save();

                return $assignment;
            }

            return StrategyAssignment::query()->create($values + [
                'strategy_id' => $strategy->id,
                'account_id' => $account->id,
                'symbol' => $symbol,
                'status' => AssignmentStatus::Paused,
            ]);
        });
        $this->audit->record('strategy.activated', actor: $actor, targetType: 'strategy_assignment', targetId: $assignment->id,
            details: ['account' => $account->label, 'symbol' => $symbol, 'version' => $version->version, 'contract' => $contract['contract_family']]);
        $assignment->setRelation('account', $account);

        return $this->setStatus($assignment, AssignmentStatus::Enabled, $actor, $reason);
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
            $this->notifier->notify('strategy.paused', "{$assignment->symbol}: {$assignment->status_reason}", $assignment->account?->user_id, $assignment->account_id);
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

    public function changeContract(StrategyAssignment $assignment, array $contract, User $actor): StrategyAssignment
    {
        $before = ContractSpec::fromAssignment($assignment);
        $assignment->forceFill($contract + [
            'status' => AssignmentStatus::Paused, // a new configuration must be re-enabled deliberately
            'status_reason' => 'Contract settings changed — enable it again to trade',
        ])->save();
        $this->audit->record('strategy.contract_changed', actor: $actor, targetType: 'strategy_assignment', targetId: $assignment->id,
            details: ['symbol' => $assignment->symbol, 'from' => $before, 'to' => $contract]);

        return $assignment;
    }

    public function unassign(StrategyAssignment $assignment, User $actor): void
    {
        $this->audit->record('strategy.unassigned', actor: $actor, targetType: 'strategy_assignment', targetId: $assignment->id,
            details: ['symbol' => $assignment->symbol]);
        $assignment->delete();
    }
}
