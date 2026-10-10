<?php

namespace Database\Factories;

use App\Enums\UserRole;
use App\Models\User;
use App\Services\Users\UserProvisioner;
use Illuminate\Database\Eloquent\Factories\Factory;
use Illuminate\Support\Facades\Hash;

/** @extends Factory<User> */
class UserFactory extends Factory
{
    public const PASSWORD = 'Correct-Horse-42';

    protected static ?string $password;

    public function definition(): array
    {
        return [
            'name' => fake()->name(),
            'email' => strtolower(fake()->unique()->safeEmail()),
            'password' => static::$password ??= Hash::make(self::PASSWORD),
            'role' => UserRole::User,
            'is_active' => true,
        ];
    }

    public function admin(): static
    {
        return $this->state(['role' => UserRole::Admin]);
    }

    /** As after sign-up: the default risk profile and trading state (stopped, DEMO). */
    public function provisioned(): static
    {
        return $this->afterCreating(fn (User $user) => app(UserProvisioner::class)->provision($user));
    }

    public function inactive(): static
    {
        return $this->state(['is_active' => false]);
    }
}
