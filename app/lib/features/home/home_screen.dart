import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../core/format.dart';
import '../../core/models/models.dart';
import '../../core/status.dart';
import '../../core/web_links.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/badges.dart';
import '../../ui/widgets/brand.dart';
import '../../ui/widgets/charts.dart';
import '../../ui/widgets/money.dart';
import '../../ui/widgets/now.dart';
import '../../ui/widgets/states.dart';
import '../history/trade_card.dart';
import '../shell/app_shell.dart';
import '../shell/trading_control.dart';
import 'account_switcher.dart';
import 'setup_checklist.dart';

/// HOME — "what is my bot doing with my money right now?": account and
/// balance, DEMO/LIVE, running or stopped (and why not trading), today's and
/// total P/L, open trades with time left, active strategies, one big Start/Stop.
class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  @override
  Widget build(BuildContext context) {
    final accounts = ref.watch(accountsProvider);
    final account = ref.watch(currentAccountProvider);
    final accountKey = account?.id ?? '';
    // Start/Stop/mode changes: refresh the overview's blockers too, so the page never disagrees with the button.
    ref.listen<String?>(statusProvider.select((r) => r.data == null ? null : '${r.data!.killSwitchEngaged}:${r.data!.tradingMode}:${r.data!.platformHalted}'), (prev, next) {
      if (prev != null && next != null && prev != next) ref.read(overviewProvider(accountKey).notifier).load();
    });
    final waitingForAccounts = accounts.loading;
    final overview = waitingForAccounts ? null : ref.watch(overviewProvider(accountKey));

    final List<Widget> children;
    final o = overview?.data;
    if (o == null) {
      final error = overview?.error ?? (accounts.data == null ? accounts.error : null);
      children = [error != null ? ErrorView(error: error, onRetry: () => ref.read(overviewProvider(accountKey).notifier).load()) : const _HomeSkeleton()];
    } else {
      final currency = o.account?.currency;
      final setup = o.setup;
      children = [
        if (o.account != null) _AccountHero(overview: o),
        if (setup != null && !setup.complete) ...[const SizedBox(height: 20), SetupChecklistCard(setup: setup)],
        if (o.account != null) ...[
          const SizedBox(height: 20),
          _Blockers(blockers: o.blockers),
          const SizedBox(height: 16),
          _Kpis(overview: o, currency: currency),
          const SizedBox(height: 16),
          _Positions(positions: o.positions, currency: currency),
          const SizedBox(height: 16),
          _ResultsChart(overview: o),
          const SizedBox(height: 16),
          _ActiveStrategies(list: o.activeStrategies),
        ] else if (setup == null)
          AppCard(
            child: EmptyState(
              icon: Icons.power_outlined,
              title: 'No account yet',
              message: 'Start with Paper (simulated money) or connect a Deriv demo account — on the 2kPilot website.',
              action: FilledButton.icon(onPressed: () => WebLinks.open(WebLinks.addBroker), icon: const Icon(Icons.open_in_new_rounded, size: 18), label: const Text('Add an account')),
            ),
          ),
      ];
    }
    return TabPage(
      title: 'Home',
      showLogo: true,
      onRefresh: () async {
        await ref.read(overviewProvider(accountKey).notifier).load();
      },
      children: children,
    );
  }
}

class _HomeSkeleton extends StatelessWidget {
  const _HomeSkeleton();

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Loading',
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const SizedBox(height: 8),
        Row(children: [const Skeleton(width: 64, height: 64, radius: 12), const SizedBox(width: 14), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: const [Skeleton(width: 120, height: 14), SizedBox(height: 10), Skeleton(width: 180, height: 14)]))]),
        const SizedBox(height: 20),
        const Skeleton(width: 220, height: 46),
        const SizedBox(height: 20),
        const Skeleton(height: 60, radius: 999),
        const SizedBox(height: 20),
        Row(children: const [Expanded(child: Skeleton(height: 110, radius: 16)), SizedBox(width: 12), Expanded(child: Skeleton(height: 110, radius: 16))]),
        const SizedBox(height: 12),
        const Skeleton(height: 220, radius: 16),
      ]),
    );
  }
}

