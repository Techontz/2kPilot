/**
 * Plain-language definitions shown inline via <Term>. Written for someone
 * learning Forex: what it is, and why it matters to the robot.
 */

export interface GlossaryEntry {
  term: string;
  definition: string;
  why?: string;
}

export const GLOSSARY = {
  balance: {
    term: "Balance",
    definition: "The money in your account from closed trades only. It ignores trades that are still open.",
    why: "Balance only changes when a trade is closed.",
  },
  equity: {
    term: "Equity",
    definition: "Your balance plus or minus the profit or loss of all open trades — what the account is worth right now.",
    why: "If every trade were closed this second, equity is roughly what you would have.",
  },
  margin: {
    term: "Margin",
    definition: "Money the broker sets aside as a deposit while your trades are open. It is not a fee.",
    why: "Too little margin available means new trades can be refused or positions closed by the broker.",
  },
  freeMargin: {
    term: "Free Margin",
    definition: "Equity minus margin: the amount still available to open new trades.",
  },
  pip: {
    term: "Pip",
    definition: "The standard unit of price movement. For most pairs 1 pip = 0.0001 (e.g. 1.0850 → 1.0851). For JPY pairs 1 pip = 0.01.",
  },
  lot: {
    term: "Lot",
    definition: "Trade size. 1.00 lot = 100,000 units of the base currency; 0.10 is a mini lot; 0.01 is a micro lot.",
    why: "Lot size, together with the stop-loss distance, decides how much money a trade can lose.",
  },
  spread: {
    term: "Spread",
    definition: "The gap between the buy (ask) and sell (bid) price. It is a cost you pay on every trade.",
    why: "Wide spreads — common around news or at market open — make trades more expensive.",
  },
  drawdown: {
    term: "Drawdown",
    definition: "How far the account has fallen from its highest point, usually shown as a percentage.",
    why: "The risk engine stops trading when drawdown hits the limit you set.",
  },
  riskReward: {
    term: "Risk/Reward",
    definition: "Potential loss compared with potential gain. 1:2 means risking $1 to try to make $2.",
  },
  stopLoss: {
    term: "Stop Loss",
    definition: "A price at which a losing trade is closed automatically to cap the loss.",
    why: "2kFX refuses any trade without a stop loss.",
  },
  takeProfit: {
    term: "Take Profit",
    definition: "A price at which a winning trade is closed automatically to lock in the gain.",
  },
  profitFactor: {
    term: "Profit Factor",
    definition: "Total money won divided by total money lost. Above 1.0 means more was won than lost.",
  },
  expectancy: {
    term: "Expectancy",
    definition: "The average amount a strategy made (or lost) per trade over many trades.",
    why: "A strategy needs positive expectancy after costs to be worth running.",
  },
  killSwitch: {
    term: "Kill Switch",
    definition: "The STOP ALL TRADING control. It immediately blocks every new order and pauses automated strategies.",
    why: "It does not close trades that are already open — that is a separate, deliberate action.",
  },
  demoAccount: {
    term: "Demo account",
    definition: "A broker account funded with virtual money. Real prices, no real risk.",
  },
  liveAccount: {
    term: "Live account",
    definition: "A broker account with real money. Every loss is real.",
  },
  backtest: {
    term: "Backtest",
    definition: "Running a strategy on historical prices to see how it would have behaved.",
    why: "Good past results do not guarantee future results.",
  },
  openRisk: {
    term: "Open risk",
    definition: "How much money you would lose if every open trade hit its stop loss.",
  },
  pnl: {
    term: "P/L",
    definition: "Profit and loss. Positive means profit, negative means loss.",
  },
} satisfies Record<string, GlossaryEntry>;

export type GlossaryKey = keyof typeof GLOSSARY;
