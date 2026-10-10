<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Services\Trading\TradingControl;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Gate;

/** Platform operations for admins: the emergency halt that stops every user's trading. */
class AdminController extends Controller
{
    public function __construct(private readonly TradingControl $control) {}

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
}
