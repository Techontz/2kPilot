<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\AppNotification;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class NotificationController extends Controller
{
    public function index(Request $request): JsonResponse
    {
        $request->validate(['unread' => ['nullable', 'boolean'], 'severity' => ['nullable', 'string', 'max:16']]);
        $items = AppNotification::query()
            ->when($request->boolean('unread'), fn ($q) => $q->whereNull('read_at'))
            ->when($request->query('severity'), fn ($q, $s) => $q->where('severity', $s))
            ->orderByDesc('id')->paginate(min(100, (int) $request->query('per_page', 50)));

        return response()->json($items);
    }

    public function unreadCount(): JsonResponse
    {
        return response()->json(['count' => AppNotification::query()->whereNull('read_at')->count()]);
    }

    public function markRead(Request $request): JsonResponse
    {
        $data = $request->validate(['ids' => ['nullable', 'array'], 'ids.*' => ['integer']]);
        $query = AppNotification::query()->whereNull('read_at');
        if (! empty($data['ids'])) {
            $query->whereIn('id', $data['ids']);
        }

        return response()->json(['updated' => $query->update(['read_at' => now()])]);
    }
}