class _AccountHero extends ConsumerWidget {
  const _AccountHero({required this.overview});
  final Overview overview;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final o = overview;
    final a = o.account!;
    final unknown = ref.watch(statusUnknownProvider);
    final status = ref.watch(statusProvider.select((r) => r.data)) ?? o.robot;
    final robot = unknown ? RobotStatus.unknown : deriveRobotStatus(status);
    final live = a.environment == AccountEnvironment.live;
    final balance = a.balance ?? o.figures?.balance;
    final kind = switch (a.environment) {
      AccountEnvironment.live => 'Live account',
      AccountEnvironment.demo => 'Demo account',
      AccountEnvironment.paper => 'Paper account',
      _ => 'Account',
    };
    final brokerStatus = o.brokerStatus ?? a.connectionStatus;
    final brokerDetail = o.brokerDetail ?? a.connectionDetail;
    final dot = robot.running ? c.positive : robot.tone == Tone.negative ? c.negative : robot.tone == Tone.neutral ? c.subtle : c.warning;
    final botTitle = robot.running ? 'Bot running' : robot.label == 'Trading stopped' ? 'Bot stopped' : robot.label;

    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const SizedBox(height: 4),
      Row(children: [
        Container(
          decoration: live ? BoxDecoration(borderRadius: BorderRadius.circular(14), border: Border.all(color: c.live, width: 2.5)) : null,
          padding: live ? const EdgeInsets.all(2) : EdgeInsets.zero,
          child: Artwork(seed: a.label, size: 60, radius: 12, values: o.balanceHistory.length > 1 ? o.balanceHistory.map((p) => p.balance).toList() : null),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [EnvBadge(a.environment), const SizedBox(width: 8), Text(kind, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14))]),
            const SizedBox(height: 4),
            AccountSwitcherButton(label: a.label),
          ]),
        ),
      ]),
      const SizedBox(height: 14),
      Semantics(label: 'Balance', child: MoneyText(balance, currency: a.currency, style: context.text.displayMedium?.copyWith(fontSize: 40))),
      const SizedBox(height: 8),
      Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 8, runSpacing: 4, children: [
        ConnectionDot(brokerStatus),
        Text(o.brokerName ?? a.broker, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 13)),
        Text('· ${brokerStatus.label}', style: context.text.bodySmall),
        if (brokerStatus != ConnectionStatus.connected && brokerDetail != null) Text('($brokerDetail)', style: context.text.bodySmall?.copyWith(color: c.subtle)),
        Text('· Balance updated ${formatRelative(a.syncedAt)}', style: context.text.bodySmall),
      ]),
      if (live) Padding(padding: const EdgeInsets.only(top: 8), child: Text('Real money — every loss is real.', style: TextStyle(color: c.live, fontWeight: FontWeight.w900, fontSize: 14))),
      const SizedBox(height: 18),
      const BigTradingButton(),
      const SizedBox(height: 12),
      Semantics(
        liveRegion: true,
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
          decoration: BoxDecoration(color: c.raised, borderRadius: BorderRadius.circular(14), border: Border.all(color: c.border)),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(padding: const EdgeInsets.only(top: 5), child: StatusDot(color: dot, size: 11, pulse: robot.running)),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(botTitle, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
                const SizedBox(height: 2),
                Text(robot.running ? 'It keeps trading on the server even when you close the app.' : robot.detail, style: context.text.bodySmall?.copyWith(fontSize: 13.5)),
              ]),
            ),
          ]),
        ),
      ),
    ]);
  }
}

class _Blockers extends StatelessWidget {
  const _Blockers({required this.blockers});
  final List<Blocker> blockers;

  @override
  Widget build(BuildContext context) {
    return Consumer(builder: (context, ref, _) {
      final c = context.c;
      final running = !(ref.watch(statusProvider.select((r) => r.data?.killSwitchEngaged)) ?? true);
      if (blockers.isEmpty) {
        return running
            ? const Notice(tone: NoticeTone.success, title: 'All set — the bot is watching the market', message: 'Your active strategies are checked every time a candle closes. Every trade passes your risk limits first.')
            : const SizedBox.shrink();
      }
      final allMarketClosed = blockers.every((b) => b.code == 'market_closed');
      return AppCard(
        border: Border.all(color: c.soft(c.warning, 0.35)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            IconBubble(Icons.error_outline_rounded, color: c.warning),
            const SizedBox(width: 10),
            Expanded(child: Semantics(header: true, child: Text('Nothing will trade right now', style: context.text.titleMedium?.copyWith(fontWeight: FontWeight.w800)))),
          ]),
          const SizedBox(height: 6),
          Text(allMarketClosed ? 'Here is why — the bot waits and starts again on its own when the market opens.' : 'Here is why — fix these and the bot can start trading.', style: context.text.bodySmall?.copyWith(fontSize: 13.5)),
          const SizedBox(height: 12),
          for (final b in blockers) Padding(padding: const EdgeInsets.only(bottom: 8), child: _BlockerRow(blocker: b)),
        ]),
      );
    });
  }
}

