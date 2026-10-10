"use client";

import { FlaskConical } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Notice } from "@/components/app/states";
import { Term } from "@/components/app/term";
import { useAppData } from "@/components/providers/AppDataProvider";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, ApiError } from "@/lib/api";
import { contractProblems, specForFamily } from "@/lib/contracts";
import { useApi } from "@/lib/hooks";
import type { Account, Backtest, ContractFamily, ContractSpec, Dataset, RiskProfile, Strategy, Timeframe } from "@/lib/types";
import { ContractFields } from "./ContractFields";
import { latestVersion, strategyTimeframe } from "./strategyUtils";

const TIMEFRAMES: { value: Timeframe; label: string; minutes: number }[] = [
  { value: "M1", label: "1-minute candles", minutes: 1 },
  { value: "M5", label: "5-minute candles", minutes: 5 },
  { value: "M15", label: "15-minute candles", minutes: 15 },
  { value: "M30", label: "30-minute candles", minutes: 30 },
  { value: "H1", label: "1-hour candles", minutes: 60 },
  { value: "H4", label: "4-hour candles", minutes: 240 },
  { value: "D1", label: "Daily candles", minutes: 1440 },
];

const PERIODS = [
  { days: 30, label: "Last 30 days" },
  { days: 90, label: "Last 90 days" },
  { days: 180, label: "Last 6 months" },
  { days: 365, label: "Last year" },
];

const SYNTHETIC = "synthetic";

/** Practice data on short candles makes many bars, so its period is capped (the server checks too). */
export const PRACTICE_MAX_DAYS: Partial<Record<Timeframe, number>> = { M1: 60, M5: 365 };

type Phase = "idle" | "data" | "queue";

/** Profile limits the backtest's risk engine should use (same rules as live). */
function riskFromProfile(profile: RiskProfile | null, stake: string): Record<string, unknown> {
  const base: Record<string, unknown> = profile
    ? Object.fromEntries(Object.entries(profile).filter(([k]) => !["id", "name", "user_id", "created_at", "updated_at", "accounts_count"].includes(k)))
    : {};
  return { ...base, stake_amount: stake };
}

/** A dataset with the right market + candles covering the period (reuse instead of downloading again). */
export function findDataset(datasets: Dataset[], symbol: string, timeframe: string, source: "broker" | "synthetic", start: Date, end: Date): Dataset | null {
  const day = 86_400_000;
  return datasets.find((d) => d.symbol === symbol && d.timeframe === timeframe && d.source === source && d.first_bar && d.last_bar
    && new Date(d.first_bar).getTime() <= start.getTime() + day && new Date(d.last_bar).getTime() >= end.getTime() - 2 * day) ?? null;
}

/**
 * "Test on history" — one guided flow: market, period and price data
 * (downloaded from the user's own connection, or labelled practice data),
 * then how each trade works and the stake. Runs as a queued job; the report
 * page shows progress and results.
 */
