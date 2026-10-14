import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/format.dart';
import '../../core/models/models.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/badges.dart';
import '../../ui/widgets/states.dart';
import '../history/trade_detail_screen.dart';

/// "Why no trade?" — every closed candle the strategy checked, and what the risk limits said.
Future<void> showEvaluations(BuildContext context, Assignment a) {
  return showModalBottomSheet<void>(useRootNavigator: true, 
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) => DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.85,
      maxChildSize: 0.95,
      builder: (ctx, scroll) => _Evaluations(assignment: a, scroll: scroll),
    ),
  );
}

class _Evaluations extends ConsumerWidget {
  const _Evaluations({required this.assignment, required this.scroll});
  final Assignment assignment;
  final ScrollController scroll;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final res = ref.watch(evaluationsProvider((assignment.id, 50)));
    final d = res.data;
    return ListView(controller: scroll, padding: const EdgeInsets.fromLTRB(20, 0, 20, 32), children: [
      Text("Why ${assignment.symbol} did — or didn't — trade", style: context.text.titleLarge),
      const SizedBox(height: 4),
      Text('The rules are checked each time a candle closes. Trades the rules wanted but your risk limits refused are listed with the reason.', style: context.text.bodySmall),
      const SizedBox(height: 16),
      if (res.error != null && d == null)
        ErrorView(error: res.error, onRetry: () => ref.read(evaluationsProvider((assignment.id, 50)).notifier).load())
      else if (d == null)
        const ListSkeleton(rows: 4)
      else ...[
        Text('Trade ideas and risk decisions', style: context.text.titleSmall),
        const SizedBox(height: 8),
        if (d.signals.isEmpty) Text("No trade ideas yet — the rules haven't matched.", style: context.text.bodySmall),
        for (final s in d.signals)
          _Box(children: [
            Row(children: [
              Expanded(child: Text('${s.side == 'BUY' ? 'Up' : 'Down'} · candle ${formatDateTime(s.barTime)}', style: const TextStyle(fontWeight: FontWeight.w600))),
              Pill(
                s.status == 'EXECUTED' ? 'Traded' : s.status == 'REJECTED' ? 'Refused by limits' : s.status.toLowerCase(),
                tone: switch (s.status) { 'EXECUTED' => PillTone.positive, 'REJECTED' => PillTone.warning, 'FAILED' => PillTone.negative, _ => PillTone.neutral },
              ),
            ]),
            const SizedBox(height: 4),
            Text(s.rejectionReason ?? s.reasons.join('; '), style: context.text.bodySmall),
          ]),
        const SizedBox(height: 18),
        Text('Every closed candle', style: context.text.titleSmall),
        const SizedBox(height: 8),
        if (d.evaluations.isEmpty) Text('No candles checked yet. Checks happen while trading is started and the strategy is active.', style: context.text.bodySmall),
        for (final e in d.evaluations)
          _Box(children: [
            Row(children: [
              Expanded(child: Text('${formatDateTime(e.barTime)} · ${formatRelative(e.barTime)}', style: tnum(context.text.labelSmall?.copyWith(letterSpacing: 0, fontSize: 12)))),
              Pill(
                switch (e.outcome) { 'SIGNAL' => 'Signal', 'INSUFFICIENT_DATA' => 'Not enough data yet', _ => 'No setup' },
                tone: switch (e.outcome) { 'SIGNAL' => PillTone.positive, 'INSUFFICIENT_DATA' => PillTone.warning, _ => PillTone.neutral },
              ),
            ]),
            const SizedBox(height: 4),
            Text(e.summary, style: const TextStyle(fontSize: 14)),
            if (e.checks.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: ChecksList(e.checks)),
          ]),
      ],
    ]);
  }
}

class _Box extends StatelessWidget {
  const _Box({required this.children});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(borderRadius: BorderRadius.circular(12), border: Border.all(color: context.c.border)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children),
      );
}
