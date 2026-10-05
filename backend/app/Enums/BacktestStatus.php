<?php

namespace App\Enums;

enum BacktestStatus: string
{
    case Queued = 'QUEUED';
    case Running = 'RUNNING';
    case Completed = 'COMPLETED';
    case Failed = 'FAILED';
}
