<?php

namespace App\Enums;

/** A user's operating mode (user_trading_states.trading_mode). */
enum TradingMode: string
{
    case Demo = 'DEMO'; // PAPER and DEMO accounts only
    case Live = 'LIVE'; // LIVE accounts only (needs the server LIVE lock off and a LIVE authorisation)

    /** May an account of this environment receive orders in this mode? */
    public function permits(AccountEnvironment $environment): bool
    {
        return match ($this) {
            self::Demo => in_array($environment, [AccountEnvironment::Paper, AccountEnvironment::Demo], true),
            self::Live => $environment === AccountEnvironment::Live,
        };
    }
}
