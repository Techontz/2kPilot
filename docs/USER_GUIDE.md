# User guide

The dashboard answers eight questions at a glance:

| Question | Where |
|---|---|
| Which broker/account am I using? | Account switcher, top left (broker · account id) |
| Is this PAPER, DEMO or LIVE? | The badge next to the account, and the strip under the top bar (grey PAPER, blue DEMO, red LIVE) |
| Is my robot running? | "Running / Trading stopped / Engine offline" in the top bar |
| What strategy is running? | Overview → Strategies; Strategies page |
| How much am I risking? | Overview → Risk used; Risk page → Limits in use |
| What positions are open? | Overview → Active positions; Positions page |
| Am I making or losing money? | Overview → Today's / Total / Open P/L (green profit, red loss) |
| Is my broker connected? | The dot next to the account; Overview → Broker connection |

## Learn with Paper Trading (no real money)

1. **Brokers → Add broker → Paper Trading → Continue → Continue.** Keep the defaults (or set "Start the simulation this many days ago" to 0 to follow the real clock) → **Test connection** → tick "This is the account I want" → keep *Conservative (default)* → **Save account**.
2. On the account card switch **Trading enabled** on.
3. **Strategies → Trend Pullback V1 → Assign** → your paper account, EURUSD → *Assign (paused)* → **Enable**.
4. Press **Resume trading** in the top bar and confirm.
5. Watch **Journal** (every decision, including rejected signals and why), **Positions**, **History** and **Analytics**. Everything is labelled PAPER.

The default profile only trades in the London, Overlap and New York sessions — outside them every ticket is rejected with the reason. Create a profile on the **Risk** page if you want different limits.

## Place a manual trade

**Trade** → symbol → Buy/Sell → stop loss (required — use the "20 pips" shortcut) → optional take profit → the **Risk check** panel shows estimated risk, reward, R:R and every rule. Use **"Use max allowed"** for the largest size your risk profile permits → **Review order** → confirm. Manual tickets pass the same risk engine as the robot: STOP TRADING, loss limits, exposure, spread, session, stop loss… Each confirmation carries a one-time key, so a double click or a network retry can never open two positions.

## STOP TRADING and Close positions

* **STOP TRADING** (red, top bar, always visible): no new trades — automated or manual — until you resume. **Open positions stay open.**
* **Close positions** (Risk page → Emergency): stops trading *and* closes every open position at market. You must type `CLOSE`.

## Backtesting

**Backtesting → Manage data** → generate SYNTHETIC data (for testing the system only) or import a CSV (MetaTrader export) → choose strategy, data, period, initial balance, risk %, spread, commission, slippage, and Single / In-and-out-of-sample / Walk-forward → **Run backtest**. Results: return, net P/L, win rate, profit factor, expectancy, max drawdown, average R:R, trades, equity and drawdown curves, monthly results and every trade. Fills happen at the next bar's open — the strategy never sees the future. Historical results never guarantee future performance.

## Strategies: why did it (not) trade?

**Strategies → Why?** on an assignment shows every closed bar (signal / no setup / not enough data, with each check) and every signal with the risk engine's verdict.

## Two-factor authentication

**Settings → Security**: confirm your password → scan the QR code with an authenticator app → enter the code → **save the recovery codes**. From then on sign-in asks for a code. LIVE mode cannot be enabled without MFA.

## LIVE (real money)

LIVE is **locked** until the server operator sets `LIVE_TRADING_ENABLED=true` (backend and engine). Even then, switching the operating mode to LIVE requires trading to be stopped, MFA, your password and typing `ENABLE LIVE TRADING`. Read [ROADMAP.md](ROADMAP.md) first.
