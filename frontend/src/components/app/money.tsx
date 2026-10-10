import { cn } from "@/lib/utils";
import { formatCurrency, formatSignedCurrency, pnlTone } from "@/lib/format";

type Value = string | number | null | undefined;

/** Money in the account currency, tabular figures ("$1,234.56"). */
export function Money({ value, currency, className }: { value: Value; currency?: string | null; className?: string }) {
  return <span className={cn("num", className)}>{formatCurrency(value, currency)}</span>;
}

/**
 * Profit/loss: always signed (+ / −) so colour is never the only cue;
 * green for profit, red for loss.
 */
export function PnlText({ value, currency, className }: { value: Value; currency?: string | null; className?: string }) {
  const tone = pnlTone(value);
  return (
    <span className={cn("num", tone === "positive" && "text-positive", tone === "negative" && "text-negative", className)}>
      {formatSignedCurrency(value, currency)}
    </span>
  );
}
