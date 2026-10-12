<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\MobileDevice;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

/**
 * The mobile app's push registration (Firebase Cloud Messaging device
 * tokens). Bearer-token requests only; each registration is linked to the
 * user and to the token that registered it, so signing out removes it.
 */
class MobileDeviceController extends Controller
{
    /** Register (or refresh) this phone for push notifications. */
    public function store(Request $request): JsonResponse
    {
        $data = $request->validate([
            'fcm_token' => ['required', 'string', 'max:4096'],
            'platform' => ['required', 'string', 'in:android,ios'],
            'app_version' => ['nullable', 'string', 'max:40'],
        ]);
        // Upsert by FCM token: a token moves to whoever signs in on that phone now.
        MobileDevice::query()->updateOrCreate(
            ['fcm_token_hash' => MobileDevice::hashToken($data['fcm_token'])],
            [
                'fcm_token' => $data['fcm_token'],
                'user_id' => $request->user()->id,
                'personal_access_token_id' => $request->user()->currentAccessToken()->id,
                'platform' => $data['platform'],
                'app_version' => $data['app_version'] ?? null,
                'last_seen_at' => now(),
            ],
        );

        return response()->json(['ok' => true]);
    }

    /** Stop push notifications to this phone (only the user's own registration). */
    public function destroy(Request $request): JsonResponse
    {
        $data = $request->validate(['fcm_token' => ['required', 'string', 'max:4096']]);
        MobileDevice::query()->ownedBy($request->user())
            ->where('fcm_token_hash', MobileDevice::hashToken($data['fcm_token']))->delete();

        return response()->json(['ok' => true]);
    }
}
