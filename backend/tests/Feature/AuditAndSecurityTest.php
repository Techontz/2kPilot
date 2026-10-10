<?php

namespace Tests\Feature;

use App\Models\AuditLog;
use App\Services\Audit\AuditLogger;
use App\Services\Audit\Masker;
use Illuminate\Database\QueryException;
use Tests\TestCase;

class AuditAndSecurityTest extends TestCase
{
    public function test_audit_log_is_append_only_at_the_database_level(): void
    {
        $entry = app(AuditLogger::class)->record('test.action', details: ['x' => 1]);
        try {
            AuditLog::query()->whereKey($entry->id)->update(['action' => 'tampered']);
            $this->fail('update should be refused');
        } catch (QueryException $e) {
            $this->assertStringContainsString('append-only', $e->getMessage());
        }
        $this->expectException(QueryException::class);
        AuditLog::query()->whereKey($entry->id)->delete();
    }

    public function test_secrets_are_masked_in_audit_details(): void
    {
        $entry = app(AuditLogger::class)->record('test.masking', details: [
            'token' => 'pat_abc', 'nested' => ['api_secret' => 's3cret', 'symbol' => 'EURUSD'], 'note' => 'password=hunter2 ok',
        ]);
        $this->assertSame(Masker::MASK, $entry->details['token']);
        $this->assertSame(Masker::MASK, $entry->details['nested']['api_secret']);
        $this->assertSame('EURUSD', $entry->details['nested']['symbol']);
        $this->assertSame('password=*** ok', $entry->details['note']);
    }

    public function test_users_see_their_own_audit_entries_and_admins_see_all(): void
    {
        $other = $this->user();
        app(AuditLogger::class)->record('test.mine', actor: $this->me());
        app(AuditLogger::class)->record('test.theirs', actor: $other);
        $this->actingAs($this->me())->getJson('/api/audit')->assertOk()->assertJsonCount(1, 'data')->assertJsonPath('data.0.action', 'test.mine');
        $this->actingAs($this->admin())->getJson('/api/audit')->assertOk()->assertJsonCount(2, 'data');
    }

    public function test_horizon_dashboard_is_for_admins_only(): void
    {
        $this->get('/horizon')->assertForbidden();
        $this->actingAs($this->me())->get('/horizon')->assertForbidden();
        $this->actingAs($this->admin())->get('/horizon')->assertOk();
    }

    public function test_security_headers_are_set(): void
    {
        $this->actingAs($this->me())->getJson('/api/trading/status')
            ->assertHeader('X-Content-Type-Options', 'nosniff')
            ->assertHeader('X-Frame-Options', 'DENY');
    }

    public function test_hidden_attributes_never_serialise(): void
    {
        $owner = $this->me();
        $json = json_encode($owner);
        $this->assertStringNotContainsString('password', $json);
        $this->assertStringNotContainsString('two_factor', $json);
    }
}
