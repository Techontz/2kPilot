<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\AuditLog;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

/** The audit trail: a user sees their own actions; admins see everyone's. */
class AuditController extends Controller
{
    public function index(Request $request): JsonResponse
    {
        $user = $request->user();

        return response()->json(AuditLog::query()
            ->when(! $user->isAdmin(), fn ($q) => $q->where('actor_user_id', $user->id))
            ->when($request->query('action'), fn ($q, $a) => $q->where('action', 'like', $a.'%'))
            ->orderByDesc('id')->paginate(min(200, (int) $request->query('per_page', 100))));
    }
}
