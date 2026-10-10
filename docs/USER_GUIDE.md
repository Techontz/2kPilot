# User guide

2kPilot has exactly **four sections** — **Home**, **Strategies**, **History** and **Settings** (left rail on a computer, bottom tab bar on a phone). Everything starts in **Demo**: no real money is involved until you deliberately authorise it.

## Create your account

Open **/signup** (or *No account? Create one* on the sign-in page): name, email, a password (10+ characters, mixed case, a number) and accept the risk disclosure. You're signed in straight away with a *Beginner* risk profile, **DEMO** mode and trading **stopped**. Everything you add — brokers, accounts, risk profiles, strategies, data, tests — is yours alone.

## Always visible (top bar)

| | |
|---|---|
| **Account switcher** | Which account you're looking at, with its balance. Home and History follow it. |
| **DEMO / LIVE pill** | Calm teal **DEMO** = virtual money only. Loud **LIVE** = real money. Click it to authorise real money or to **Return to Demo** in one click. |
| **Running / Stopped** | Whether the bot may open trades right now (hover for why). |
| **Start / Stop** | **Stop is one click and never asks.** Start asks once and tells you whether it's virtual or real money. |

The bot runs on the server: you can close the page and it keeps trading until you press **Stop**. Stop blocks new trades; trades that are already open finish normally (History → Open → *Close all open trades…* closes them deliberately).

## Home

* The connected **broker** and its status, the selected **account**, its **balance** (with a 30-day sparkline) and the **DEMO/LIVE** badge.
* **Bot running / stopped** and the big **Start / Stop trading** button.
* **Nothing will trade right now** — when something blocks trading, each reason is listed in plain words with the fix: *Trading is stopped*, *No strategy is active on this account*, *Risk profile missing*, *Trading is switched off for this account*, *The broker connection is …*, *The trading engine is offline*, *An administrator paused trading*.
* **Today's P/L** and **total realized P/L** (finished trades, in the account currency, green + / red −), and open trades with their current P/L.
* **Active trades** — updated live: market, contract type and direction (Rise/Fall, Up/Down, Buy/Sell), stake, **time left** for Rise/Fall contracts and current P/L. Tap one for its details.
* **Active strategies** on this account and the **last 30 days** (daily P/L bars, balance).
* First time? A **four-step checklist**: 1 Connect Deriv or start Paper → 2 Pick a strategy → 3 Test it → 4 Start in Demo.

## Step 1 — connect an account (Settings → Brokers → Add broker)

* **Paper Trading** (simulated money, no sign-up): *Paper Trading → Continue → Continue → Continue → Test connection → tick "This is the account I want to add." → risk profile + name → Save account*.
* **Deriv demo**: *Deriv → DEMO →* **Sign in with Deriv** (you come back to the wizard automatically) or paste a **personal access token** with the *trade* scope → *Find my Deriv accounts* → pick the demo account → test → save. See [BROKERS.md](BROKERS.md) for the App ID setup.

New accounts are saved with **trading off**: switch **Trading enabled** on in *Settings → Accounts* when you're ready.

## Step 2 — add a strategy (Strategies → Add strategy)

A strategy is a set of simple rules: *when* something happens on a closed candle, propose a trade up or down. Your risk limits still decide every trade. Three ways to add one:

1. **Start from a template** — *Strategies → Templates*. Each card explains how it works, when it struggles, its difficulty, suggested markets and contract, and a disclaimer. **Use this template** copies it into *My strategies* and opens it so you can review the rules.
2. **Build it step by step** — the visual builder: **WHEN** (buy and/or sell conditions, *All* or *Any*; each condition = price / number / indicator + an operator like *crosses above*, *is below*, *is between*), **THEN** (a buy or sell idea), **EXIT** (Rise/Fall settles at expiry; Multiplier/Spot can have a stop, a target and early-close conditions). A plain-English preview updates as you edit; problems are shown next to the row. Nothing is saved until you press **Save**.
3. **Describe it in your words** — type the idea (e.g. "buy when RSI 14 crosses back above 30 on 5-minute candles"). 2kPilot drafts rules with Claude and shows the explanation, warnings and anything it can't do (news, martingale, guaranteed wins…). You review and edit the draft in the builder before saving — it is **never saved automatically**. Only available when the server has an Anthropic API key; your description is sent to Anthropic, so don't include personal information.

You can also **Import** a strategy file (`.json`) from *Add strategy*, and **Export** your own rule-based strategies from the ⋯ menu on their card.

## Step 3 — test it (Test on history)

