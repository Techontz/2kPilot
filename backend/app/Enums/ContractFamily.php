<?php

namespace App\Enums;

/** How a BUY/SELL decision is traded. Deriv accounts trade contracts; SPOT is Paper only. */
enum ContractFamily: string
{
    case RiseFall = 'RISE_FALL';     // fixed duration, fixed stake; BUY → CALL, SELL → PUT
    case Multiplier = 'MULTIPLIER';  // stake × multiplier; BUY → MULTUP, SELL → MULTDOWN
    case Spot = 'SPOT';              // lots with stop loss / take profit prices (Paper)

    public function label(): string
    {
        return match ($this) {
            self::RiseFall => 'Rise/Fall',
            self::Multiplier => 'Multiplier',
            self::Spot => 'Spot',
        };
    }
}
