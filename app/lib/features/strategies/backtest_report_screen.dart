import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/contracts.dart';
import '../../core/format.dart';
import '../../core/models/models.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/badges.dart';
import '../../ui/widgets/brand.dart';
import '../../ui/widgets/charts.dart';
import '../../ui/widgets/money.dart';
import '../../ui/widgets/states.dart';
import 'backtests_list.dart';
import 'strategy_insights.dart';

/// The result of one "Test on history": progress while it runs, then the honest numbers.
class BacktestReportScreen extends ConsumerWidget {
  const BacktestReportScreen({super.key, required this.id});
  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final res = ref.watch(backtestProvider(id));
    final b = res.data;
    const currency = 'USD';
    final List<Widget> children;
    if (b == null) {
      children = [res.error != null ? ErrorView(error: res.error, onRetry: () => ref.read(backtestProvider(id).notifier).load()) : const ListSkeleton(rows: 5, height: 100)];
    } else {
      final m = b.metrics;
      final notes = (m?.notes ?? const <String>[]).where((n) => !(n.contains('ESTIMATE') && b.warnings.any((w) => w.contains('ESTIMATE'))));
      final warnings = {...b.warnings, ...notes}.toList();
      final contract = b.contract ?? m?.contract;
      children = [
        Row(children: [
          Artwork(seed: b.name, size: 64, radius: 12),
          const SizedBox(width: 14),
          Expanded(
            child: Wrap(spacing: 8, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
              Icon(Icons.science_outlined, size: 18, color: c.brandInk),
              const Text('Test on history', style: TextStyle(fontWeight: FontWeight.w700)),
              BacktestStatusPill(b),
            ]),
          ),
        ]),
        const SizedBox(height: 14),
        Text(b.name, style: context.text.headlineMedium),
        if (m != null)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
              Text('Net result ', style: context.text.bodySmall?.copyWith(fontSize: 14)),
              PnlText(m.netPnl, currency: currency, style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 24)),
            ]),
          ),
        const SizedBox(height: 8),
        if (b.dataSource == 'synthetic') const Padding(padding: EdgeInsets.only(bottom: 6), child: Pill('Practice (synthetic) data', tone: PillTone.warning)),
        Text('${b.symbol} · ${b.timeframe} candles · ${formatDate(b.start)} – ${formatDate(b.end)}', style: context.text.bodySmall?.copyWith(fontSize: 13.5)),
        Text('Starting balance ${formatCurrency(b.initialCapital, currency)}', style: tnum(context.text.bodySmall?.copyWith(fontSize: 13.5))),
        if (contract != null) Text(contractSummary(contract, currency: currency), style: context.text.bodySmall?.copyWith(fontSize: 13.5)),
        if (m?.payoutRatio != null) Text('Payout estimate ${m!.payoutRatio}', style: context.text.bodySmall?.copyWith(fontSize: 13.5)),
        const SizedBox(height: 16),
        if (b.running)
          AppCard(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
                const SizedBox(width: 10),
                Text(b.status == 'QUEUED' ? 'Waiting for a free worker…' : 'Replaying past prices… ${b.progress}%', style: const TextStyle(fontWeight: FontWeight.w700)),
              ]),
              const SizedBox(height: 10),
              ClipRRect(borderRadius: BorderRadius.circular(99), child: LinearProgressIndicator(value: b.progress / 100, minHeight: 6)),
              const SizedBox(height: 8),
              Text('This runs on the server — you can leave and come back. The screen updates by itself.', style: context.text.bodySmall),
            ]),
          ),
        if (b.status == 'FAILED') Notice(tone: NoticeTone.danger, title: 'The test failed', message: b.error),
        if (warnings.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Notice(
              tone: NoticeTone.warning,
              title: 'Read before trusting these numbers',
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [for (final w in warnings) Padding(padding: const EdgeInsets.only(bottom: 3), child: Text('• $w', style: context.text.bodySmall?.copyWith(fontSize: 13)))]),
            ),
          ),
        if (b.validation != null) Padding(padding: const EdgeInsets.only(top: 12), child: ValidationCard(gate: b.validation!)),
        if (m != null) ...[const SizedBox(height: 16), MetricsView(m: m, currency: currency)],
        if (b.status == 'COMPLETED' && b.kind != 'SENSITIVITY') ...[const SizedBox(height: 16), _Trades(id: id, symbol: b.symbol, currency: currency)],
      ];
    }
    return Scaffold(
      appBar: AppBar(title: const Text('Test report')),
      body: RefreshIndicator(
        onRefresh: () async => ref.read(backtestProvider(id).notifier).load(),
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 40), physics: const AlwaysScrollableScrollPhysics(), children: children),
      ),
    );
  }
}

