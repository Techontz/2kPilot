<?php

namespace App\Console\Commands;

use App\Enums\UserRole;
use App\Models\User;
use App\Services\Audit\AuditLogger;
use App\Services\Users\UserProvisioner;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\Validator;
use Illuminate\Validation\Rule;
use Illuminate\Validation\Rules\Password;

/**
 * Create a user from the command line — e.g. the first admin, or users on a
 * server with sign-up turned off (TP_REGISTRATION_ENABLED=false). The user is
 * provisioned exactly like a sign-up: Beginner risk profile, trading STOPPED.
 *
 *   php artisan tp:user --email=you@example.com --name="Conrad" --role=admin
 */
class CreateUser extends Command
{
    protected $signature = 'tp:user
        {--email= : Login email}
        {--name= : Display name}
        {--role=user : user (trades their own accounts) or admin (also operates the platform)}
        {--password-stdin : Read the password from standard input (for scripts)}';

    protected $description = 'Create a 2kPilot user';

    public function handle(AuditLogger $audit, UserProvisioner $provisioner): int
    {
        $email = strtolower(trim((string) ($this->option('email') ?: $this->ask('Email'))));
        $name = (string) ($this->option('name') ?: $this->ask('Name', 'Owner'));
        $role = (string) $this->option('role');
        if ($this->option('password-stdin')) {
            $password = rtrim((string) fgets(STDIN), "\r\n");
        } else {
            $password = (string) $this->secret('Password (10+ characters, mixed case, a number)');
            if ($password !== (string) $this->secret('Repeat the password')) {
                $this->error('Passwords do not match.');

                return self::FAILURE;
            }
        }
        $validator = Validator::make(compact('email', 'name', 'role', 'password'), [
            'email' => ['required', 'email', 'max:320', 'unique:users,email'],
            'name' => ['required', 'string', 'max:120'],
            'role' => ['required', Rule::enum(UserRole::class)],
            'password' => ['required', Password::defaults()],
        ]);
        if ($validator->fails()) {
            foreach ($validator->errors()->all() as $message) {
                $this->error($message);
            }

            return self::FAILURE;
        }
        $user = User::query()->create(['email' => $email, 'name' => $name, 'role' => UserRole::from($role), 'password' => $password, 'is_active' => true]);
        $provisioner->provision($user);
        $audit->record('user.created', actor: null, targetType: 'user', targetId: $user->id, details: ['email' => $email, 'role' => $role], actorLabel: 'cli');
        $this->info("Created {$role} user {$email}. Turn on two-factor authentication in Settings → Security after your first login.");

        return self::SUCCESS;
    }
}
