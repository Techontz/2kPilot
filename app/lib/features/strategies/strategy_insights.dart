import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/format.dart';
import '../../core/insights.dart';
import '../../core/models/models.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/badges.dart';
import '../../ui/widgets/states.dart';
import 'backtest_report_screen.dart';

/// The facts behind a code strategy: where it may run, its parameters and risk
/// caps, the latest decision with the market regime, test results by market
/// and by regime with the demo-forward-testing gate. Nothing here switches
/// anything (the admin emergency stop is website-only).
class StrategyInsights extends StatelessWidget {
  const StrategyInsights({super.key, required this.strategy});
  final Strategy strategy;

  @override
  Widget build(BuildContext context) {
    final s = strategy;
    final c = context.c;
    final symbols = allowedSymbols(s);
    final params = latestVersion(s)?.parameters;
    final caps = riskCaps(params);
    final rows = parameterRows(s);
    final watched = s.assignments.where((a) => a.enabled).firstOrNull ?? s.assignments.firstOrNull;
    final tested = s.backtestsBySymbol ?? (s.backtest == null ? const <BacktestHeadline>[] : [s.backtest!]);
    final stop = s.entriesDisabled;
    final signals = s.assignments.map((a) => a.lastSignalAt).whereType<String>().toList()..sort();
    final lastRun = signals.isEmpty ? null : signals.last;
    final verdict = validationVerdict(s);

    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (stop != null)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Notice(
            tone: NoticeTone.danger,
            title: 'New trades are stopped by an administrator',
            message: '${stop.reason ?? 'No reason given.'}${stop.inherited ? ' (set on the built-in this copy comes from)' : ''} Open positions are not closed.',
          ),
        ),
      Row(children: [
        Expanded(child: _Stat(label: 'Status', child: stop != null ? const Pill('Entries stopped', tone: PillTone.negative, dot: true) : const Pill('Entries allowed', tone: PillTone.positive, dot: true))),
        const SizedBox(width: 8),
        Expanded(child: _Stat(label: 'Last trade idea', child: Text(lastRun != null ? formatRelative(lastRun) : 'None yet'))),
      ]),
      const SizedBox(height: 8),
      _Stat(label: 'Markets', child: Text(symbols != null ? symbols.join(', ') : 'Any market')),
      const SizedBox(height: 8),
      _Stat(label: 'Contracts', child: Text(contractSupportText(allowedFamilies(s)))),
      if (watched != null) Padding(padding: const EdgeInsets.only(top: 10), child: LatestDecision(assignmentId: watched.id, symbol: watched.symbol)),
      if (caps.isNotEmpty)
        Container(
          margin: const EdgeInsets.only(top: 10),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: c.raised, borderRadius: BorderRadius.circular(12)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text.rich(TextSpan(children: [
              const TextSpan(text: 'Risk caps', style: TextStyle(fontWeight: FontWeight.w700)),
              TextSpan(text: ' — they only tighten your risk profile', style: TextStyle(color: c.subtle)),
            ]), style: context.text.bodySmall),
            for (final cap in caps)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Row(children: [
                  Expanded(child: Text(cap.label, style: context.text.bodySmall)),
                  Text(cap.value, style: tnum(const TextStyle(fontWeight: FontWeight.w800, fontSize: 13.5))),
                ]),
              ),
          ]),
        ),
      if (rows.isNotEmpty)
        _Fold(
          title: 'Parameters',
          meta: '${rows.length}',
          child: Column(children: [
            for (final r in rows)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Expanded(child: Text(r.label, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13.5))),
                    const SizedBox(width: 8),
                    Flexible(child: Text(r.value, textAlign: TextAlign.right, style: tnum(const TextStyle(fontWeight: FontWeight.w800, fontSize: 13.5)))),
                  ]),
                  if (r.description != null) Text(r.description!, style: context.text.labelSmall?.copyWith(fontWeight: FontWeight.w500, letterSpacing: 0, fontSize: 12)),
                ]),
              ),
          ]),
        ),
      if (tested.isNotEmpty)
        _Fold(
          title: 'Tests on history',
          meta: '${tested.length} ${tested.length == 1 ? 'market' : 'markets'}',
          badge: verdict.gate == null ? null : Pill(verdict.qualifies ? 'Qualifies' : 'Not validated', tone: verdict.qualifies ? PillTone.positive : PillTone.warning),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('Latest test on each market. Tap one for the full report.', style: context.text.bodySmall),
            const SizedBox(height: 8),
            for (final b in tested)
              Container(
                margin: const EdgeInsets.only(bottom: 8),
                decoration: BoxDecoration(color: c.raised, borderRadius: BorderRadius.circular(12)),
                child: InkWell(
                  borderRadius: BorderRadius.circular(12),
                  onTap: () => context.push('/strategies/backtests/${b.id}'),
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Row(children: [
                        Text('${b.symbol} ${b.timeframe}', style: const TextStyle(fontWeight: FontWeight.w800)),
                        if (b.dataSource == 'synthetic') ...[const SizedBox(width: 8), const Pill('Synthetic', tone: PillTone.warning)],
                        const Spacer(),
                        Icon(Icons.chevron_right_rounded, color: c.subtle),
                      ]),
                      const SizedBox(height: 6),
                      MiniStats([
                        ('Trades', '${b.trades ?? 0}'),
                        ('Wins', formatPct(b.winRate, digits: 0)),
                        ('Profit factor', b.profitFactor == null ? emDash : formatNumber(b.profitFactor)),
                        ('Per trade', b.expectancy == null ? emDash : formatSignedCurrency(b.expectancy, 'USD')),
                        ('Drawdown', formatPct(b.maxDrawdownPct, digits: 1)),
                      ]),
                      if (b.validation != null) Padding(padding: const EdgeInsets.only(top: 10), child: ValidationCard(gate: b.validation!, compact: true)),
                    ]),
                  ),
                ),
              ),
          ]),
        ),
      if (s.backtest?.byRegime.isNotEmpty ?? false)
        _Fold(
          title: 'Results by market regime',
          meta: 'latest test',
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('The regime when each trade was taken (closed candles only).', style: context.text.bodySmall),
            const SizedBox(height: 8),
            GroupStatList(groups: s.backtest!.byRegime, currency: 'USD'),
          ]),
        ),
    ]);
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.child});
  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
        decoration: BoxDecoration(color: context.c.raised, borderRadius: BorderRadius.circular(12)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: context.text.labelSmall?.copyWith(letterSpacing: 0, fontSize: 12)),
          const SizedBox(height: 4),
          DefaultTextStyle.merge(style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13.5), child: child),
        ]),
      );
}

