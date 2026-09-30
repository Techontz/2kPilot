# User guide

This guide is written for someone learning Forex. Hover any underlined term in the dashboard, such as <u>Equity</u> or <u>Drawdown</u>, for a plain-language explanation.

## The top bar answers the important questions

| You see | It means |
|---|---|
| **Demo / Backtest / LIVE** badge | Where orders are allowed to go. A red **LIVE — real money at risk** banner appears whenever LIVE is on |
| **Running** | The engine is alive, the kill switch is released, and strategies may place orders |
| **Trading stopped** | The kill switch is engaged. No new orders are placed. Open positions stay open, protected by their stop losses |
| **Robot offline** | No engine heartbeat. Start the backend (`make dev`) |
| ● Live | The dashboard is receiving live updates |
| **STOP ALL TRADING** | One click stops everything new. **Resume trading** asks for confirmation |

## 1. Run paper trading (no broker, no money)

1. **Brokers → Add broker → Paper / Simulation (internal)**.
   * *Price source*: `synthetic` gives generated prices, clearly labelled SYNTHETIC. `replay` replays a dataset you imported.
   * *Simulation speed*: seconds of real time per 15-minute bar. `2` means one simulated day every ~3 minutes. The simulation starts *N days ago* and never runs ahead of real time.
   * Click through **Test connection → Verify → Risk profile → Save**. The account is saved with **trading disabled**.
2. On the account card, turn on **Trading enabled**. A risk profile is required. The default "Conservative" profile is preselected.
3. **Strategies → Assign**, then choose the account and a symbol (e.g. EURUSD). New assignments are **Paused**. Click **Enable**.
4. **Resume trading** in the top bar.
5. Watch the results:
   * **Journal**: every signal, risk decision, order and exit. Rejections are normal: that's the risk engine doing its job, and every rejection says why.
   * **Positions**: open trades. You can edit the stop loss and take profit (a stop is always required) or close at market.
   * **Trade History**: click any trade to see its whole story.
   * **Analytics**: equity, drawdown, results by period, and breakdowns.

Everything created by the paper broker is marked **PAPER** and is never presented as a broker execution.

## 2. Run a backtest

1. **Markets → Historical data** gives you three ways to get data:
   * **Import CSV**: in MT5, open *View → Symbols → Bars*, choose the symbol and timeframe, and click *Export*. Enter your broker's server **UTC offset** (often +2 or +3), because MT5 exports server time.
   * **From MT5**: download straight from a connected MT5 account.
   * **Synthetic**: generated practice data. Results on it **say nothing about real markets**, and every screen says so.
2. **Backtesting → New backtest** and choose:
   * the strategy version, dataset, dates and capital;
   * a risk profile, since every live rule is applied;
   * costs: spread (empty means use each bar's recorded spread), commission per lot per side, and slippage;
   * a **validation mode**:

| Mode | Use it to… |
|---|---|
| Single | See one run |
| **In / out of sample** | The honest test: judge on data the strategy never saw |
| Walk-forward | Repeatedly pick parameters on a window, then test on the next unseen window |
| Sensitivity | Check the result doesn't collapse when a parameter changes slightly |

3. Read the warnings first. Then look at the expectancy, profit factor, max drawdown, the out-of-sample column and the trade count. Fewer than 30 trades tells you very little.

## 3. Connect an MT5 demo account

Follow [MT5_BRIDGE_SETUP.md](MT5_BRIDGE_SETUP.md). In short:
1. Install MT5 and the 2kFX bridge on a Windows PC or VPS.
2. In **Add broker**, choose **MetaTrader 5 → DEMO**.
3. Enter the bridge URL and secret, your MT5 login, password and server.
4. 2kFX verifies with the broker that it really is a demo account before saving it.

## 4. Stop, pause, emergency

| Action | Where | Effect |
|---|---|---|
| STOP ALL TRADING | Top bar / Risk Management | No new orders, strategies stop evaluating. Positions stay open |
| Pause a strategy | Strategies | That strategy only |
| Trading enabled off | Brokers (account card) | That account only |
| Emergency stop… | Risk Management | Kill switch, plus optionally **close every open position at market** |

## 5. Risk profiles

**Risk Management → Risk profiles** explains every limit next to its input. Changes are audited and apply to the next signal. The live meters show how much of each limit is used right now, for example "Daily loss: 0.4% of 2%".

## 6. Notifications

The bell shows the unread count. The **Notifications** page lists broker connect/disconnect, signals, rejections, orders, stops and targets hit, limits reached, emergency stops and system errors.

## 7. LIVE trading

It is not available. The server hard lock (`LIVE_TRADING_ENABLED=false`) makes LIVE impossible, whatever you click. Each account has a **LIVE readiness checklist** on the Brokers page that shows what evidence is still missing. See [ROADMAP.md](ROADMAP.md#live-readiness).
