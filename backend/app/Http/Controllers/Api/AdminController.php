<?php

namespace App\Http\Controllers\Api;

use App\Enums\AssignmentStatus;
use App\Http\Controllers\Controller;
use App\Models\Strategy;
use App\Models\StrategyAssignment;
use App\Services\Audit\AuditLogger;
use App\Services\Notifier;
use App\Services\Trading\TradingControl;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Gate;

/**
 * Platform operations for admins: the emergency halt that stops every user's
 * trading, and the per-strategy emergency stop that blocks NEW entries from one
 * strategy (and users' copies of it) for everyone. Neither closes positions.
 */
class AdminController extends Controller
{
    public function __construct(
        private readonly TradingControl $control,
        private readonly AuditLogger $audit,
        private readonly Notifier $notifier,
    ) {}

    public function halt(Request $request): JsonResponse
    {
        Gate::authorize('operate-platform');
        $data = $request->validate(['reason' => ['required', 'string', 'max:300']]);
        $this->control->haltPlatform($request->user(), $data['reason']);

        return response()->json($this->control->status($request->user())->toArray());
    }

    public function resume(Request $request): JsonResponse
    {
        Gate::authorize('operate-platform');
        $request->validate(['confirm' => ['accepted']]);
        $this->control->resumePlatform($request->user());

        return response()->json($this->control->status($request->user())->toArray());
    }

    /** Stop new entries from $strategy for everyone (the engine checks it on every signal). */
    public function disableStrategy(Request $request, Strategy $strategy): JsonResponse
    {
        Gate::authorize('operate-platform');
        $data = $request->validate(['reason' => ['required', 'string', 'max:300']]);
        $wasDisabled = $strategy->entriesDisabled();
        $strategy->forceFill([
            'entries_disabled_at' => $strategy->entries_disabled_at ?? now(),
            'entries_disabled_reason' => $data['reason'],
            'entries_disabled_by' => $request->user()->id,
        ])->save();
        $this->audit->record('strategy.entries_disabled', actor: $request->user(), targetType: 'strategy', targetId: $strategy->id,
            details: ['name' => $strategy->name, 'reason' => $data['reason'], 'already_disabled' => $wasDisabled]);
        if (! $wasDisabled) {
            $this->notifyUsers($strategy, 'strategy.entries_disabled',
                "{$strategy->name}: new trades are stopped by an administrator ({$data['reason']}). Open positions are not closed.");
        }

        return response()->json(self::state($strategy));
    }

    /** Lift the stop: the strategy may open trades again (every other rule still applies). */
    public function enableStrategy(Request $request, Strategy $strategy): JsonResponse
    {
        Gate::authorize('operate-platform');
        $request->validate(['confirm' => ['accepted']]);
        $wasDisabled = $strategy->entriesDisabled();
        $strategy->forceFill(['entries_disabled_at' => null, 'entries_disabled_reason' => null, 'entries_disabled_by' => null])->save();
        $this->audit->record('strategy.entries_enabled', actor: $request->user(), targetType: 'strategy', targetId: $strategy->id,
            details: ['name' => $strategy->name, 'was_disabled' => $wasDisabled]);
        if ($wasDisabled) {
            $this->notifyUsers($strategy, 'strategy.entries_enabled', "{$strategy->name}: an administrator lifted the stop on new trades.");
        }

        return response()->json(self::state($strategy));
    }

    public static function state(Strategy $strategy): array
    {
        return [
            'id' => $strategy->id,
            'name' => $strategy->name,
            'entries_disabled' => $strategy->entriesDisabled(),
            'entries_disabled_at' => $strategy->entries_disabled_at?->toIso8601String(),
            'entries_disabled_reason' => $strategy->entries_disabled_reason,
        ];
    }

    /** Tell each user with an enabled assignment of the strategy (or of a copy of it). */
    private function notifyUsers(Strategy $strategy, string $type, string $message): void
    {
        $ids = Strategy::query()->where('id', $strategy->id)->orWhere('copied_from_id', $strategy->id)->pluck('id');
        $accounts = StrategyAssignment::query()->whereIn('strategy_id', $ids)->where('status', AssignmentStatus::Enabled)
            ->with('account:id,user_id')->get()->pluck('account')->filter()->unique('user_id');
        foreach ($accounts as $account) {
            $this->notifier->notify($type, $message, $account->user_id);
        }
    }
}