class _BlockerRow extends StatelessWidget {
  const _BlockerRow({required this.blocker});
  final Blocker blocker;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    Widget? action;
    switch (blocker.code) {
      case 'trading_stopped':
        action = FilledButton(
          style: FilledButton.styleFrom(backgroundColor: c.positive, foregroundColor: c.onPositive),
          onPressed: () => requestStart(context),
          child: const Text('Start trading'),
        );
      case 'no_active_strategy':
        action = OutlinedButton(onPressed: () => context.go('/strategies'), child: const Text('Activate a strategy'));
      case 'risk_profile_missing':
        action = OutlinedButton(onPressed: () => context.push('/settings/accounts'), child: const Text('Choose a risk profile'));
      case 'account_trading_disabled':
        action = OutlinedButton(onPressed: () => context.push('/settings/accounts'), child: const Text('Turn trading on'));
      case 'broker_disconnected':
        action = OutlinedButton(onPressed: () => context.push('/settings/brokers'), child: const Text('Check the connection'));
      case 'live_locked':
        action = OutlinedButton.icon(onPressed: () => WebLinks.open(WebLinks.realMoney), icon: const Icon(Icons.open_in_new_rounded, size: 16), label: const Text('Real-money settings'));
      case 'mode_mismatch':
        action = OutlinedButton(onPressed: () => context.push('/settings/accounts'), child: const Text('Accounts'));
    }
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: c.raised, borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Padding(padding: const EdgeInsets.only(top: 7), child: Container(width: 6, height: 6, decoration: BoxDecoration(color: c.warning, shape: BoxShape.circle))),
          const SizedBox(width: 10),
          Expanded(child: Text(blocker.message, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500))),
        ]),
        if (action != null) Padding(padding: const EdgeInsets.only(top: 10), child: action),
      ]),
    );
  }
}

class _Kpis extends StatelessWidget {
  const _Kpis({required this.overview, required this.currency});
  final Overview overview;
  final String? currency;

  @override
  Widget build(BuildContext context) {
    final f = overview.figures;
    final big = context.text.headlineMedium?.copyWith(fontWeight: FontWeight.w900);
    final open = f?.openPositions ?? 0;
    return Column(children: [
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(child: _Kpi(icon: Icons.event_rounded, label: "Today's P/L", hint: 'Finished trades since 00:00 UTC', child: PnlText(f?.todayPnl, currency: currency, style: big))),
        const SizedBox(width: 12),
        Expanded(child: _Kpi(icon: Icons.functions_rounded, label: 'Total realized P/L', hint: 'All finished trades on this account', child: PnlText(f?.totalPnl, currency: currency, style: big))),
      ]),
      const SizedBox(height: 12),
      _Kpi(
        icon: Icons.show_chart_rounded,
        label: 'Open trades',
        hint: open > 0 ? 'Current P/L — not final until they finish' : 'Nothing open right now',
        child: Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
          Text('$open', style: tnum(big)),
          if (open > 0) ...[const SizedBox(width: 10), PnlText(f?.openPnl, currency: currency, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15))],
        ]),
      ),
    ]);
  }
}

class _Kpi extends StatelessWidget {
  const _Kpi({required this.icon, required this.label, required this.child, this.hint});
  final IconData icon;
  final String label;
  final Widget child;
  final String? hint;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      padding: const EdgeInsets.all(14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [IconBubble(icon, size: 28), const SizedBox(width: 8), Expanded(child: Text(label, style: context.text.labelMedium?.copyWith(fontSize: 13.5)))]),
        const SizedBox(height: 10),
        FittedBox(fit: BoxFit.scaleDown, alignment: Alignment.centerLeft, child: child),
        if (hint != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text(hint!, style: context.text.labelSmall?.copyWith(fontWeight: FontWeight.w500, letterSpacing: 0, fontSize: 12))),
      ]),
    );
  }
}

class _CardHeader extends StatelessWidget {
  const _CardHeader({required this.title, this.subtitle, this.trailing});
  final String title;
  final String? subtitle;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Semantics(header: true, child: Text(title, style: context.text.titleLarge)),
          if (subtitle != null) Padding(padding: const EdgeInsets.only(top: 3), child: Text(subtitle!, style: context.text.bodySmall)),
        ]),
      ),
      ?trailing,
    ]);
  }
}

class _Positions extends StatelessWidget {
  const _Positions({required this.positions, required this.currency});
  final List<Trade> positions;
  final String? currency;