class MetricsView extends StatelessWidget {
  const MetricsView({super.key, required this.m, this.currency});
  final Metrics m;
  final String? currency;

  @override
  Widget build(BuildContext context) {
    final streak = m.longestLosingStreak ?? m.maxConsecutiveLosses;
    final kpis = <(String, Widget, String?)>[
      ('Net profit / loss', PnlText(m.netPnl, currency: currency, style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 20)), m.returnPct != null ? '${formatPct(m.returnPct, signed: true)} of the starting balance' : null),
      ('Win rate', _big(formatPct(m.winRate, digits: 1)), '${m.wins} won · ${m.losses} lost'),
      ('Trades', _big('${m.trades}'), m.outcomes?.entries.map((e) => '${e.value} ${e.key.toLowerCase()}').join(' · ')),
      ('Profit factor', _big(m.profitFactor == null ? emDash : formatNumber(m.profitFactor)), 'Money won ÷ money lost; above 1 = more won'),
      ('Max drawdown', _big(formatPct(m.maxDrawdownPct, digits: 1)), m.maxDrawdown != null ? '${formatCurrency(m.maxDrawdown, currency)} from the peak' : null),
      ('Losing streak', _big('$streak in a row'), null),
      ('Expectancy', _big(m.expectancy == null ? emDash : formatSignedCurrency(m.expectancy, currency)), 'Average result per trade'),
      ('Costs', _big(formatCurrency(m.totalCosts, currency)), m.avgHoldingHours != null ? 'Average trade lasted ${formatDuration(m.avgHoldingHours! * 3600)}' : null),
    ];
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      LayoutBuilder(builder: (context, box) {
        final w = (box.maxWidth - 10) / 2;
        return Wrap(spacing: 10, runSpacing: 10, children: [
          for (final k in kpis)
            SizedBox(
              width: w,
              child: AppCard(
                padding: const EdgeInsets.all(12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(k.$1, style: context.text.labelMedium?.copyWith(fontSize: 12.5)),
                  const SizedBox(height: 6),
                  FittedBox(fit: BoxFit.scaleDown, alignment: Alignment.centerLeft, child: k.$2),
                  if (k.$3 != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(k.$3!, maxLines: 2, style: context.text.labelSmall?.copyWith(fontWeight: FontWeight.w500, letterSpacing: 0, fontSize: 11.5))),
                ]),
              ),
            ),
        ]);
      }),
      const SizedBox(height: 14),
      _ChartCard(
        title: 'Balance over the test',
        subtitle: 'How the balance would have moved, trade by trade.',
        child: m.equityCurve.length > 1
            ? LineSeries(values: m.equityCurve.map((p) => p.value).toList(), labels: m.equityCurve.map((p) => formatTime(p.t)).toList(), semanticLabel: 'Balance over the test', format: (v) => formatCurrency(v, currency))
            : Text('Not enough trades to draw a curve.', style: context.text.bodySmall),
      ),
      const SizedBox(height: 14),
      _ChartCard(
        title: 'Drawdown',
        subtitle: 'How far below its best point the balance fell.',
        child: m.drawdownCurve.length > 1
            ? LineSeries(values: m.drawdownCurve.map((p) => p.value).toList(), labels: m.drawdownCurve.map((p) => formatTime(p.t)).toList(), semanticLabel: 'Drawdown', format: (v) => '${v.toStringAsFixed(2)}%', color: context.c.negative, inverted: true, height: 140)
            : Text('No drawdown to show.', style: context.text.bodySmall),
      ),
      if (m.byRegime.isNotEmpty) ...[
        const SizedBox(height: 14),
        _ChartCard(title: 'By market regime at entry', subtitle: 'Trend, sideways or high-volatility conditions when each trade was taken (closed candles only).', child: GroupStatList(groups: m.byRegime, currency: currency)),
      ],
      if (m.bySymbol.length > 1) ...[
        const SizedBox(height: 14),
        _ChartCard(title: 'By market', child: GroupStatList(groups: m.bySymbol, currency: currency)),
      ],
      if (m.monthly.length > 1) ...[
        const SizedBox(height: 14),
        _ChartCard(
          title: 'Month by month',
          child: PnlBars(bars: [for (final x in m.monthly) BarPoint(x.month, x.netPnl, '${x.trades} trades')], format: (v) => formatSignedCurrency(v, currency), semanticLabel: 'Monthly net P/L'),
        ),
      ],
    ]);
  }

  static Widget _big(String text) => Text(text, style: tnum(const TextStyle(fontWeight: FontWeight.w900, fontSize: 20)));
}

