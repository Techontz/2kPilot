import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_client.dart';
import '../../core/contracts.dart';
import '../../core/format.dart';
import '../../core/insights.dart';
import '../../core/models/models.dart';
import '../../core/web_links.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/badges.dart';
import '../../ui/widgets/brand.dart';
import '../../ui/widgets/dialogs.dart';
import '../../ui/widgets/money.dart';
import '../../ui/widgets/states.dart';
import 'activate_sheet.dart';
import 'backtest_sheet.dart';
import 'evaluations_sheet.dart';
import 'strategy_insights.dart';

class MyStrategies extends ConsumerWidget {
  const MyStrategies({super.key, required this.onBrowseTemplates, required this.onAdd});
  final VoidCallback onBrowseTemplates;
  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final res = ref.watch(strategiesProvider);
    final data = res.data;
    final List<Widget> children;
    if (data == null) {
      children = [res.error != null ? ErrorView(error: res.error, onRetry: () => ref.read(strategiesProvider.notifier).load()) : const ListSkeleton(rows: 2, height: 260)];
    } else {
      final mine = data.where(isMine).toList();
      final templates = data.where((s) => s.builtIn && !isMine(s)).take(4).toList();
      children = mine.isEmpty
          ? [
              AppCard(
                child: EmptyState(
                  icon: Icons.tune_rounded,
                  title: "You don't have a strategy yet",
                  message: 'The easiest start is a ready-made template: copy it, test it on past prices, then activate it on your demo account.',
                  action: Column(children: [
                    FilledButton(onPressed: onBrowseTemplates, child: const Text('Browse templates')),
                    const SizedBox(height: 8),
                    TextButton(onPressed: onAdd, child: const Text('Other ways to add one')),
                  ]),
                ),
              ),
            ]
          : [
              _ShelfHeader(title: 'Your strategies', meta: '${mine.length} ${mine.length == 1 ? 'strategy' : 'strategies'}'),
              for (final s in mine) Padding(padding: const EdgeInsets.only(bottom: 14), child: StrategyCard(strategy: s)),
              if (templates.isNotEmpty) ...[
                const SizedBox(height: 10),
                _ShelfHeader(title: 'Start from a template', action: TextButton(onPressed: onBrowseTemplates, child: const Text('Show all'))),
                GridView.count(
                  crossAxisCount: 2,
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  mainAxisSpacing: 12,
                  crossAxisSpacing: 12,
                  childAspectRatio: 0.92,
                  children: [
                    for (final t in templates)
                      AppCard(
                        padding: const EdgeInsets.all(10),
                        onTap: onBrowseTemplates,
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          AspectRatio(aspectRatio: 16 / 9, child: Artwork(seed: '${t.name} ${t.description}')),
                          const SizedBox(height: 10),
                          Text(t.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w800)),
                          const SizedBox(height: 2),
                          Text(t.description, maxLines: 2, overflow: TextOverflow.ellipsis, style: context.text.bodySmall?.copyWith(fontSize: 12)),
                        ]),
                      ),
                  ],
                ),
              ],
            ];
    }
    return ListView(padding: const EdgeInsets.fromLTRB(16, 12, 16, 32), physics: const AlwaysScrollableScrollPhysics(), children: children);
  }
}

class _ShelfHeader extends StatelessWidget {
  const _ShelfHeader({required this.title, this.meta, this.action});
  final String title;
  final String? meta;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 10, left: 2),
        child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Semantics(header: true, child: Text(title, style: context.text.headlineSmall)),
          if (meta != null) Padding(padding: const EdgeInsets.only(left: 8, bottom: 2), child: Text(meta!, style: context.text.labelMedium?.copyWith(color: context.c.subtle))),
          const Spacer(),
          ?action,
        ]),
      );
}

class StrategyCard extends ConsumerStatefulWidget {
  const StrategyCard({super.key, required this.strategy});
  final Strategy strategy;

  @override
  ConsumerState<StrategyCard> createState() => _StrategyCardState();
}

class _StrategyCardState extends ConsumerState<StrategyCard> {
  bool _expanded = false;
  bool _insights = false;
  String? _busyAccount;

  Strategy get s => widget.strategy;

  Future<void> _deactivate(String accountId) async {
    setState(() => _busyAccount = accountId);
    try {
      await ref.read(apiClientProvider).post('/strategies/${s.id}/deactivate', body: {'account_id': accountId});
      ref.read(strategiesProvider.notifier).load();
      if (mounted) showSnack(context, '${s.name} deactivated', detail: 'It no longer opens trades on that account. Open trades finish normally.');
    } catch (e) {
      if (mounted) showApiError(context, e, title: 'Not deactivated');
    } finally {
      if (mounted) setState(() => _busyAccount = null);
    }
  }

