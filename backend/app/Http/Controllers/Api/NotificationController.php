<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\AppNotification;
use App\Models\User;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

/** The current user's notifications; admins also see platform notifications (user_id NULL). */
class NotificationController extends Controller
{
    public function index(Request $request): JsonResponse
    {
        $request->validate(['unread' => ['nullable', 'boolean'], 'severity' => ['nullable', 'string', 'max:16']]);
        $items = self::inbox($request->user())
            ->when($request->boolean('unread'), fn ($q) => $q->whereNull('read_at'))
            ->when($request->query('severity'), fn ($q, $s) => $q->where('severity', $s))
            ->orderByDesc('id')->paginate(min(100, (int) $request->query('per_page', 50)));

        return response()->json($items);
    }

    public function unreadCount(Request $request): JsonResponse
    {
        return response()->json(['count' => self::inbox($request->user())->whereNull('read_at')->count()]);
    }

    public function markRead(Request $request): JsonResponse
    {
        $data = $request->validate(['ids' => ['nullable', 'array'], 'ids.*' => ['integer']]);
        $query = self::inbox($request->user())->whereNull('read_at');
        if (! empty($data['ids'])) {
            $query->whereIn('id', $data['ids']);
        }

        return response()->json(['updated' => $query->update(['read_at' => now()])]);
    }

    /** @return Builder<AppNotification> */
    public static function inbox(User $user): Builder
    {
        return AppNotification::query()->where(fn (Builder $q) => $q->where('user_id', $user->id)
            ->when($user->isAdmin(), fn (Builder $q2) => $q2->orWhereNull('user_id')));
    }
}
