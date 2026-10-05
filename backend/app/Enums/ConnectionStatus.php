<?php

namespace App\Enums;

enum ConnectionStatus: string
{
    case Connected = 'CONNECTED';
    case Disconnected = 'DISCONNECTED';
    case Reconnecting = 'RECONNECTING';
    case Error = 'ERROR';
}
