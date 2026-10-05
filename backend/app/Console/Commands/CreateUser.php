<?php

namespace App\Console\Commands;

use App\Enums\UserRole;
use App\Models\User;
use App\Services\Audit\AuditLogger;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\Validator;
use Illuminate\Validation\Rules\Password;

/**
 * Create a dashboard user. There is deliberately no public sign-up: a trading
 * system should only have accounts its operator created.
 *
 *   php artisan fx:user --email=you@example.com --name="Conrad"
 */
class CreateUser extends Command
{
    protected $signature = 'fx:user
        {--email= : Login email}
        {--name= : Display name}
        {--role=owner : owner (full control) or viewer (read-only)}
        {--password-stdin : Read the password from standard input (for scripts)}';

    protected $description = 'Create a 2kFX dashboard user';

    public function handle(AuditLogger $audit): int
    {
        $email = strtolower(trim((string) ($this->option('email') ?: $this->ask('Email'))));
        $name = (string) ($this->option('name') ?: $this->ask('Name', 'Owner'));
        $role = (string) $this->option('role');
        if ($this->option('password-stdin')) {
            $password = rtrim((string) fgets(STDIN), "\r\n");
        } else {
            $password = (string) $this->secret('Password (12+ characters, mixed case, a number)');
            if ($password !== (string) $this->secret('Repeat the password')) {
                $this->error('Passwords do not match.');

                return self::FAILURE;
            }
        }
        $validator = Validator::make(compact('email', 'name', 'role', 'password'), [
            'email' => ['required', 'email', 'max:320', 'unique:users,email'],
            'name' => ['required', 'string', 'max:120'],
            'role' => ['required', 'in:owner,viewer'],
            'password' => ['required', Password::min(12)->mixedCase()->numbers()],
        ]);
        if ($validator->fails()) {
            foreach ($validator->errors()->all() as $message) {
                $this->error($message);
            }

            return self::FAILURE;
        }
        $user = User::query()->create(['email' => $email, 'name' => $name, 'role' => UserRole::from($role), 'password' => $password]);
        $audit->record('user.created', actor: null, targetType: 'user', targetId: $user->id, details: ['email' => $email, 'role' => $role], actorLabel: 'cli');
        $this->info("Created {$role} user {$email}. Turn on two-factor authentication in Settings → Security after your first login.");

        return self::SUCCESS;
    }
}
