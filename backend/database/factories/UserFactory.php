<?php

namespace Database\Factories;

use App\Enums\UserRole;
use App\Models\User;
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
            'role' => UserRole::Owner,
            'is_active' => true,
        ];
    }

    public function viewer(): static
    {
        return $this->state(['role' => UserRole::Viewer]);
    }

    public function inactive(): static
    {
        return $this->state(['is_active' => false]);
    }
}