  Future<void> _delete() async {
    await confirmAction(
      context,
      title: 'Delete ${s.name}?',
      body: const ['If it has trades or tests, it is archived instead so your history stays complete. Deactivate it everywhere first.'],
      confirmLabel: 'Delete',
      destructive: true,
      onConfirm: () async {
        try {
          final res = asJson(await ref.read(apiClientProvider).delete('/strategies/${s.id}'));
          ref.read(strategiesProvider.notifier).load();
          if (mounted) {
            final archived = res.str('outcome') == 'archived';
            showSnack(context, archived ? '${s.name} archived' : '${s.name} deleted', detail: archived ? 'Its trades and tests stay in your history.' : null);
          }
          return null;
        } on ApiException catch (e) {
          return e.message;
        }
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final active = s.assignments.where((a) => a.enabled).toList();
    final ruleBased = isRuleBased(s);
    final user = ref.watch(userProvider);
    final editable = ruleBased && (!s.builtIn || (user?.isAdmin ?? false)) && s.editable != false;
    final accounts = ref.watch(accountsProvider.select((r) => r.data)) ?? const <Account>[];
    final currencies = accounts.map((a) => a.currency).toSet();
    final currency = currencies.length == 1 ? currencies.first : null;
    final text = rulesText(s);
    final rules = ruleLines(text);
    final demo = s.demo;
    final bt = s.backtest;
    final shownRules = _expanded ? rules : rules.take(2).toList();

    return AppCard(
      padding: EdgeInsets.zero,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 6, 0),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Artwork(seed: '${s.name} ${s.description}', size: 60, radius: 10),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(s.name, style: context.text.titleLarge),
                const SizedBox(height: 6),
                Wrap(spacing: 6, runSpacing: 6, children: [
                  Pill(sourceLabel(s.source), tone: s.source == 'template' || s.source == 'code' ? PillTone.primary : PillTone.neutral),
                  active.isNotEmpty ? Pill('Active on ${active.length}', tone: PillTone.positive, dot: true) : const Pill('Not active'),
                  if (s.entriesDisabled != null) const Pill('Stopped by admin', tone: PillTone.negative, dot: true),
                ]),
              ]),
            ),
            PopupMenuButton<String>(
              tooltip: 'More actions for ${s.name}',
              icon: Icon(Icons.more_horiz_rounded, color: c.muted),
              onSelected: (v) {
                switch (v) {
                  case 'edit':
                    WebLinks.open(WebLinks.editStrategy(s.id));
                  case 'export':
                    WebLinks.open(WebLinks.strategies);
                  case 'delete':
                    _delete();
                }
              },
              itemBuilder: (_) => [
                if (editable) const PopupMenuItem(value: 'edit', child: ListTile(leading: Icon(Icons.edit_outlined), title: Text('Edit rules on the website'))),
                if (ruleBased) const PopupMenuItem(value: 'export', child: ListTile(leading: Icon(Icons.download_outlined), title: Text('Export on the website'))),
                if (!s.builtIn) PopupMenuItem(value: 'delete', child: ListTile(leading: Icon(Icons.delete_outline_rounded, color: c.negative), title: Text('Delete…', style: TextStyle(color: c.negative)))),
              ],
            ),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (s.description.isNotEmpty && s.description != text) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(s.description, style: context.text.bodyMedium?.copyWith(color: c.muted))),
            for (final r in shownRules)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Padding(padding: const EdgeInsets.only(top: 8, right: 10), child: Container(width: 4, height: 4, decoration: BoxDecoration(color: c.subtle, shape: BoxShape.circle))),
                  Expanded(child: Text(r, maxLines: _expanded ? null : 2, overflow: _expanded ? null : TextOverflow.ellipsis, style: const TextStyle(fontSize: 14.5, height: 1.45))),
                ]),
              ),
            if (rules.length > 2 || text.length > 180)
              TextButton(
                style: TextButton.styleFrom(padding: EdgeInsets.zero, minimumSize: const Size(48, 40), tapTargetSize: MaterialTapTargetSize.shrinkWrap),
                onPressed: () => setState(() => _expanded = !_expanded),
                child: Text(_expanded ? 'Show less' : 'Show all rules'),
              ),
          ]),
        ),
        if (!ruleBased)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
            child: _insights
                ? Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    StrategyInsights(strategy: s),
                    TextButton(onPressed: () => setState(() => _insights = false), child: const Text('Hide strategy insights')),
                  ])
                : OutlinedButton.icon(onPressed: () => setState(() => _insights = true), icon: const Icon(Icons.insights_rounded, size: 18), label: const Text('Strategy insights')),
          ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: Column(children: [
            _Fact(
              title: 'Demo results (your Paper/demo trades)',
              child: demo != null && demo.trades > 0
                  ? Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Wrap(crossAxisAlignment: WrapCrossAlignment.center, children: [
                        PnlText(demo.netPnl, currency: currency, style: const TextStyle(fontWeight: FontWeight.w900)),
                        Text(' · ${demo.trades} trades · ${formatPct(demo.winRate, digits: 0)} wins', style: tnum(null)),
                      ]),
                      const SizedBox(height: 2),
                      Wrap(children: [
                        Text('Last 30 days ', style: context.text.bodySmall),
                        PnlText(demo.netPnl30d, currency: currency, style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700)),
                        Text(' · last trade ${formatRelative(demo.lastTradeAt)}', style: context.text.bodySmall),
                      ]),
                    ])
                  : Text('Not traded on demo yet', style: TextStyle(color: c.muted)),
            ),
            const SizedBox(height: 8),
            _Fact(
              title: 'Latest test on history',
              onTap: bt == null ? null : () => context.push('/strategies/backtests/${bt.id}'),
              child: bt != null
                  ? Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Wrap(crossAxisAlignment: WrapCrossAlignment.center, children: [
                        PnlText(bt.netPnl, currency: 'USD', style: const TextStyle(fontWeight: FontWeight.w900)),
                        Text(' · ${bt.trades ?? 0} trades · ${formatPct(bt.winRate, digits: 0)} wins', style: tnum(null)),
                      ]),
                      const SizedBox(height: 2),
                      Text('${bt.symbol} ${bt.timeframe} · max drawdown ${formatPct(bt.maxDrawdownPct, digits: 1)} · ${formatRelative(bt.runAt)}', style: context.text.bodySmall),
                    ])
                  : Text('Not tested yet', style: TextStyle(color: c.muted)),
            ),
          ]),
        ),
        if (s.assignments.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: Column(children: [
              for (final a in s.assignments)
                Container(
                  margin: const EdgeInsets.only(bottom: 8),
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(borderRadius: BorderRadius.circular(12), border: Border.all(color: c.border)),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
                      if (a.account != null) EnvBadge(a.account!.environment),
                      Text(a.symbol, style: const TextStyle(fontWeight: FontWeight.w800)),
                      Text('on ${a.account?.label ?? 'account'}', style: context.text.bodySmall),
                      a.enabled ? const Pill('Active', tone: PillTone.positive, dot: true) : const Pill('Paused'),
                    ]),
                    const SizedBox(height: 4),
                    Text('${contractSummary(a.contract)}${a.lastBarEvaluated != null ? ' · checked ${formatRelative(a.lastBarEvaluated)}' : ''}', style: context.text.labelSmall?.copyWith(fontWeight: FontWeight.w500, letterSpacing: 0, fontSize: 12)),
                    const SizedBox(height: 8),
                    Row(children: [
                      Expanded(child: OutlinedButton(onPressed: () => showEvaluations(context, a), child: const Text('Why no trade?'))),
                      if (a.enabled && a.account != null) ...[
                        const SizedBox(width: 8),
                        Expanded(
                          child: OutlinedButton(
                            onPressed: _busyAccount != null ? null : () => _deactivate(a.account!.id),
                            child: Text(_busyAccount == a.account!.id ? 'Working…' : 'Deactivate'),
                          ),
                        ),
                      ],
                    ]),
                  ]),
                ),
            ]),
          ),
        Container(
          margin: const EdgeInsets.only(top: 8),
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
          decoration: BoxDecoration(border: Border(top: BorderSide(color: c.border))),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            FilledButton.icon(
              onPressed: () => showActivateSheet(context, s),
              icon: const Icon(Icons.play_arrow_rounded),
              label: Text(active.isNotEmpty ? 'Activate on another market' : 'Activate'),
            ),
            const SizedBox(height: 8),
            Row(children: [
              Expanded(child: OutlinedButton.icon(onPressed: () => showBacktestSheet(context, s), icon: const Icon(Icons.science_outlined, size: 19), label: const Text('Test on history'))),
              if (editable) ...[
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton.icon(onPressed: () => WebLinks.open(WebLinks.editStrategy(s.id)), icon: const Icon(Icons.open_in_new_rounded, size: 17), label: const Text('Edit on web')),
                ),
              ],
            ]),
          ]),
        ),
      ]),
    );
  }
}

class _Fact extends StatelessWidget {
  const _Fact({required this.title, required this.child, this.onTap});
  final String title;
  final Widget child;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Material(
      color: c.raised,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, style: context.text.labelMedium),
                const SizedBox(height: 4),
                DefaultTextStyle.merge(style: const TextStyle(fontSize: 14), child: child),
              ]),
            ),
            if (onTap != null) Icon(Icons.chevron_right_rounded, color: c.subtle),
          ]),
        ),
      ),
    );
  }
}
