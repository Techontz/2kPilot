<?php

namespace App\Http\Controllers\Api;

use App\Exceptions\DomainException;
use App\Http\Controllers\Controller;
use App\Http\Requests\RiskProfileRequest;
use App\Models\AccountSnapshot;
use App\Models\RiskProfile;
use App\Models\Trade;
use App\Models\TradingAccount;
use App\Services\Audit\AuditLogger;
use App\Services\Trading\TradingControl;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class RiskController extends Controller
{
    public function __construct(private readonly AuditLogger $audit, private readonly TradingControl $control) {}

    public function index(Request $request): JsonResponse
    {
        $this->authorize('viewAny', RiskProfile::class);

        return response()->json(RiskProfile::query()->ownedBy($request->user())->withCount('accounts')->orderBy('name')->get());
    }

    public function store(RiskProfileRequest $request): JsonResponse
    {
        $profile = RiskProfile::query()->create($request->validated() + ['user_id' => $request->user()->id]);
        $this->audit->record('risk.profile_created', actor: $request->user(), targetType: 'risk_profile', targetId: $profile->id,
            details: ['name' => $profile->name]);

        return response()->json($profile->refresh(), 201);
    }

    public function update(RiskProfileRequest $request, RiskProfile $profile): JsonResponse
    {
        $before = $profile->only(array_keys($request->validated()));
        $profile->fill($request->validated())->save();
        $changed = array_keys(array_diff_assoc(array_map('json_encode', $profile->only(array_keys($before))), array_map('json_encode', $before)));
        $this->audit->record('risk.profile_updated', actor: $request->user(), targetType: 'risk_profile', targetId: $profile->id,
            details: ['changed' => $changed]);
        if ($changed) { // LIVE was authorised against the limits as they were
            $this->control->revokeLiveIf($profile->user_id, $request->user(), "the risk profile \"{$profile->name}\" was edited",
                fn ($state) => $state->live_authorized_profile_id === $profile->id);
        }

        return response()->json($profile->refresh());
    }

    public function destroy(Request $request, RiskProfile $profile): JsonResponse
    {
        $this->authorize('delete', $profile);
        if ($profile->name === RiskProfile::DEFAULT_NAME) {
            throw DomainException::conflict('The Beginner profile cannot be deleted.');
        }
        if ($profile->accounts()->exists()) {
            throw DomainException::conflict('This profile is assigned to an account. Assign another profile first.');
        }
        $this->audit->record('risk.profile_deleted', actor: $request->user(), targetType: 'risk_profile', targetId: $profile->id,
            details: ['name' => $profile->name]);
        $profile->delete();

        return response()->json(['ok' => true]);
    }

    /** How much of each limit an account is using right now (from stored records). */
    public function usage(TradingAccount $account): JsonResponse
    {
        $this->authorize('view', $account);
        $profile = $account->riskProfile;
        $now = now();
        $dayStart = $now->copy()->startOfDay();
        $weekStart = $now->copy()->startOfWeek();
        $closed = Trade::query()->where('account_id', $account->id)->where('status', 'CLOSED')->whereNotNull('net_pnl');
        $open = Trade::query()->where('account_id', $account->id)->where('status', 'OPEN')->get();
        $realizedToday = (float) (clone $closed)->where('exit_time', '>=', $dayStart)->sum('net_pnl');
        $realizedWeek = (float) (clone $closed)->where('exit_time', '>=', $weekStart)->sum('net_pnl');
        $unrealized = (float) $open->sum(fn ($t) => (float) $t->unrealized_pnl);
        $balance = (float) $account->balance;
        $equity = (float) $account->equity;
        $peak = max((float) AccountSnapshot::query()->where('account_id', $account->id)->max('equity'), $equity);
        $recent = (clone $closed)->orderByDesc('exit_time')->limit(20)->pluck('net_pnl');
        $consecutive = 0;
        foreach ($recent as $pnl) {
            if ((float) $pnl < 0) {
                $consecutive++;
            } else {
                break;
            }
        }
        // Losses in a row among today's (UTC) closed trades: the contract halt rule.
        $streakToday = 0;
        foreach ((clone $closed)->where('exit_time', '>=', $dayStart)->orderByDesc('exit_time')->pluck('net_pnl') as $pnl) {
            if ((float) $pnl >= 0) {
                break;
            }
            $streakToday++;
        }
        $pct = fn (float $loss, float $base) => $base > 0 ? round(max(0, -$loss) / $base * 100, 2) : null;
        $lim = fn (?string $field) => $profile && $profile->{$field} !== null ? (float) $profile->{$field} : null;

        return response()->json([
            'account' => ['id' => $account->id, 'label' => $account->label, 'environment' => $account->environment->value, 'currency' => $account->currency],
            'profile' => $profile,
            'usage' => [
                ['key' => 'daily_loss', 'label' => 'Daily loss', 'used' => $pct($realizedToday + $unrealized, $balance - $realizedToday), 'limit' => $lim('max_daily_loss_pct'), 'unit' => '%'],
                ['key' => 'weekly_loss', 'label' => 'Weekly loss', 'used' => $pct($realizedWeek + $unrealized, $balance - $realizedWeek), 'limit' => $lim('max_weekly_loss_pct'), 'unit' => '%'],
                ['key' => 'drawdown', 'label' => 'Drawdown from peak', 'used' => $peak > 0 ? round(max(0, ($peak - $equity) / $peak * 100), 2) : null, 'limit' => $lim('max_drawdown_pct'), 'unit' => '%'],
                ['key' => 'open_risk', 'label' => 'Open risk', 'used' => $equity > 0 ? round($open->sum(fn ($t) => (float) $t->risk_amount) / $equity * 100, 2) : null, 'limit' => $lim('max_total_risk_pct'), 'unit' => '%'],
                ['key' => 'open_positions', 'label' => 'Open positions', 'used' => $open->count(), 'limit' => $lim('max_open_positions'), 'unit' => ''],
                ['key' => 'exposure', 'label' => 'Total exposure', 'used' => round((float) $open->sum(fn ($t) => (float) $t->volume), 2), 'limit' => $lim('max_total_exposure_lots'), 'unit' => 'lots'],
                ['key' => 'trades_today', 'label' => 'Trades today', 'used' => Trade::query()->where('account_id', $account->id)->where('entry_time', '>=', $dayStart)->count(), 'limit' => $lim('max_trades_per_day'), 'unit' => ''],
                ['key' => 'losing_streak', 'label' => 'Losses in a row', 'used' => $consecutive, 'limit' => $lim('cooldown_after_losses'), 'unit' => ''],
                ['key' => 'daily_loss_amount', 'label' => 'Money lost today', 'used' => round(max(0, -$realizedToday), 2), 'limit' => $lim('max_daily_loss_amount'), 'unit' => $account->currency],
                ['key' => 'losses_in_a_row_today', 'label' => 'Losses in a row today', 'used' => $streakToday, 'limit' => $lim('max_consecutive_losses'), 'unit' => ''],
                ['key' => 'profit_today', 'label' => 'Profit today', 'used' => round($realizedToday, 2), 'limit' => $lim('daily_profit_target_amount'), 'unit' => $account->currency],
            ],
        ]);
    }
}
