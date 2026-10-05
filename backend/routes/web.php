<?php

use Illuminate\Support\Facades\Route;

// The user interface is the Next.js dashboard (frontend/). Laravel serves the API only.
Route::get('/', fn () => response()->json([
    'app' => config('app.name'),
    'api' => url('/api'),
    'dashboard' => config('fx.frontend_url'),
]));