class _ChartCard extends StatelessWidget {
  const _ChartCard({required this.title, this.subtitle, required this.child});
  final String title;
  final String? subtitle;
  final Widget child;

  @override
  Widget build(BuildContext context) => AppCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(title, style: context.text.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
          if (subtitle != null) Padding(padding: const EdgeInsets.only(top: 3), child: Text(subtitle!, style: context.text.bodySmall)),
          const SizedBox(height: 14),
          child,
        ]),
      );
}

/// Results per group (regime, market…): the same metrics for each slice.
class GroupStatList extends StatelessWidget {
  const GroupStatList({super.key, required this.groups, this.currency});
  final List<GroupStat> groups;
  final String? currency;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Column(children: [
      for (final g in groups)
        Container(
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: c.raised, borderRadius: BorderRadius.circular(12)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(child: Text(humanize(g.key), style: const TextStyle(fontWeight: FontWeight.w800))),
              Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                PnlText(g.netPnl, currency: currency, style: const TextStyle(fontWeight: FontWeight.w900)),
                Text('net after costs', style: context.text.labelSmall?.copyWith(letterSpacing: 0, fontSize: 11)),
              ]),
            ]),
            const SizedBox(height: 8),
            MiniStats([
              ('Trades', '${g.trades}'),
              ('Win rate', formatPct(g.winRate, digits: 0)),
              ('Profit factor', g.profitFactor == null ? emDash : formatNumber(g.profitFactor)),
              ('Per trade', g.expectancy == null ? emDash : formatSignedCurrency(g.expectancy, currency)),
              ('Avg R:R', g.avgRr == null ? emDash : formatNumber(g.avgRr)),
              ('Max drawdown', g.maxDrawdown == null ? emDash : formatCurrency(g.maxDrawdown, currency)),
              ('Losing streak', g.longestLosingStreak?.toString() ?? emDash),
            ]),
          ]),
        ),
    ]);
  }
}

