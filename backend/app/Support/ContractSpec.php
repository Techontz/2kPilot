<?php

namespace App\Support;

use App\Enums\ContractFamily;
use App\Models\StrategyAssignment;
use App\Models\TradingAccount;
use Closure;
use Illuminate\Support\Facades\Validator as ValidatorFactory;
use Illuminate\Validation\Rule;
use Illuminate\Validation\Validator;

/**
 * The contract specification: how a BUY/SELL decision is traded. One canonical
 * shape everywhere (assignments, manual tickets, backtests, the engine):
 *
 *   {contract_family, duration, duration_unit, allow_equals, stake,
 *    multiplier, take_profit_amount, stop_loss_amount}
 *
 *  - SPOT        lots + stop loss/take profit prices (Paper accounts only)
 *  - RISE_FALL   duration + unit; stake NULL = the risk profile's stake_amount
 *  - MULTIPLIER  multiplier; optional take profit / stop loss amounts (money)
 *
 * Bounds here are sanity limits only: the trading engine checks every
 * contract against the broker's real `contracts_for` limits.
 */
final class ContractSpec
{
    public const FIELDS = ['contract_family', 'duration', 'duration_unit', 'allow_equals', 'stake', 'multiplier', 'take_profit_amount', 'stop_loss_amount'];

    public const DURATION_UNITS = ['t', 's', 'm', 'h', 'd'];

    private const LABELS = [
        'duration' => 'a duration', 'duration_unit' => 'a duration unit', 'stake' => 'a stake', 'multiplier' => 'a multiplier',
        'take_profit_amount' => 'a take profit amount', 'stop_loss_amount' => 'a stop loss amount',
    ];

    /** Field rules. With a prefix ("contract.") the family is required whenever the object is sent. */
    public static function rules(string $prefix = ''): array
    {
        $parent = rtrim($prefix, '.');
        $money = ['nullable', 'numeric', 'gt:0', 'max:1000000'];

        return [
            "{$prefix}contract_family" => array_filter(['nullable', $parent === '' ? null : "required_with:{$parent}", Rule::enum(ContractFamily::class)]),
            "{$prefix}duration" => ['nullable', 'integer', 'min:1', 'max:100000'],
            "{$prefix}duration_unit" => ['nullable', Rule::in(self::DURATION_UNITS)],
            "{$prefix}allow_equals" => ['nullable', 'boolean'],
            "{$prefix}stake" => ['nullable', 'numeric', 'gt:0', 'max:100000'],
            "{$prefix}multiplier" => ['nullable', 'integer', 'min:1', 'max:5000'],
            "{$prefix}take_profit_amount" => $money,
            "{$prefix}stop_loss_amount" => $money,
        ];
    }

    /** What a new assignment or ticket trades when no family was chosen. */
    public static function defaultFor(TradingAccount $account): array
    {
        return $account->isDeriv()
            ? self::normalize(['contract_family' => ContractFamily::RiseFall->value, 'duration' => 5, 'duration_unit' => 'm', 'allow_equals' => false])
            : self::normalize(['contract_family' => ContractFamily::Spot->value]);
    }

    /** The submitted fields with the default applied when no family was chosen (no account: SPOT). */
    public static function resolve(array $input, ?TradingAccount $account = null): array
    {
        $input = array_intersect_key($input, array_flip(self::FIELDS));
        if (self::filled($input, 'contract_family')) {
            return $input;
        }
        $default = $account ? self::defaultFor($account) : self::normalize(['contract_family' => ContractFamily::Spot->value]);

        return array_merge($default, array_filter($input, fn ($v) => $v !== null && $v !== ''));
    }

