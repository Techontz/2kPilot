<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

/**
 * Shared settings for every 2kFX table: timestamps are DATETIME(6) in UTC,
 * the format the trading engine reads and writes too.
 */
abstract class BaseModel extends Model
{
    protected $dateFormat = 'Y-m-d H:i:s.u';

    protected $guarded = [];
}
