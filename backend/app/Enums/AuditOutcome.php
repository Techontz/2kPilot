<?php

namespace App\Enums;

enum AuditOutcome: string
{
    case Success = 'success';
    case Failure = 'failure';
    case Denied = 'denied';
}
