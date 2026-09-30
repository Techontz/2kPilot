import { Card, CardHeader } from "@/components/ui/Card";
import { Term } from "@/components/ui/Term";

const LIMITS: { label: React.ReactNode; detail: string; status?: string }[] = [
  { label: "Risk per trade", detail: "Maximum % of equity a single trade may lose at its stop." },
  { label: <>Daily loss limit</>, detail: "Trading stops for the day once this loss is reached." },
  { label: "Weekly loss limit", detail: "Trading stops for the week once this loss is reached." },
  { label: <><Term id="drawdown" /> limit</>, detail: "Trading stops when the account falls this far from its peak." },
  { label: "Max open positions", detail: "Total simultaneous positions across all strategies." },
  { label: "Max trades per day", detail: "Prevents runaway strategies from over-trading." },
  { label: <><Term id="spread" /> protection</>, detail: "Skip entries when the spread is wider than allowed." },
  { label: <><Term id="stopLoss" /> required</>, detail: "Every order must carry a stop loss. Cannot be switched off.", status: "Mandatory" },
];

export function RiskLimits() {
  return (
    <Card>
      <CardHeader
        title="Risk limits"
        description="Configurable when the risk engine ships (Phase 5). No strategy can bypass these."
      />
      <ul className="divide-y divide-line">
        {LIMITS.map((limit, i) => (
          <li key={i} className="flex items-start justify-between gap-4 px-5 py-3">
            <div>
              <p className="text-sm text-fg">{limit.label}</p>
              <p className="mt-0.5 text-xs text-fg-subtle">{limit.detail}</p>
            </div>
            <span className="shrink-0 text-xs text-fg-subtle">{limit.status ?? "Not configured"}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
