<?php

namespace App\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;
use Illuminate\Validation\Rule;

/** Rename a strategy or change its description (rules change through new versions). */
class UpdateStrategyRequest extends FormRequest
{
    public function authorize(): bool
    {
        return $this->user()->can('update', $this->route('strategy'));
    }

    public function rules(): array
    {
        $strategy = $this->route('strategy');

        return [
            'name' => ['sometimes', 'required', 'string', 'max:120', Rule::unique('strategies', 'name')
                ->where('user_id', $strategy->user_id)->ignore($strategy)],
            'description' => ['sometimes', 'nullable', 'string', 'max:2000'],
        ];
    }

    public function messages(): array
    {
        return ['name.unique' => 'You already have a strategy with this name.'];
    }
}
