<?php

namespace App\Http\Requests;

use App\Support\ContractSpec;
use Illuminate\Foundation\Http\FormRequest;

/**
 * Run a strategy's latest version on one account + symbol with a contract
 * spec (contract omitted: Rise/Fall 5 minutes on Deriv, Spot on Paper).
 */
class ActivateStrategyRequest extends FormRequest
{
    public function authorize(): bool
    {
        return $this->user()->can('use', $this->route('strategy')); // own or built-in, never admin-read
    }

    public function rules(): array
    {
        return [
            'account_id' => ['required', 'uuid'],
            'symbol' => ['required', 'string', 'max:40'],
            'contract' => ['nullable', 'array'],
        ] + ContractSpec::rules('contract.');
    }
}