export function BacktestDialog({ strategy, open, onOpenChange }: { strategy: Strategy | null; open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-2xl">
        {strategy && open && <BacktestForm key={strategy.id} strategy={strategy} onClose={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  );
}

function defaultDuration(tf: Timeframe): { duration: number; duration_unit: "m" | "h" } {
  const minutes = (TIMEFRAMES.find((t) => t.value === tf)?.minutes ?? 5) * 5;
  return minutes >= 60 && minutes % 60 === 0 ? { duration: minutes / 60, duration_unit: "h" } : { duration: minutes, duration_unit: "m" };
}

function BacktestForm({ strategy, onClose }: { strategy: Strategy; onClose: () => void }) {
  const router = useRouter();
  const { accounts, account: selected } = useAppData();
  const datasets = useApi<Dataset[]>("/datasets");
  const profiles = useApi<RiskProfile[]>("/risk/profiles");
  // Paper connections simulate prices live and keep no past prices to download.
  const canDownload = (a: Account) => a.connector_type !== "paper" && a.capabilities?.historical_candles !== false && a.connection_status === "CONNECTED";
  const [source, setSource] = useState<string>(() => (selected && canDownload(selected) ? selected.id : SYNTHETIC));
  const account = accounts?.find((a) => a.id === source) ?? null;
  const isDeriv = account?.connector_type === "deriv";
  const strategyTf = strategyTimeframe(strategy);
  const [timeframe, setTimeframe] = useState<Timeframe>(strategyTf);
  const [symbol, setSymbol] = useState(strategy.details?.suggested_symbols?.[0] ?? "R_75");
  const [days, setDays] = useState(30);
  const suggestion = strategy.details?.suggested_contract;
  const [spec, setSpec] = useState<ContractSpec>(() => {
    const family: ContractFamily = suggestion?.contract_family ?? "RISE_FALL";
    return specForFamily(family, family === "RISE_FALL" && !suggestion?.duration ? defaultDuration(strategyTf) : suggestion ?? {});
  });
  const profile = profiles.data?.find((p) => p.id === (account ?? selected)?.risk_profile?.id) ?? profiles.data?.[0] ?? null;
  const [stake, setStake] = useState<string>("");
  const stakeValue = stake || profile?.stake_amount || "1.00";
  const [payout, setPayout] = useState("0.95");
  const [capital, setCapital] = useState<string>("");
  const capitalValue = capital || String(Math.max(100, Math.round(Number(account?.balance ?? selected?.balance ?? 1000)) || 1000));
  const currency = account?.currency ?? "USD";
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);

  const families: ContractFamily[] = isDeriv ? ["RISE_FALL", "MULTIPLIER"] : ["RISE_FALL", "MULTIPLIER", "SPOT"];
  const errors = contractProblems({ ...spec, stake: spec.contract_family === "SPOT" ? null : stakeValue }, null, { isDeriv, maxStake: null });
  const payoutNum = Number(payout);
  const payoutError = spec.contract_family === "RISE_FALL" && !(payoutNum >= 0.01 && payoutNum <= 2) ? "Enter a number between 0.01 and 2 (0.95 means a win pays 95% of the stake as profit)." : null;
  const tfMinutes = TIMEFRAMES.find((t) => t.value === timeframe)?.minutes ?? 5;
  const tooMuchData = days * 1440 / tfMinutes > 120_000;
  // Practice data: any candle size, with a capped period on 1- and 5-minute candles.
  const practiceMaxDays = PRACTICE_MAX_DAYS[timeframe] ?? 3650;
  const practiceTooLong = !account && days > practiceMaxDays;
  const invalid = practiceTooLong || !symbol.trim() || Object.keys(errors).length > 0 || Boolean(payoutError) || !(Number(capitalValue) > 0) || tooMuchData;
  const version = latestVersion(strategy);

  const { start, end } = useMemo(() => {
    const e = new Date();
    e.setUTCHours(0, 0, 0, 0);
    return { start: new Date(e.getTime() - days * 86_400_000), end: e };
  }, [days]);

  const run = async () => {
    if (!version) return;
    setError(null);
    setProblems([]);
    try {
      setPhase("data");
      const sym = symbol.trim();
      const kind = account ? "broker" : "synthetic";
      let dataset = findDataset(datasets.data ?? [], sym, timeframe, kind, start, end);
      if (!dataset) {
        dataset = account
          ? await api<Dataset>("/datasets/download", { method: "POST", body: { account_id: account.id, symbol: sym, timeframe, start: start.toISOString(), end: end.toISOString() } })
          : await api<Dataset>("/datasets/synthetic", { method: "POST", body: { symbol: sym, timeframe, days: Math.max(30, days) } });
      }
      setPhase("queue");
      const from = dataset.first_bar && new Date(dataset.first_bar) > start ? new Date(dataset.first_bar) : start;
      const to = dataset.last_bar && new Date(dataset.last_bar) < end ? new Date(dataset.last_bar) : end;
      const contract = { ...spec, stake: spec.contract_family === "SPOT" ? null : stakeValue };
      const created = await api<Backtest>("/backtests", {
        method: "POST",
        body: {
          mode: "single",
          strategy_version_id: version.id,
          dataset_id: dataset.id,
          start: from.toISOString(),
          end: to.toISOString(),
          initial_capital: capitalValue,
          name: `${strategy.name} · ${sym} ${timeframe}`,
          risk: riskFromProfile(profile, stakeValue),
          contract,
          payout_ratio: spec.contract_family === "RISE_FALL" ? payout : undefined,
        },
      });
      toast.success("Test started", { description: "It runs on the server — you can leave this page." });
      onClose();
      router.push(`/strategies/backtests/${created.id}`);
    } catch (e) {
      setPhase("idle");
      if (e instanceof ApiError) {
        setError(e.message);
        setProblems(Object.values(e.fieldErrors).flat());
      } else {
        setError("Something went wrong.");
      }
    }
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>Test {strategy.name} on history</DialogTitle>
        <DialogDescription>
          See how these rules would have traded on past prices — using the same risk rules as live trading. Past results don&apos;t guarantee future results.
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-6">
        <section className="space-y-3">
          <h3 className="text-sm font-semibold text-fg">1. Market and period</h3>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="grid gap-1.5">
              <Label htmlFor="bt-symbol">Market (symbol)</Label>
              <Input id="bt-symbol" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} list="bt-symbols" autoComplete="off" />
              <datalist id="bt-symbols">{(strategy.details?.suggested_symbols ?? []).map((s) => <option key={s} value={s} />)}</datalist>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="bt-tf">Candles</Label>
              <Select value={timeframe} onValueChange={(v) => setTimeframe(v as Timeframe)}>
                <SelectTrigger id="bt-tf" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>{TIMEFRAMES.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}{t.value === strategyTf ? " (strategy)" : ""}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="bt-period">Period</Label>
              <Select value={String(days)} onValueChange={(v) => setDays(Number(v))}>
                <SelectTrigger id="bt-period" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>{PERIODS.map((p) => <SelectItem key={p.days} value={String(p.days)}>{p.label}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>
          {(strategy.details?.suggested_symbols?.length ?? 0) > 0 && (
            <p className="text-xs text-fg-subtle">Designed for: {strategy.details!.suggested_symbols!.join(", ")}.</p>
          )}
          {tooMuchData && <p role="alert" className="text-xs text-negative">That is a lot of candles — choose a shorter period or longer candles.</p>}
          {timeframe !== strategyTf && <p className="text-xs text-fg-subtle">The strategy decides on {strategyTf} candles; shorter candles only make exits more precise.</p>}
        </section>

        <section className="space-y-3">
          <h3 className="text-sm font-semibold text-fg">2. Price data</h3>
          <div className="grid gap-1.5">
            <Label htmlFor="bt-source">Use prices from</Label>
            <Select value={source} onValueChange={setSource}>
              <SelectTrigger id="bt-source" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {(accounts ?? []).filter(canDownload).map((a) => <SelectItem key={a.id} value={a.id}>{a.label} — download past prices ({a.broker})</SelectItem>)}
                <SelectItem value={SYNTHETIC}>Practice data — generated by 2kPilot</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {account ? (
            <p className="text-xs text-fg-subtle">Past candles are downloaded from your {account.broker} connection (public market data). Data you already have is reused.</p>
          ) : practiceTooLong ? (
            <Notice tone="danger" title={`Practice data on ${timeframe} candles covers at most ${practiceMaxDays} days`}>
              Choose a shorter period, or longer candles.
            </Notice>
          ) : (
            <Notice tone="warning" title="Practice data says nothing about real markets">
              2kPilot generates {timeframe} candles to test that everything works — the same simulated prices Paper accounts trade. Use real prices before drawing any conclusion.
            </Notice>
          )}
        </section>

        <section className="space-y-3">
          <h3 className="text-sm font-semibold text-fg">3. How each trade works</h3>
          <ContractFields spec={spec} onChange={setSpec} isDeriv={isDeriv} errors={errors} families={families} />
          {strategy.details?.suggested_contract_note && <p className="text-xs text-fg-subtle">{strategy.details.suggested_contract_note}</p>}
          <div className="grid items-start gap-3 sm:grid-cols-3">
            {spec.contract_family !== "SPOT" && (
              <div className="grid gap-1.5">
                <Label htmlFor="bt-stake"><Term id="stake">Stake</Term> per trade ({currency})</Label>
                <Input id="bt-stake" type="number" inputMode="decimal" min={0} step="0.01" className="num" value={stakeValue} onChange={(e) => setStake(e.target.value)} aria-invalid={Boolean(errors.stake)} />
                {errors.stake && <p className="text-xs text-negative">{errors.stake}</p>}
              </div>
            )}
            {spec.contract_family === "RISE_FALL" && (
              <div className="grid gap-1.5">
                <Label htmlFor="bt-payout"><Term id="backtestPayoutEstimate">Payout (estimate)</Term></Label>
                <Input id="bt-payout" type="number" inputMode="decimal" min={0.01} max={2} step="0.01" className="num" value={payout} onChange={(e) => setPayout(e.target.value)} aria-invalid={Boolean(payoutError)} aria-describedby="bt-payout-help" />
                <p id="bt-payout-help" className="text-xs text-fg-subtle">{payoutError ?? "0.95 = a win earns 95% of the stake. Real payouts vary with every quote."}</p>
              </div>
            )}
            <div className="grid gap-1.5">
              <Label htmlFor="bt-capital">Starting balance ({currency})</Label>
              <Input id="bt-capital" type="number" inputMode="decimal" min={1} className="num" value={capitalValue} onChange={(e) => setCapital(e.target.value)} />
            </div>
          </div>
          {profile && <p className="text-xs text-fg-subtle">Your “{profile.name}” risk limits apply, exactly as in live trading (losses in a row, daily limits, trades per day).</p>}
        </section>

        {phase !== "idle" && (
          <Notice tone="info" title={phase === "data" ? "Getting the price data…" : "Starting the test…"}>
            {phase === "data" ? (account ? "Downloading candles from your broker. This can take a minute." : "Generating practice data.") : "Queuing the test on the server."}
          </Notice>
        )}
        {error && (
          <Notice tone="danger" title="The test didn't start">
            <p>{error}</p>
            {problems.length > 0 && <ul className="mt-1 list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
          </Notice>
        )}
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={phase !== "idle"}>Cancel</Button>
        <Button onClick={() => void run()} disabled={invalid || phase !== "idle" || !version}>
          <FlaskConical aria-hidden /> {phase === "idle" ? "Run the test" : "Working…"}
        </Button>
      </DialogFooter>
    </>
  );
}