class _Fold extends StatelessWidget {
  const _Fold({required this.title, required this.child, this.meta, this.badge});
  final String title;
  final String? meta;
  final Widget? badge;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      margin: const EdgeInsets.only(top: 10),
      decoration: BoxDecoration(borderRadius: BorderRadius.circular(12), border: Border.all(color: c.border)),
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 12),
          childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
          title: Text.rich(TextSpan(children: [
            TextSpan(text: title, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 14.5)),
            if (meta != null) TextSpan(text: '  $meta', style: TextStyle(color: c.subtle, fontSize: 12.5, fontWeight: FontWeight.w600)),
          ])),
          trailing: Row(mainAxisSize: MainAxisSize.min, children: [?badge, const SizedBox(width: 4), Icon(Icons.expand_more_rounded, color: c.subtle)]),
          children: [child],
        ),
      ),
    );
  }
}

class MiniStats extends StatelessWidget {
  const MiniStats(this.items, {super.key});
  final List<(String, String)> items;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, box) {
      final w = (box.maxWidth - 16) / 3;
      return Wrap(spacing: 8, runSpacing: 8, children: [
        for (final i in items)
          SizedBox(
            width: w,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(i.$1, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.text.labelSmall?.copyWith(letterSpacing: 0, fontSize: 11.5)),
              const SizedBox(height: 2),
              Text(i.$2, maxLines: 1, overflow: TextOverflow.ellipsis, style: tnum(const TextStyle(fontWeight: FontWeight.w800, fontSize: 13.5))),
            ]),
          ),
      ]);
    });
  }
}

/// The latest closed candle the strategy checked: BUY / SELL / No trade, and the regime.
class LatestDecision extends ConsumerWidget {
  const LatestDecision({super.key, required this.assignmentId, required this.symbol});
  final String assignmentId;
  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final data = ref.watch(evaluationsProvider((assignmentId, 1))).data;
    if (data == null) return const SizedBox.shrink();
    final e = data.evaluations.firstOrNull;
    if (e == null) {
      return Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(borderRadius: BorderRadius.circular(12), border: Border.all(color: c.border)),
        child: Text('No completed candle checked on $symbol yet.', style: context.text.bodySmall),
      );
    }
    final decision = decisionOf(e);
    final regime = regimeOf(e);
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(borderRadius: BorderRadius.circular(12), border: Border.all(color: c.border)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
          Text('Latest signal', style: context.text.labelMedium),
          Pill(decision == 'NO_TRADE' ? 'No trade' : decision ?? emDash, tone: decision == 'BUY' ? PillTone.positive : decision == 'SELL' ? PillTone.negative : PillTone.neutral),
          if (regime != null) Pill(regimeLabel[regime.regime] ?? regime.regime, tone: pillToneOf(regimeTone[regime.regime]!)),
        ]),
        const SizedBox(height: 8),
        Text(e.summary, style: const TextStyle(fontSize: 14)),
        if (regime != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text('Regime: ${regime.reason}', style: context.text.bodySmall)),
        Padding(padding: const EdgeInsets.only(top: 6), child: Text('Closed candle on $symbol · ${formatDateTime(e.barTime)}', style: context.text.labelSmall?.copyWith(fontWeight: FontWeight.w500, letterSpacing: 0, fontSize: 12))),
      ]),
    );
  }
}
