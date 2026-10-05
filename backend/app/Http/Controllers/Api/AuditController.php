<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\AuditLog;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Gate;

class AuditController extends Controller
{
    public function index(Request $request): JsonResponse
    {
        Gate::authorize('view-audit');

        return response()->json(AuditLog::query()
            ->when($request->query('action'), fn ($q, $a) => $q->where('action', 'like', $a.'%'))
            ->orderByDesc('id')->paginate(min(200, (int) $request->query('per_page', 100))));
    }
}
