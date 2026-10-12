<?php

namespace Tests\Feature;

use App\Models\User;
use Database\Factories\UserFactory;
use Tests\TestCase;

class UserApprovalTest extends TestCase
{
    private function pending(): User
    {
        return User::factory()->pending()->provisioned()->create(['name' => 'Juma', 'email' => 'juma@example.com']);
    }

    public function test_a_pending_user_sees_only_the_waiting_page_and_can_sign_out(): void
    {
        $user = $this->pending();
        $this->actingAs($user);
        $this->getJson('/api/auth/me')->assertOk()->assertJsonPath('user.approved', false);
        foreach (['/api/overview', '/api/trading/status', '/api/strategies', '/api/accounts'] as $path) {
            $this->getJson($path)->assertForbidden()->assertJsonPath('code', 'approval_pending');
        }
        $this->postJson('/api/trading/stop')->assertForbidden();
        $this->postJson('/api/auth/logout')->assertSuccessful();
    }

    public function test_the_admins_are_told_about_a_new_sign_up(): void
    {
        $admin = $this->admin();
        $this->postJson('/api/auth/register', [
            'name' => 'Juma', 'email' => 'juma@example.com', 'password' => 'Trading-Pilot-42',
            'password_confirmation' => 'Trading-Pilot-42', 'accept_terms' => true,
        ])->assertCreated();
        $this->assertDatabaseHas('notifications', ['user_id' => $admin->id, 'type' => 'user.pending_approval']);
    }

    public function test_an_admin_lists_and_approves_users(): void
    {
        $user = $this->pending();
        $this->user(); // an approved one
        $this->actingAs($this->admin());
        $list = $this->getJson('/api/admin/users')->assertOk()->json('users');
        $this->assertSame('juma@example.com', $list[0]['email']); // waiting users first
        $this->assertFalse($list[0]['approved']);

        $this->postJson("/api/admin/users/{$user->id}/approve")->assertOk()->assertJsonPath('approved', true);
        $this->assertNotNull($user->fresh()->approved_at);
        $this->assertDatabaseHas('audit_logs', ['action' => 'user.approved', 'target_id' => $user->id]);
        $this->assertDatabaseHas('notifications', ['user_id' => $user->id, 'type' => 'user.approved']);

        $this->actingAs($user->fresh());
        $this->getJson('/api/trading/status')->assertOk();
    }

    public function test_an_admin_disables_and_enables_a_user_but_not_themself(): void
    {
        $admin = $this->admin();
        $user = $this->user();
        $this->actingAs($admin);
        $this->postJson("/api/admin/users/{$user->id}/disable")->assertOk()->assertJsonPath('is_active', false);
        $this->postJson("/api/admin/users/{$user->id}/enable")->assertOk()->assertJsonPath('is_active', true);
        $this->postJson("/api/admin/users/{$admin->id}/disable")->assertStatus(409)->assertJsonPath('code', 'cannot_disable_self');
    }

    public function test_only_admins_manage_users(): void
    {
        $user = $this->pending();
        $this->actingAs($this->user());
        $this->getJson('/api/admin/users')->assertForbidden();
        $this->postJson("/api/admin/users/{$user->id}/approve")->assertForbidden();
        $this->assertNull($user->fresh()->approved_at);
    }

    public function test_a_pending_user_cannot_sign_in_on_the_mobile_app(): void
    {
        $this->pending();
        $this->postJson('/api/mobile/auth/login', ['email' => 'juma@example.com', 'password' => UserFactory::PASSWORD, 'device_name' => 'Phone'])
            ->assertForbidden()->assertJsonPath('code', 'approval_pending');
    }

    public function test_an_existing_account_can_be_made_an_admin(): void
    {
        $user = $this->pending();
        $this->artisan('tp:make-admin', ['email' => 'JUMA@example.com'])->assertSuccessful();
        $user->refresh();
        $this->assertTrue($user->isAdmin());
        $this->assertNotNull($user->approved_at);
        $this->artisan('tp:make-admin', ['email' => 'nobody@example.com'])->assertFailed();
    }
}
