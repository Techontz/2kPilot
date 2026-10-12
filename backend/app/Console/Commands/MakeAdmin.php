<?php

namespace App\Console\Commands;

use App\Enums\UserRole;
use App\Models\User;
use App\Services\Audit\AuditLogger;
use Illuminate\Console\Command;

/**
 * Make an existing account an administrator (approves it too):
 *   php artisan tp:make-admin you@example.com
 */
class MakeAdmin extends Command
{
    protected $signature = 'tp:make-admin {email : the account to promote}';

    protected $description = 'Make an existing 2kPilot user an administrator';

    public function handle(AuditLogger $audit): int
    {
        $email = strtolower(trim((string) $this->argument('email')));
        $user = User::query()->where('email', $email)->first();
        if ($user === null) {
            $this->error("No user with the email {$email}.");

            return self::FAILURE;
        }
        $user->forceFill(['role' => UserRole::Admin, 'approved_at' => $user->approved_at ?? now(), 'is_active' => true])->save();
        $audit->record('user.made_admin', actor: null, targetType: 'user', targetId: $user->id, details: ['email' => $email], actorLabel: 'cli');
        $this->info("{$email} is now an administrator. Settings → Users shows new sign-ups to approve.");

        return self::SUCCESS;
    }
}
