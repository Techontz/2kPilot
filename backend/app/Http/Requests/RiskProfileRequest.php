<?php

namespace App\Http\Requests;

use App\Models\RiskProfile;
use Illuminate\Foundation\Http\FormRequest;
use Illuminate\Validation\Rule;
use Illuminate\Validation\Validator;

/**
 * Risk limits — the same rules the trading engine enforces in
 * trading-engine/src/fxrobot/risk_engine/limits.py (RiskLimits.validate).
 * An empty optional field means "this limit is off"; risk per trade, the
 * allowed sessions, the data-age limit and the contract stake are mandatory.
 * Pip/lot limits apply to SPOT trades; the stake limits (account currency)
 * to Deriv contracts (Rise/Fall, Multipliers).
 */
class RiskProfileRequest extends FormRequest
{
    public function authorize(): bool
    {
        $profile = $this->route('profile');

        return $profile ? $this->user()->can('update', $profile) : $this->user()->can('create', RiskProfile::class);
    }

    public function rules(): array
    {
        $pct = ['nullable', 'numeric', 'gt:0', 'max:100'];
        $lots = ['nullable', 'numeric', 'gt:0', 'max:100000'];
        $pips = ['nullable', 'numeric', 'min:0', 'max:100000'];
        $count = ['nullable', 'integer', 'min:1', 'max:100000'];

        return [
            // Names are unique per user.
            'name' => ['required', 'string', 'max:120', Rule::unique('risk_profiles', 'name')
                ->where('user_id', $this->route('profile')?->user_id ?? $this->user()->id)->ignore($this->route('profile'))],
            'risk_per_trade_pct' => ['required', 'numeric', 'min:0.01', 'max:5'],
            'max_position_lots' => $lots,
            'max_open_positions' => $count,
            'max_positions_per_symbol' => $count,
            'max_symbol_exposure_lots' => $lots,
            'max_total_exposure_lots' => $lots,
            'max_total_risk_pct' => $pct,
            'max_daily_loss_pct' => $pct,
            'max_weekly_loss_pct' => $pct,
            'max_drawdown_pct' => $pct,
            'max_trades_per_day' => $count,
            'max_spread_pips' => $pips,
            'max_slippage_pips' => $pips,
            'min_stop_pips' => $pips,
            'max_stop_pips' => $pips,
            'min_reward_risk' => ['nullable', 'numeric', 'min:0', 'max:50'],
            'allowed_sessions' => ['present', 'array'],
            'allowed_sessions.*' => [Rule::in(['ASIA', 'LONDON', 'OVERLAP', 'NEW_YORK'])],
            'trading_hours_start' => ['nullable', 'required_with:trading_hours_end', 'date_format:H:i'],
            'trading_hours_end' => ['nullable', 'required_with:trading_hours_start', 'date_format:H:i'],
            'cooldown_after_losses' => $count,
            'cooldown_minutes' => $count,
            'max_data_age_seconds' => ['required', 'integer', 'min:1', 'max:86400'],
            'stake_amount' => ['required', 'numeric', 'gt:0', 'max:100000'],
            'max_stake_amount' => ['nullable', 'numeric', 'gt:0', 'max:100000'],
            'max_daily_loss_amount' => ['nullable', 'numeric', 'gt:0', 'max:100000000'],
            'max_consecutive_losses' => $count,
            'daily_profit_target_amount' => ['nullable', 'numeric', 'gt:0', 'max:100000000'],
            // No new trades while the account balance is below this (empty = off).
            'min_account_balance' => ['nullable', 'numeric', 'gt:0', 'max:100000000'],
        ];
    }

    public function after(): array
    {
        return [function (Validator $validator) {
            $min = $this->input('min_stop_pips');
            $max = $this->input('max_stop_pips');
            if (is_numeric($min) && is_numeric($max) && (float) $min > (float) $max) {
                $validator->errors()->add('min_stop_pips', 'The minimum stop cannot be larger than the maximum stop.');
            }
            if (($this->input('cooldown_after_losses') === null) !== ($this->input('cooldown_minutes') === null)) {
                $validator->errors()->add('cooldown_minutes', 'Set both the losses and the minutes for a cooldown, or neither.');
            }
            $stake = $this->input('stake_amount');
            $maxStake = $this->input('max_stake_amount');
            if (is_numeric($stake) && is_numeric($maxStake) && (float) $stake > (float) $maxStake) {
                $validator->errors()->add('stake_amount', 'The stake per trade cannot be larger than the maximum stake.');
            }
        }];
    }
}
