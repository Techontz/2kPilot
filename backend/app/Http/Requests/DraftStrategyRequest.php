<?php

namespace App\Http\Requests;

use App\Models\Strategy;
use Illuminate\Foundation\Http\FormRequest;
use Illuminate\Validation\Rule;

/** Plain-English description → draft rules (Method C). Nothing is saved. */
class DraftStrategyRequest extends FormRequest
{
    public function authorize(): bool
    {
        return $this->user()->can('create', Strategy::class);
    }

    public function rules(): array
    {
        return [
            'description' => ['required', 'string', 'min:10', 'max:2000'],
            'symbol' => ['nullable', 'string', 'max:40', 'regex:/^[A-Za-z0-9_.\-]+$/'],
            'timeframe' => ['nullable', Rule::in(['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'])],
            'contract_family' => ['nullable', Rule::in(['RISE_FALL', 'MULTIPLIER', 'SPOT'])],
        ];
    }
}
