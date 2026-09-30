import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Card } from "./Card";

interface PlannedFeatureProps {
  icon: LucideIcon;
  title: string;
  phase: string;
  children: ReactNode;
  /** What the finished screen will show — sets expectations honestly. */
  willShow: string[];
}

/**
 * Honest empty state for screens whose engine is not built yet.
 * Never renders sample data pretending to be real.
 */
export function PlannedFeature({ icon: Icon, title, phase, children, willShow }: PlannedFeatureProps) {
  return (
    <Card className="px-6 py-10">
      <div className="mx-auto max-w-xl text-center">
        <div className="mx-auto mb-4 flex size-10 items-center justify-center rounded-lg border border-line bg-surface-raised">
          <Icon aria-hidden className="size-5 text-fg-muted" />
        </div>
        <p className="text-xs font-medium tracking-wide text-fg-subtle uppercase">Arrives in {phase}</p>
        <h2 className="mt-1 text-base font-semibold text-fg">{title}</h2>
        <div className="mt-2 text-sm leading-relaxed text-fg-muted">{children}</div>
        <ul className="mx-auto mt-6 grid max-w-md gap-2 text-left text-sm text-fg-muted sm:grid-cols-2">
          {willShow.map((item) => (
            <li key={item} className="flex items-start gap-2">
              <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-fg-subtle" />
              {item}
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}
