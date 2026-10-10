<?php

namespace App\Http\Requests;

use App\Models\Strategy;
use Illuminate\Foundation\Http\FormRequest;
use Illuminate\Validation\Rule;
use Illuminate\Validation\Validator;

/**
 * A strategy file produced by GET /api/strategies/{id}/export:
 * {format: "tradepilot.strategy", schema_version: 1, name, description, rules}.
 * Size-limited; the rule set is validated by the engine like any other.
 */
class ImportStrategyRequest extends FormRequest
{
    public const MAX_BYTES = 131_072;

    public function authorize(): bool
    {
        return $this->user()->can('create', Strategy::class);
    }

    public function rules(): array
    {
        return [
            'format' => ['required', 'string', Rule::in(['tradepilot.strategy'])],
            'schema_version' => ['required', 'integer', Rule::in([1])],
            'name' => ['required', 'string', 'max:120', Rule::unique('strategies', 'name')->where('user_id', $this->user()->id)],
            'description' => ['nullable', 'string', 'max:2000'],
            'rules' => ['required', 'array', StoreStrategyRequest::sizeLimit()],
        ];
    }

    public function messages(): array
    {
        return [
            'format.in' => 'This is not a 2kPilot strategy file.',
            'schema_version.in' => 'This strategy file was made by a newer version of 2kPilot.',
            'name.unique' => 'You already have a strategy with this name — rename it before importing.',
        ];
    }

    public function after(): array
    {
        return [function (Validator $validator) {
            if (strlen($this->getContent()) > self::MAX_BYTES) {
                $validator->errors()->add('rules', 'The file is too large (128 KB at most).');
            }
        }];
    }
}
