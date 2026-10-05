<?php

namespace App\Enums;

enum ConnectorType: string
{
    case Paper = 'paper';
    case Deriv = 'deriv';
    case Mt5Bridge = 'mt5_bridge';
}
