<?php

namespace App\Enums;

enum TradingMode: string
{
    case Backtest = 'BACKTEST'; // no broker orders at all
    case Demo = 'DEMO';         // PAPER and DEMO accounts only
    case Live = 'LIVE';         // real money allowed (needs the server LIVE lock off)

    /** May an account of this environment receive orders in this mode? */
    public function permits(AccountEnvironment $environment): bool
    {
        if ($environment === AccountEnvironment::Unknown || $this === self::Backtest) {
            return false;
        }
        if ($this === self::Demo) {
            return in_array($environment, [AccountEnvironment::Paper, AccountEnvironment::Demo], true);
        }

        return true;
    }
}
