<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * New sign-ups wait for an admin's approval (users.approved_at NULL = pending).
 * Everyone who already has an account is approved now, so nobody is locked out.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::table('users', function (Blueprint $table) {
            $table->timestamp('approved_at', 6)->nullable()->after('is_active');
            $table->foreignUuid('approved_by')->nullable()->after('approved_at')
                ->constrained('users')->nullOnDelete();
        });
        DB::table('users')->whereNull('approved_at')->update(['approved_at' => now()]);
    }

    public function down(): void
    {
        Schema::table('users', function (Blueprint $table) {
            $table->dropConstrainedForeignId('approved_by');
            $table->dropColumn('approved_at');
        });
    }
};
