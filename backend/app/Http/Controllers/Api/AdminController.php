<?php

namespace App\Http\Controllers\Api;

use App\Enums\AssignmentStatus;
use App\Exceptions\DomainException;
use App\Http\Controllers\Controller;
use App\Models\Strategy;
use App\Models\StrategyAssignment;
use App\Models\User;
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

    /** Every user, those waiting for approval first. */
    public function users(Request $request): JsonResponse
    {
        Gate::authorize('operate-platform');
        $users = User::query()
            ->orderByRaw('approved_at IS NULL DESC')
            ->orderByDesc('created_at')
            ->limit(500)
            ->get()
            ->map(fn (User $u) => self::userState($u));

        return response()->json(['users' => $users]);
    }

    /** Let a new sign-up into the dashboard. */
    public function approveUser(Request $request, User $user): JsonResponse
    {
        Gate::authorize('operate-platform');
        if ($user->approved_at === null) {
            $user->forceFill(['approved_at' => now(), 'approved_by' => $request->user()->id])->save();
            $this->audit->record('user.approved', actor: $request->user(), targetType: 'user', targetId: $user->id,
                details: ['email' => $user->email]);
            $this->notifier->notify('user.approved', 'Your 2kPilot account is approved. Welcome!', $user->id);
        }

        return response()->json(self::userState($user));
    }

    /** Sign the user out everywhere and refuse their logins (nothing is deleted). */
    public function disableUser(Request $request, User $user): JsonResponse
    {
        Gate::authorize('operate-platform');
        if ($user->is($request->user())) {
            throw DomainException::conflict('You cannot disable your own account.', 'cannot_disable_self');
        }
        if ($user->is_active) {
            $user->forceFill(['is_active' => false])->save(); // ends sessions and mobile tokens
            $this->audit->record('user.disabled', actor: $request->user(), targetType: 'user', targetId: $user->id,
                details: ['email' => $user->email]);
        }

        return response()->json(self::userState($user));
    }

    public function enableUser(Request $request, User $user): JsonResponse
    {
        Gate::authorize('operate-platform');
        if (! $user->is_active) {
            $user->forceFill(['is_active' => true])->save();
            $this->audit->record('user.enabled', actor: $request->user(), targetType: 'user', targetId: $user->id,
                details: ['email' => $user->email]);
        }

        return response()->json(self::userState($user));
    }

    public static function userState(User $user): array
    {
        return [
            'id' => $user->id,
            'name' => $user->name,
            'email' => $user->email,
            'role' => $user->role->value,
            'is_active' => $user->is_active,
            'approved' => $user->isApproved(),
            'approved_at' => $user->approved_at?->toIso8601String(),
            'created_at' => $user->created_at?->toIso8601String(),
            'last_login_at' => $user->last_login_at?->toIso8601String(),
        ];
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
