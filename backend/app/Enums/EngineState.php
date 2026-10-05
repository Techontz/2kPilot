<?php

namespace App\Enums;

enum EngineState: string
{
    case Offline = 'offline';   // no recent heartbeat
    case Running = 'running';
    case Degraded = 'degraded'; // running, but an account or broker has a problem
}
