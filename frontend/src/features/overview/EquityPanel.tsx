"use client";

import { LineChart } from "lucide-react";
import { useMemo } from "react";
import { TimeSeriesChart } from "@/components/charts/TimeSeriesChart";
import { toSeries } from "@/components/charts/theme";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/Misc";
import { formatMoney } from "@/lib/format";
import type { Overview } from "@/lib/types";

export function EquityPanel({ data }: { data: Overview }) {
  const series = useMemo(() => toSeries(data.equity_series, (p) => p.t, (p) => p.equity), [data.equity_series]);
  const account = data.accounts.find((a) => a.id === data.equity_series_account);
  return (
    <Card>
      <CardHeader title="Equity" description={account ? `${account.label} · ${account.environment}` : "Account value over time"} />
      <CardBody>
        {series.length >= 2 ? (
          <TimeSeriesChart data={series} label="Account equity" format={(v) => formatMoney(v)} />
        ) : (
          <EmptyState icon={LineChart} title="Not enough history yet">
            The equity curve appears after the robot has recorded a few account snapshots (every 15 minutes while an
            account is connected).
          </EmptyState>
        )}
      </CardBody>
    </Card>
  );
}
