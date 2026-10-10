<?php

namespace App\Http\Requests;

use App\Models\Strategy;
use Closure;
use Illuminate\Foundation\Http\FormRequest;
use Illuminate\Validation\Rule;

/**
 * A new rule-based strategy from the visual builder or a reviewed AI draft.
 * Laravel checks the envelope; the trading engine validates the rule set
 * itself (it owns the format) and its messages are returned as `problems`.
 */
class StoreStrategyRequest extends FormRequest
{
    public const MAX_RULES_BYTES = 65_536;

    public function authorize(): bool
    {
        return $this->user()->can('create', Strategy::class);
    }

    public function rules(): array
    {
        return [
            'name' => ['required', 'string', 'max:120', Rule::unique('strategies', 'name')->where('user_id', $this->user()->id)],
            'description' => ['nullable', 'string', 'max:2000'],
            'rules' => ['required', 'array', self::sizeLimit()],
            'source' => ['nullable', Rule::in(['builder', 'ai', 'import'])],
        ];
    }

    public function messages(): array
    {
        return ['name.unique' => 'You already have a strategy with this name.'];
    }

    /** Rule sets are small; anything bigger is a mistake or abuse. */
    public static function sizeLimit(): Closure
    {
        return function (string $attribute, mixed $value, Closure $fail) {
            if (strlen((string) json_encode($value)) > self::MAX_RULES_BYTES) {
                $fail('The rules are too large (64 KB at most).');
            }
        };
    }
}