    /** Combination rules, as [field => message]; empty when the spec is consistent. */
    public static function problems(array $spec, ?TradingAccount $account = null): array
    {
        $family = ContractFamily::tryFrom((string) ($spec['contract_family'] ?? ''));
        if ($family === null) {
            return ['contract_family' => 'Choose a contract type: Rise/Fall, Multiplier or Spot.'];
        }
        $errors = [];
        $equals = in_array($spec['allow_equals'] ?? false, [true, 1, '1', 'true'], true);
        if ($family === ContractFamily::Spot && $account?->isDeriv()) {
            $errors['contract_family'] = 'Deriv accounts trade contracts: choose Rise/Fall or Multiplier.';
        }
        switch ($family) {
            case ContractFamily::RiseFall:
                if (! self::filled($spec, 'duration')) {
                    $errors['duration'] = 'Rise/Fall contracts need a duration.';
                }
                if (! self::filled($spec, 'duration_unit')) {
                    $errors['duration_unit'] = 'Choose a duration unit: ticks, seconds, minutes, hours or days.';
                }
                foreach (['multiplier', 'take_profit_amount', 'stop_loss_amount'] as $field) {
                    if (self::filled($spec, $field)) {
                        $errors[$field] = 'Only Multiplier contracts use '.self::LABELS[$field].'.';
                    }
                }
                break;
            case ContractFamily::Multiplier:
                if (! self::filled($spec, 'multiplier')) {
                    $errors['multiplier'] = 'Multiplier contracts need a multiplier.';
                }
                foreach (['duration', 'duration_unit'] as $field) {
                    if (self::filled($spec, $field)) {
                        $errors[$field] = 'Multiplier contracts have no fixed duration: leave it empty.';
                    }
                }
                if ($equals) {
                    $errors['allow_equals'] = '"Allow equals" only applies to Rise/Fall contracts.';
                }
                if (self::filled($spec, 'stop_loss_amount') && self::filled($spec, 'stake') && (float) $spec['stop_loss_amount'] > (float) $spec['stake']) {
                    $errors['stop_loss_amount'] = 'The stop loss amount cannot be more than the stake (the most a contract can lose).';
                }
                break;
            case ContractFamily::Spot:
                foreach (array_keys(self::LABELS) as $field) {
                    if (self::filled($spec, $field)) {
                        $errors[$field] = 'Spot trades are sized in lots: leave the contract settings empty.';
                    }
                }
                if ($equals) {
                    $errors['allow_equals'] = '"Allow equals" only applies to Rise/Fall contracts.';
                }
                break;
        }

        return $errors;
    }

    /** An "after" validator hook: reports combination problems once the field rules passed. */
    public static function after(?TradingAccount $account = null, string $prefix = ''): Closure
    {
        return function (Validator $validator) use ($account, $prefix) {
            $keys = array_map(fn (string $f) => $prefix.$f, self::FIELDS);
            if ($prefix !== '') {
                $keys[] = rtrim($prefix, '.');
            }
            foreach ($keys as $key) {
                if ($validator->errors()->has($key)) {
                    return; // fix the field errors first
                }
            }
            $input = self::slice($validator->getData(), $prefix);
            foreach (self::problems(self::resolve($input, $account), $account) as $field => $message) {
                $validator->errors()->add($prefix.$field, $message);
            }
        };
    }

    /**
     * Validate the spec in $data (at $prefix) for $account, with optional extra
     * rules, and return it in canonical form. Throws a ValidationException.
     */
    public static function validate(array $data, ?TradingAccount $account = null, string $prefix = '', array $rules = []): array
    {
        ValidatorFactory::make($data, $rules + self::rules($prefix))->after(self::after($account, $prefix))->validate();

        return self::normalize(self::resolve(self::slice($data, $prefix), $account));
    }

    /** Canonical form: fields that do not apply to the family are NULL; money as "0.00" strings. */
    public static function normalize(array $spec): array
    {
        $family = ContractFamily::from((string) $spec['contract_family']);
        $riseFall = $family === ContractFamily::RiseFall;
        $multiplier = $family === ContractFamily::Multiplier;
        $int = fn (string $f) => self::filled($spec, $f) ? (int) $spec[$f] : null;
        $money = fn (string $f) => self::filled($spec, $f) ? number_format((float) $spec[$f], 2, '.', '') : null;

        return [
            'contract_family' => $family->value,
            'duration' => $riseFall ? $int('duration') : null,
            'duration_unit' => $riseFall && self::filled($spec, 'duration_unit') ? (string) $spec['duration_unit'] : null,
            'allow_equals' => $riseFall && in_array($spec['allow_equals'] ?? false, [true, 1, '1', 'true'], true),
            'stake' => $family === ContractFamily::Spot ? null : $money('stake'),
            'multiplier' => $multiplier ? $int('multiplier') : null,
            'take_profit_amount' => $multiplier ? $money('take_profit_amount') : null,
            'stop_loss_amount' => $multiplier ? $money('stop_loss_amount') : null,
        ];
    }

    /** The stored spec of an assignment. */
    public static function fromAssignment(StrategyAssignment $assignment): array
    {
        return self::normalize(['contract_family' => $assignment->contract_family ?: ContractFamily::Spot->value] + $assignment->only(self::FIELDS));
    }

    public static function isSpot(array $spec): bool
    {
        return ($spec['contract_family'] ?? null) === ContractFamily::Spot->value;
    }

    private static function slice(array $data, string $prefix): array
    {
        if ($prefix === '') {
            return $data;
        }
        $nested = data_get($data, rtrim($prefix, '.'));

        return is_array($nested) ? $nested : [];
    }

    private static function filled(array $spec, string $field): bool
    {
        return ($spec[$field] ?? null) !== null && $spec[$field] !== '';
    }
}
