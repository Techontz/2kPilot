<?php

namespace App\Enums;

/** Where an account's money lives. The BROKER reports it; users only select an expectation. */
enum AccountEnvironment: string
{
    case Paper = 'PAPER';     // internal simulator, no broker, no money
    case Demo = 'DEMO';       // broker account with virtual money
    case Live = 'LIVE';       // real money
    case Unknown = 'UNKNOWN'; // broker did not say — treated as LIVE for safety, never trades

    public function isRealMoneyPossible(): bool
    {
        return $this === self::Live || $this === self::Unknown;
    }
}