/// The demo-forward-testing gate: every check with its reason. Never enables anything.
class ValidationCard extends StatelessWidget {
  const ValidationCard({super.key, required this.gate, this.compact = false});
  final ValidationGate gate;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final list = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final check in gate.checks)
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(
              padding: const EdgeInsets.only(top: 1, right: 6),
              child: Icon(check.passed ? Icons.check_rounded : Icons.close_rounded, size: 16, color: check.passed ? c.positive : c.negative, semanticLabel: check.passed ? 'passed' : 'failed'),
            ),
            Expanded(
              child: Text.rich(TextSpan(children: [TextSpan(text: check.name, style: const TextStyle(fontWeight: FontWeight.w700)), TextSpan(text: ': ${check.detail}')]),
                  style: TextStyle(fontSize: 12.5, color: check.passed ? c.muted : c.fg)),
            ),
          ]),
        ),
    ]);
    if (compact) {
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Pill(gate.qualifies ? 'Qualifies for demo forward testing' : 'Not validated for demo forward testing', tone: gate.qualifies ? PillTone.positive : PillTone.warning),
        const SizedBox(height: 6),
        list,
      ]);
    }
    return Notice(
      tone: gate.qualifies ? NoticeTone.success : NoticeTone.warning,
      title: gate.qualifies ? 'Qualifies for demo forward testing' : 'Does not qualify for demo forward testing',
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [list, if (gate.note.isNotEmpty) Text(gate.note, style: context.text.labelSmall?.copyWith(letterSpacing: 0, fontWeight: FontWeight.w500))]),
    );
  }
}

class _Trades extends ConsumerStatefulWidget {
  const _Trades({required this.id, required this.symbol, this.currency});
  final String id;
  final String symbol;
  final String? currency;

  @override
  ConsumerState<_Trades> createState() => _TradesState();
}

class _TradesState extends ConsumerState<_Trades> {
  static const page = 50;
  int _shown = page;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final res = ref.watch(backtestTradesProvider(widget.id));
    final trades = res.data;
    if (trades == null) return res.error != null ? ErrorView(error: res.error) : const ListSkeleton(rows: 3, height: 64);
    final contract = trades.any((t) => t.contractType != null);
    Widget result(BacktestTrade t) => switch (t.outcome) {
          'WON' => const Pill('Won', tone: PillTone.positive),
          'LOST' => const Pill('Lost', tone: PillTone.negative),
          'SOLD' => const Pill('Closed early'),
          _ => Text(humanize(t.exitReason), style: context.text.bodySmall),
        };
    String dir(BacktestTrade t) {
      final up = t.side == 'BUY';
      final type = t.contractType ?? '';
      if (type.startsWith('CALL') || type.startsWith('PUT')) return up ? 'Rise' : 'Fall';
      if (type.startsWith('MULT')) return up ? 'Up' : 'Down';
      return up ? 'Buy' : 'Sell';
    }

    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('Every simulated trade (${trades.length})', style: context.text.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
        const SizedBox(height: 3),
        Text('Each trade starts at the open of the candle after the signal — the test never sees the future.', style: context.text.bodySmall),
        const SizedBox(height: 12),
        if (trades.isEmpty) Text('The rules never matched in this period, so nothing traded.', style: context.text.bodySmall),
        for (final t in trades.take(_shown))
          Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: c.raised, borderRadius: BorderRadius.circular(12)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                Text(dir(t), style: TextStyle(fontWeight: FontWeight.w800, color: t.side == 'BUY' ? c.positive : c.negative)),
                const SizedBox(width: 8),
                result(t),
                const Spacer(),
                PnlText(t.netPnl, currency: widget.currency, style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 15)),
              ]),
              const SizedBox(height: 6),
              Text(
                '${formatTime(t.entryTime)} · ${contract ? 'Stake' : 'Size'} ${t.stake != null ? formatCurrency(t.stake, widget.currency) : '${toNumber(t.volume) ?? 0} lots'} · ${formatPrice(t.entryPrice, widget.symbol)} → ${formatPrice(t.exitPrice, widget.symbol)}',
                style: tnum(context.text.bodySmall?.copyWith(fontSize: 12.5)),
              ),
            ]),
          ),
        if (_shown < trades.length)
          OutlinedButton(onPressed: () => setState(() => _shown += page), child: Text('Show ${(trades.length - _shown).clamp(0, page)} more')),
      ]),
    );
  }
}
