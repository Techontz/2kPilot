import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_client.dart';
import '../../core/contracts.dart';
import '../../core/format.dart';
import '../../core/insights.dart';
import '../../core/models/models.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/badges.dart';
import '../../ui/widgets/dialogs.dart';
import '../../ui/widgets/money.dart';
import '../../ui/widgets/states.dart';
import 'backtest_sheet.dart';

class BacktestStatusPill extends StatelessWidget {
  const BacktestStatusPill(this.b, {super.key});
  final Backtest b;

  @override
  Widget build(BuildContext context) => Pill(
        backtestStatusLabel(b),
        tone: switch (b.status) { 'FAILED' => PillTone.negative, 'RUNNING' => PillTone.info, _ => PillTone.neutral },
        dot: b.running,
      );
}

/// Every test you ran, newest first; running ones show progress.
class BacktestsList extends ConsumerWidget {
  const BacktestsList({super.key});

  Future<void> _delete(BuildContext context, WidgetRef ref, Backtest b) => confirmAction(
        context,
        title: 'Delete this test?',
        body: const ['The results and simulated trades are removed. Your strategy is not affected.'],
        confirmLabel: 'Delete',
        destructive: true,
        onConfirm: () async {
          try {
            await ref.read(apiClientProvider).delete('/backtests/${b.id}');
            ref.read(backtestsProvider.notifier).load();
            if (context.mounted) showSnack(context, 'Test deleted');
            return null;
          } on ApiException catch (e) {
            return e.message;
          }
        },
      );

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final res = ref.watch(backtestsProvider);
    final runs = res.data;
    final strategies = ref.watch(strategiesProvider.select((r) => r.data));
    final first = strategies?.where((s) => !s.builtIn).firstOrNull;
    final List<Widget> children;
    if (runs == null) {
      children = [res.error != null ? ErrorView(error: res.error, onRetry: () => ref.read(backtestsProvider.notifier).load()) : const ListSkeleton(rows: 4, height: 120)];
    } else if (runs.isEmpty) {
      children = [
        AppCard(
          child: EmptyState(
            icon: Icons.science_outlined,
            title: 'No tests yet',
            message: 'A test replays past prices through your strategy and your risk limits, so you can see how it would have behaved — before any money is involved.',
            action: first != null
                ? FilledButton.icon(onPressed: () => showBacktestSheet(context, first), icon: const Icon(Icons.science_outlined, size: 18), label: Text('Test ${first.name}'))
                : FilledButton(onPressed: () => context.go('/strategies?tab=templates'), child: const Text('Pick a template')),
          ),
        ),
      ];
    } else {
      children = [
        for (final b in runs)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: AppCard(
              onTap: () => context.push('/strategies/backtests/${b.id}'),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Expanded(child: Text(b.name, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15.5))),
                  if (!b.running)
                    IconButton(
                      tooltip: 'Delete test ${b.name}',
                      visualDensity: VisualDensity.compact,
                      onPressed: () => _delete(context, ref, b),
                      icon: Icon(Icons.delete_outline_rounded, color: c.subtle),
                    ),
                ]),
                Wrap(spacing: 6, runSpacing: 6, children: [
                  BacktestStatusPill(b),
                  if (b.dataSource == 'synthetic') const Pill('Practice data', tone: PillTone.warning),
                ]),
                const SizedBox(height: 6),
                Text('${formatDate(b.start)} – ${formatDate(b.end)}${b.contract != null ? ' · ${familyLabel[b.contract!.contractFamily]}' : ''} · ${formatRelative(b.createdAt)}', style: context.text.bodySmall?.copyWith(fontSize: 12.5)),
                if (b.running)
                  Padding(
                    padding: const EdgeInsets.only(top: 10),
                    child: ClipRRect(borderRadius: BorderRadius.circular(99), child: LinearProgressIndicator(value: b.progress / 100, minHeight: 6, semanticsLabel: 'Progress ${b.progress}%')),
                  ),
                if (b.status == 'FAILED' && b.error != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text(b.error!, style: TextStyle(color: c.negative, fontSize: 13))),
                if (b.metrics != null)
                  Container(
                    margin: const EdgeInsets.only(top: 10),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(color: c.raised, borderRadius: BorderRadius.circular(12)),
                    child: Row(children: [
                      Expanded(child: _Metric('Net P/L', PnlText(b.metrics!.netPnl, currency: 'USD', style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 15)))),
                      Expanded(child: _Metric('Trades', Text('${b.metrics!.trades}', style: tnum(const TextStyle(fontWeight: FontWeight.w800, fontSize: 15))))),
                      Expanded(child: _Metric('Wins', Text(formatPct(b.metrics!.winRate, digits: 0), style: tnum(const TextStyle(fontWeight: FontWeight.w800, fontSize: 15))))),
                    ]),
                  ),
              ]),
            ),
          ),
      ];
    }
    return ListView(padding: const EdgeInsets.fromLTRB(16, 12, 16, 32), physics: const AlwaysScrollableScrollPhysics(), children: children);
  }
}

class _Metric extends StatelessWidget {
  const _Metric(this.label, this.child);
  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: context.text.labelSmall?.copyWith(letterSpacing: 0, fontSize: 12)),
        const SizedBox(height: 2),
        child,
      ]);
}