  @override
  Widget build(BuildContext context) {
    final expiring = positions.any((p) => p.expiresAt != null);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _CardHeader(
          title: 'Active trades',
          subtitle: 'Updated live. Tap a trade for details.',
          trailing: TextButton(onPressed: () => context.go('/history?tab=open'), child: const Text('All open')),
        ),
        const SizedBox(height: 8),
        if (positions.isEmpty)
          const EmptyState(icon: Icons.layers_outlined, compact: true, title: 'No open trades', message: 'When a strategy opens a trade, it appears here with its time left and current P/L.')
        else
          NowBuilder(
            enabled: expiring,
            builder: (context, now) => Column(children: [
              for (final p in positions)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: TradeCard(trade: p, open: true, flat: true, now: now, onTap: () => context.push('/trades/${p.id}')),
                ),
            ]),
          ),
      ]),
    );
  }
}

class _ResultsChart extends StatefulWidget {
  const _ResultsChart({required this.overview});
  final Overview overview;

  @override
  State<_ResultsChart> createState() => _ResultsChartState();
}

class _ResultsChartState extends State<_ResultsChart> {
  bool _balance = false;

  @override
  Widget build(BuildContext context) {
    final o = widget.overview;
    final currency = o.account?.currency;
    final hasTrades = o.dailyPnl.any((d) => d.trades > 0);
    final balances = o.balanceHistory.map((p) => p.balance).toList();
    final fmt = DateFormat.MMMd();
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const _CardHeader(title: 'Last 30 days', subtitle: 'Realized profit or loss per day (UTC), and the balance.'),
        const SizedBox(height: 12),
        SegmentedButton<bool>(
          showSelectedIcon: false,
          segments: const [ButtonSegment(value: false, label: Text('Daily P/L')), ButtonSegment(value: true, label: Text('Balance'))],
          selected: {_balance},
          onSelectionChanged: (s) => setState(() => _balance = s.first),
        ),
        const SizedBox(height: 16),
        if (!_balance)
          hasTrades
              ? PnlBars(
                  semanticLabel: 'Daily realized P/L, last 30 days',
                  format: (v) => formatSignedCurrency(v, currency),
                  bars: [
                    for (final d in o.dailyPnl)
                      BarPoint(DateTime.tryParse('${d.date}T00:00:00Z') == null ? d.date : fmt.format(DateTime.parse('${d.date}T00:00:00Z')), d.netPnl, '${d.trades} trade${d.trades == 1 ? '' : 's'}'),
                  ],
                )
              : const EmptyState(icon: Icons.candlestick_chart_outlined, compact: true, title: 'No finished trades in the last 30 days')
        else
          balances.length > 1
              ? LineSeries(
                  values: balances,
                  labels: o.balanceHistory.map((p) => formatTime(p.t)).toList(),
                  semanticLabel: 'Balance, last 30 days',
                  format: (v) => formatCurrency(v, currency),
                )
              : const EmptyState(icon: Icons.candlestick_chart_outlined, compact: true, title: 'Not enough balance history yet', message: 'The balance is recorded as the account syncs.'),
      ]),
    );
  }
}

class _ActiveStrategies extends StatelessWidget {
  const _ActiveStrategies({required this.list});
  final List<ActiveStrategy> list;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const _CardHeader(title: 'Active strategies', subtitle: 'What the bot is allowed to trade on this account.'),
        const SizedBox(height: 8),
        if (list.isEmpty)
          EmptyState(
            icon: Icons.layers_outlined,
            compact: true,
            title: 'No strategy active',
            message: 'Activate a strategy on this account so the bot has something to trade.',
            action: FilledButton(onPressed: () => context.go('/strategies'), child: const Text('Choose a strategy')),
          )
        else
          for (final s in list)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Artwork(seed: s.strategy ?? 'Strategy', size: 48, radius: 8),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Row(children: [
                      Expanded(child: Text(s.strategy ?? 'Strategy', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15))),
                      const Pill('Active', tone: PillTone.positive, dot: true),
                    ]),
                    const SizedBox(height: 3),
                    Text.rich(TextSpan(children: [TextSpan(text: s.symbol, style: TextStyle(color: c.fg, fontWeight: FontWeight.w700)), TextSpan(text: ' · ${s.contractSummary}')]), style: context.text.bodySmall),
                    const SizedBox(height: 3),
                    Text(
                      '${s.lastBarEvaluated != null ? 'Last candle checked: ${formatTime(s.lastBarEvaluated)}' : 'Waiting for the next candle to close'}${s.lastSignalAt != null ? ' · last signal ${formatRelative(s.lastSignalAt)}' : ''}',
                      style: context.text.labelSmall?.copyWith(fontWeight: FontWeight.w500, letterSpacing: 0, fontSize: 12),
                    ),
                  ]),
                ),
              ]),
            ),
      ]),
    );
  }
}
