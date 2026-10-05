<?php

namespace App\Services\Audit;

use App\Enums\AuditOutcome;
use App\Models\AuditLog;
use App\Models\User;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Log;

/**
 * Writes the append-only audit trail. Every security- or trading-relevant
 * action — allowed, refused or failed — goes through here. Details are masked.
 */
class AuditLogger
{
    public function __construct(private readonly ?Request $request = null) {}

    public function record(
        string $action,
        AuditOutcome $outcome = AuditOutcome::Success,
        ?User $actor = null,
        ?string $targetType = null,
        ?string $targetId = null,
        array $details = [],
        ?string $actorLabel = null,
    ): AuditLog {
        $actor ??= $this->request?->user();
        $entry = AuditLog::query()->create([
            'occurred_at' => now(),
            'actor_user_id' => $actor?->id,
            'actor_label' => $actorLabel ?? $actor?->email ?? 'system',
            'action' => $action,
            'outcome' => $outcome,
            'target_type' => $targetType,
            'target_id' => $targetId,
            'ip_address' => $this->request?->ip(),
            'user_agent' => $this->request ? substr((string) $this->request->userAgent(), 0, 512) ?: null : null,
            'correlation_id' => $this->request?->header('X-Request-ID'),
            'details' => Masker::mask($details),
        ]);
        Log::info("audit {$action} {$outcome->value}", ['actor' => $entry->actor_label]);

        return $entry;
    }
}