On a strategy card press **Test on history**: pick the market, candles and period; choose where the prices come from (**download past prices from your account**, or **practice data** generated by 2kPilot — clearly labelled, it says nothing about real markets); choose how each trade works (defaults come from the strategy's suggestion), the stake and — for Rise/Fall — the **payout estimate** (real payouts change with every quote). The test runs on the server; its page shows progress, then: net P/L, win rate, trades, profit factor, max drawdown, longest losing streak, expectancy, the balance and drawdown curves, warnings and every simulated trade. All tests are listed under *Strategies → Backtests*. Past and test results never guarantee future results.

## Step 4 — activate it and start in Demo

**Activate** on a strategy card: choose the account (the selected one by default), the market (the strategy's suggested markets that your account offers), the contract (Rise/Fall duration, or a Multiplier) within the ranges the broker allows, and see the **stake** from your risk profile (optionally a different one). After activating, 2kPilot tells you honestly whether it **will trade** — or exactly what still blocks it (for example "Trading is stopped" with a Start button). Then press **Start**.

*Why no trade?* on an activated strategy shows every closed candle that was checked and every trade idea your risk limits refused, with the reason. **Deactivate** stops it opening new trades on that account.

## History

* **Open** — trades that are running now (time left for Rise/Fall, current P/L), and *Close all open trades…* (stops trading first; Rise/Fall can't be closed early).
* **Closed** — every finished trade: opened/closed time, market, strategy, contract and direction, stake or size, entry, exit, fees, payout, P/L, result and duration. Filter by period, account, strategy and result (profit / loss / break-even); **Export CSV** downloads exactly what the filters show.
* **Activity** — every bot decision (including the trades it decided *not* to take, and why) and every order sent to the broker.

Tap any trade for its full story: what the broker says about the contract, why the bot took it, the risk checks, the orders and a timeline. On a phone the tables become cards.

## Settings

| Tab | What's there |
|---|---|
| **Brokers** | Your connections and accounts: status, sync, reconnect, disconnect, remove, **Add broker**. |
| **Accounts** | Choose the account Home and History show; each account's **risk profile** and **Trading enabled** switch; the **real-money (LIVE)** card. |
| **Risk limits** | Your profiles in plain words: stake per trade, maximum stake, maximum daily loss (amount or %), stop after N losses in a row, daily profit target, trades per day, open trades at once. Spot/lot settings are under *Advanced*. |
| **Notifications** | Everything the bot and the platform told you; mark one or all as read. |
| **Security** | Profile, **change password**, two-factor authentication (set up, recovery codes, turn off). |
| **System status** | Engine heartbeat, database, queue, each broker connection, the platform pause and the LIVE server lock. Administrators can **pause / resume the whole platform** here. |

## Real money (LIVE) — a separate, deliberate step

Real-money trading needs all of this, in a guided dialog (*Settings → Accounts → Authorize real-money trading…* or the **DEMO** pill):

1. The server operator has unlocked LIVE (`LIVE_TRADING_ENABLED=true` in both services). While locked, the dialog only explains this.
2. Your trading is **stopped** (one click inside the dialog).
3. You choose one of your **LIVE** accounts.
4. You read that account's **risk limits in plain words** ("Each trade stakes $1.00", "Stops for the day after 3 losses in a row", …). No risk profile → blocked.
5. You read and tick the warning: **"You can lose your entire trading balance. Automated strategies can and do lose money. Past and backtest results do not guarantee future results."**
6. You enter a **two-factor code** (MFA must be on — the dialog links to Security if it isn't), your **password**, and type **`ENABLE LIVE TRADING`**.

In LIVE mode only LIVE accounts trade (Paper and demo pause) and trading stays stopped until you press Start. **Return to Demo** (the LIVE pill, or Settings → Accounts) is one click: it stops trading and switches back.

## Two-factor authentication

*Settings → Security*: confirm your password → scan the QR code → enter the 6-digit code → **save the recovery codes**. From then on sign-in asks for a code. LIVE cannot be authorised without it.

## Custom sign-in background (optional)

The sign-in and sign-up screens play a built-in animated scene (drawn live in the browser, no media files; a still frame is shown to people who prefer reduced motion). To use your own footage instead, copy a dark, loopable clip to `frontend/public/auth/background.mp4` (H.264 MP4 or WebM, ideally under 8 MB) and set `AUTH_BACKGROUND_VIDEO = "/auth/background.mp4"` in `frontend/src/components/auth/AuthBackground.tsx` (optionally `AUTH_BACKGROUND_POSTER` to a still image for its first frame). The video plays muted, looping and inline under a dark overlay that keeps the text readable; if it fails to load, or the visitor prefers reduced motion, the built-in scene is used instead. Only use footage you have the rights to.
