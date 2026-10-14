import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/api/api_client.dart';
import '../../core/format.dart';
import '../../core/history_filters.dart';
import '../../core/models/models.dart';
import '../../core/web_links.dart';
import '../../state/providers.dart';
import '../../state/resource.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/badges.dart';
import '../../ui/widgets/dialogs.dart';
import '../../ui/widgets/money.dart';
import '../../ui/widgets/now.dart';
import '../../ui/widgets/states.dart';
import '../shell/app_shell.dart';
import 'trade_card.dart';

/// GET /api/history for one encoded query string.
final historyPageProvider = StateNotifierProvider.autoDispose.family<ResourceController<Paginated<Trade>>, Resource<Paginated<Trade>>, String>((ref, query) =>
    resourceFor(ref, (api) async => Paginated.fromJson(await api.get('/history', query: Uri.splitQueryString(query)), Trade.fromJson), every: const Duration(seconds: 15)));

final journalProvider = StateNotifierProvider.autoDispose.family<ResourceController<List<JournalEvent>>, Resource<List<JournalEvent>>, String>((ref, accountId) =>
    resourceFor(ref, (api) async => Paginated.fromJson(await api.get('/journal', query: {'account_id': accountId, 'per_page': 100}), JournalEvent.fromJson).data,
        every: const Duration(seconds: 10)));

final ordersProvider = StateNotifierProvider.autoDispose.family<ResourceController<List<Order>>, Resource<List<Order>>, String>((ref, accountId) =>
    resourceFor(ref, (api) async => Paginated.fromJson(await api.get('/orders', query: {'account_id': accountId, 'per_page': 100}), Order.fromJson).data,
        every: const Duration(seconds: 10)));

/// HISTORY — what is open now, what has finished, and every decision the bot made.
class HistoryScreen extends ConsumerStatefulWidget {
  const HistoryScreen({super.key, this.initialTab});
  final String? initialTab;

  @override
  ConsumerState<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends ConsumerState<HistoryScreen> with SingleTickerProviderStateMixin {
  static const tabs = ['open', 'closed', 'activity'];
  late final TabController _tabs = TabController(length: 3, vsync: this, initialIndex: _indexOf(widget.initialTab));
  HistoryFilters _filters = HistoryFilters(from: presetRange(RangePreset.d30).from, to: presetRange(RangePreset.d30).to);

  /// Until the user picks an account filter, follow the account selected on Home.
  bool _accountChosen = false;

  static int _indexOf(String? tab) => tab == null || !tabs.contains(tab) ? 0 : tabs.indexOf(tab);

  @override
  void didUpdateWidget(covariant HistoryScreen old) {
    super.didUpdateWidget(old);
    if (widget.initialTab != old.initialTab && widget.initialTab != null) _tabs.index = _indexOf(widget.initialTab);
  }

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  HistoryFilters get filters => _accountChosen ? _filters : _filters.copyWith(accountId: ref.watch(currentAccountProvider)?.id ?? '');

  void _setFilters(HistoryFilters next) => setState(() {
        _accountChosen = _accountChosen || next.accountId != filters.accountId;
        _filters = next;
      });

  @override
  Widget build(BuildContext context) {
    final f = filters;
    return TabPage(
      title: 'History',
      bottom: PreferredSize(
        preferredSize: const Size.fromHeight(52),
        child: Align(
          alignment: Alignment.centerLeft,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
            child: SizedBox(
              height: 40,
              child: TabBar(controller: _tabs, isScrollable: true, tabs: const [Tab(text: 'Open'), Tab(text: 'Closed'), Tab(text: 'Activity')]),
            ),
          ),
        ),
      ),
      body: TabBarView(controller: _tabs, children: [
        _OpenTab(filters: f, setFilters: _setFilters),
        _ClosedTab(filters: f, setFilters: _setFilters),
        _ActivityTab(filters: f, setFilters: _setFilters),
      ]),
    );
  }
}

class _AccountFilter extends ConsumerWidget {
  const _AccountFilter({required this.filters, required this.setFilters});
  final HistoryFilters filters;
  final ValueChanged<HistoryFilters> setFilters;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final accounts = ref.watch(accountsProvider.select((r) => r.data)) ?? const <Account>[];
    final current = accounts.where((a) => a.id == filters.accountId).firstOrNull;
    return PickerField(
      label: 'Account',
      value: current == null ? 'All accounts' : '${current.label} · ${current.environment.wire}',
      onTap: () async {
        final picked = await pickOption<String>(context,
            title: 'Account', selected: filters.accountId, options: [('', 'All accounts', null), for (final a in accounts) (a.id, a.label, '${a.environment.wire} · ${a.broker}')]);
        if (picked != null) setFilters(filters.copyWith(accountId: picked));
      },
    );
  }
}

Widget _pnlTotal(BuildContext context, List<Trade> trades, {bool open = false}) {
  final currencies = trades.map((t) => t.account?.currency ?? '').toSet();
  if (currencies.length != 1) return Text('(mixed currencies)', style: TextStyle(color: context.c.subtle));
  final total = trades.fold<double>(0, (s, t) => s + (toNumber(open ? t.unrealizedPnl : t.netPnl) ?? 0));
  return PnlText(total, currency: currencies.first, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 14));
}

// ── Open ────────────────────────────────────────────────────────────────

class _OpenTab extends ConsumerWidget {
  const _OpenTab({required this.filters, required this.setFilters});
  final HistoryFilters filters;
  final ValueChanged<HistoryFilters> setFilters;

  Future<void> _closeAll(BuildContext context, WidgetRef ref) async {
    await confirmAction(
      context,
      title: 'Close every open trade?',
      body: const [
        'This stops your trading first, then asks the broker to close every open trade on your accounts at the current price.',
        "Rise/Fall contracts can't be closed early — they finish at expiry on their own.",
      ],
      confirmLabel: 'Stop and close all',
      destructive: true,
      onConfirm: () async {
        try {
          final res = await ref.read(tradingActionsProvider).closeAll('Close all from History (mobile app)');
          if (res.status != null) ref.read(statusProvider.notifier).set(res.status!);
          ref.read(positionsProvider(filters.accountId).notifier).load();
          if (context.mounted) {
            showSnack(context, 'Trading stopped and open trades closed',
                detail: '${res.closed} closed${res.failed > 0 ? ', ${res.failed} could not be closed (see notifications)' : ''}.');
          }
          return null;
        } on ApiException catch (e) {
          return e.isWebOnly ? 'Do this on the 2kPilot website. ${e.message}' : e.message;
        }
      },
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final res = ref.watch(positionsProvider(filters.accountId));
    final list = res.data;
    final c = context.c;
    return RefreshIndicator(
      onRefresh: () async => ref.read(positionsProvider(filters.accountId).notifier).load(),
      child: ListView(padding: const EdgeInsets.fromLTRB(16, 12, 16, 32), physics: const AlwaysScrollableScrollPhysics(), children: [
        _AccountFilter(filters: filters, setFilters: setFilters),
        const SizedBox(height: 12),
        if (list != null && list.isNotEmpty) ...[
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(foregroundColor: c.negative, side: BorderSide(color: c.soft(c.negative, 0.5))),
            onPressed: () => _closeAll(context, ref),
            icon: const Icon(Icons.cancel_outlined),
            label: const Text('Close all open trades…'),
          ),
          const SizedBox(height: 12),
        ],
        if (res.error != null && list == null)
          ErrorView(error: res.error, onRetry: () => ref.read(positionsProvider(filters.accountId).notifier).load())
        else if (list == null)
          const ListSkeleton(rows: 3, height: 110)
        else if (list.isEmpty)
          AppCard(
            child: EmptyState(
              icon: Icons.inbox_outlined,
              title: 'No open trades',
              message: 'When an active strategy opens a trade it shows up here with its time left and current profit or loss.',
              action: OutlinedButton(onPressed: () => context.go('/home'), child: const Text('Back to Home')),
            ),
          )
        else ...[
          Semantics(
            liveRegion: true,
            child: Wrap(crossAxisAlignment: WrapCrossAlignment.center, children: [
              Text('${list.length} open', style: const TextStyle(fontWeight: FontWeight.w800)),
              Text(' · current P/L ', style: context.text.bodySmall),
              _pnlTotal(context, list, open: true),
            ]),
          ),
          const SizedBox(height: 10),
          NowBuilder(
            enabled: list.any((t) => t.expiresAt != null),
            builder: (context, now) => Column(children: [
              for (final t in list)
                Padding(padding: const EdgeInsets.only(bottom: 10), child: TradeCard(trade: t, open: true, now: now, showAccount: filters.accountId.isEmpty, onTap: () => context.push('/trades/${t.id}'))),
            ]),
          ),
        ],
      ]),
    );
  }
}

// ── Closed ──────────────────────────────────────────────────────────────

class _ClosedTab extends ConsumerStatefulWidget {
  const _ClosedTab({required this.filters, required this.setFilters});
  final HistoryFilters filters;
  final ValueChanged<HistoryFilters> setFilters;

  @override
  ConsumerState<_ClosedTab> createState() => _ClosedTabState();
}

class _ClosedTabState extends ConsumerState<_ClosedTab> {
  int _page = 1;
  bool _custom = false;
  bool _exporting = false;

  void _update(HistoryFilters next) {
    setState(() => _page = 1);
    widget.setFilters(next);
  }

  void _choosePreset(RangePreset p) {
    setState(() => _custom = p == RangePreset.custom);
    if (p != RangePreset.custom) {
      final r = presetRange(p);
      _update(widget.filters.copyWith(from: r.from, to: r.to));
    } else {
      _openFilters();
    }
  }

  Future<void> _export() async {
    final choice = await showModalBottomSheet<String>(useRootNavigator: true, 
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Padding(padding: const EdgeInsets.fromLTRB(20, 0, 20, 4), child: Text('Export finished trades', style: ctx.text.titleLarge)),
          Padding(padding: const EdgeInsets.fromLTRB(20, 0, 20, 8), child: Text('A CSV file with the current filters.', style: ctx.text.bodySmall)),
          ListTile(minTileHeight: 60, leading: const Icon(Icons.ios_share_rounded), title: const Text('Share the CSV file'), subtitle: const Text('Save to Files, email it, open in a spreadsheet'), onTap: () => Navigator.pop(ctx, 'share')),
          ListTile(minTileHeight: 60, leading: const Icon(Icons.open_in_new_rounded), title: const Text('Export on the website'), onTap: () => Navigator.pop(ctx, 'web')),
          const SizedBox(height: 8),
        ]),
      ),
    );
    if (!mounted || choice == null) return;
    if (choice == 'web') {
      WebLinks.open(WebLinks.historyExport);
      return;
    }
    final box = context.findRenderObject() as RenderBox?;
    setState(() => _exporting = true);
    try {
      final bytes = await ref.read(apiClientProvider).getBytes(exportPath(widget.filters));
      final name = '2kpilot-history-${DateFormat('yyyyMMdd').format(DateTime.now())}.csv';
      await SharePlus.instance.share(ShareParams(
        files: [XFile.fromData(bytes, mimeType: 'text/csv', name: name)],
        fileNameOverrides: [name],
        subject: '2kPilot trade history',
        sharePositionOrigin: box == null ? null : box.localToGlobal(Offset.zero) & box.size,
      ));
    } catch (e) {
      if (mounted) showApiError(context, e, title: 'Export failed');
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  Future<void> _openFilters() async {
    await showModalBottomSheet<void>(useRootNavigator: true, 
      context: context,
      isScrollControlled: true,
      builder: (ctx) => _FilterSheet(initial: widget.filters, custom: _custom, onChanged: (f) => _update(f), onClear: () {
        setState(() => _custom = false);
        _update(HistoryFilters.empty);
      }),
    );
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final f = widget.filters;
    final problem = rangeProblem(f);
    final query = Uri(queryParameters: historyQuery(f, {'page': _page, 'per_page': 50}).map((k, v) => MapEntry(k, '$v'))).query;
    final res = problem != null ? null : ref.watch(historyPageProvider(query));
    final data = res?.data;
    final preset = _custom ? RangePreset.custom : detectPreset(f);
    final extra = f.extraCount + (_custom ? 1 : 0);
    return RefreshIndicator(
      onRefresh: () async {
        if (problem == null) await ref.read(historyPageProvider(query).notifier).load();
      },
      child: ListView(padding: const EdgeInsets.fromLTRB(0, 12, 0, 32), physics: const AlwaysScrollableScrollPhysics(), children: [
        SizedBox(
          height: 44,
          child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 16), children: [
            for (final p in RangePreset.values)
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: ChoiceChip(
                  label: Text(p.label),
                  selected: preset == p,
                  showCheckmark: false,
                  onSelected: (_) => _choosePreset(p),
                  labelStyle: TextStyle(fontFamily: fontFamily, fontWeight: FontWeight.w700, color: preset == p ? (c.isDark ? Colors.black : Colors.white) : c.fg),
                  selectedColor: c.fg,
                  backgroundColor: c.hover,
                  side: BorderSide.none,
                  shape: const StadiumBorder(),
                  materialTapTargetSize: MaterialTapTargetSize.padded,
                ),
              ),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
          child: Row(children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _openFilters,
                icon: const Icon(Icons.tune_rounded, size: 20),
                label: Text(extra > 0 ? 'Filters · $extra' : 'Filters', semanticsLabel: extra > 0 ? 'Filters, $extra active' : 'Filters'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: problem != null || _exporting ? null : _export,
                icon: _exporting ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.download_rounded, size: 20),
                label: const Text('Export CSV'),
              ),
            ),
          ]),
        ),
        if (problem != null) Padding(padding: const EdgeInsets.fromLTRB(16, 8, 16, 0), child: Text(problem, style: TextStyle(color: c.negative, fontWeight: FontWeight.w600))),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 10),
          child: data == null
              ? const SizedBox(height: 18)
              : Semantics(
                  liveRegion: true,
                  child: Wrap(crossAxisAlignment: WrapCrossAlignment.center, children: [
                    Text('${NumberFormat.decimalPattern().format(data.total)} finished trade${data.total == 1 ? '' : 's'}', style: const TextStyle(fontWeight: FontWeight.w800)),
                    if (data.data.isNotEmpty) ...[Text(' · this page ', style: context.text.bodySmall), _pnlTotal(context, data.data)],
                  ]),
                ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: res == null
              ? const SizedBox.shrink()
              : res.error != null && data == null
                  ? ErrorView(error: res.error, onRetry: () => ref.read(historyPageProvider(query).notifier).load())
                  : data == null
                      ? const ListSkeleton(rows: 5, height: 104)
                      : data.data.isEmpty
                          ? AppCard(
                              child: EmptyState(
                                icon: Icons.history_rounded,
                                title: 'No finished trades match',
                                message: 'Try a longer period or another account. Trades appear here once they finish.',
                                action: OutlinedButton(
                                  onPressed: () {
                                    setState(() => _custom = false);
                                    _update(HistoryFilters.empty);
                                  },
                                  child: const Text('Clear filters'),
                                ),
                              ),
                            )
                          : Column(children: [
                              for (final t in data.data)
                                Padding(padding: const EdgeInsets.only(bottom: 10), child: TradeCard(trade: t, showAccount: f.accountId.isEmpty, onTap: () => context.push('/trades/${t.id}'))),
                              if (data.lastPage > 1)
                                Row(children: [
                                  OutlinedButton(onPressed: _page <= 1 ? null : () => setState(() => _page--), child: const Text('Previous')),
                                  Expanded(child: Text('Page ${data.currentPage} of ${data.lastPage}', textAlign: TextAlign.center, style: tnum(context.text.bodySmall))),
                                  OutlinedButton(onPressed: _page >= data.lastPage ? null : () => setState(() => _page++), child: const Text('Next')),
                                ]),
                            ]),
        ),
      ]),
    );
  }
}

class _FilterSheet extends ConsumerStatefulWidget {
  const _FilterSheet({required this.initial, required this.custom, required this.onChanged, required this.onClear});
  final HistoryFilters initial;
  final bool custom;
  final ValueChanged<HistoryFilters> onChanged;
  final VoidCallback onClear;

  @override
  ConsumerState<_FilterSheet> createState() => _FilterSheetState();
}

class _FilterSheetState extends ConsumerState<_FilterSheet> {
  late HistoryFilters _f = widget.initial;

  void _set(HistoryFilters next) {
    setState(() => _f = next);
    widget.onChanged(next); // changes apply straight away
  }

  Future<void> _pickDate(bool from) async {
    final current = DateTime.tryParse(from ? _f.from : _f.to);
    final picked = await showDatePicker(context: context, initialDate: current ?? DateTime.now(), firstDate: DateTime(2020), lastDate: DateTime.now().add(const Duration(days: 1)));
    if (picked == null) return;
    final ymd = DateFormat('yyyy-MM-dd').format(picked);
    _set(from ? _f.copyWith(from: ymd) : _f.copyWith(to: ymd));
  }

  @override
  Widget build(BuildContext context) {
    final strategies = ref.watch(strategiesProvider.select((r) => r.data)) ?? const <Strategy>[];
    final options = strategies.where((s) => !s.builtIn || s.assignments.isNotEmpty).toList();
    final chosen = options.where((s) => s.id == _f.strategyId).firstOrNull;
    final problem = rangeProblem(_f);
    final preset = detectPreset(_f);
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(20, 0, 20, 16 + MediaQuery.viewInsetsOf(context).bottom),
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('Filter finished trades', style: context.text.titleLarge),
            Text('Changes apply straight away.', style: context.text.bodySmall),
            const SizedBox(height: 16),
            PickerField(
              label: 'Period',
              value: (widget.custom ? RangePreset.custom : preset).label,
              onTap: () async {
                final p = await pickOption<RangePreset>(context, title: 'Period', selected: preset, options: [for (final p in RangePreset.values) (p, p.label, null)]);
                if (p != null && p != RangePreset.custom) {
                  final r = presetRange(p);
                  _set(_f.copyWith(from: r.from, to: r.to));
                }
              },
            ),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: PickerField(label: 'From', value: _f.from.isEmpty ? 'Any' : formatDate(_f.from), onTap: () => _pickDate(true), error: problem == null ? null : ' ')),
              const SizedBox(width: 10),
              Expanded(child: PickerField(label: 'To', value: _f.to.isEmpty ? 'Any' : formatDate(_f.to), onTap: () => _pickDate(false), error: problem == null ? null : ' ')),
            ]),
            if (problem != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text(problem, style: TextStyle(color: context.c.negative, fontWeight: FontWeight.w600))),
            const SizedBox(height: 12),
            _AccountFilter(filters: _f, setFilters: _set),
            const SizedBox(height: 12),
            PickerField(
              label: 'Strategy',
              value: chosen?.name ?? 'All strategies',
              onTap: () async {
                final id = await pickOption<String>(context, title: 'Strategy', selected: _f.strategyId, options: [('', 'All strategies', null), for (final s in options) (s.id, s.name, null)]);
                if (id != null) _set(_f.copyWith(strategyId: id));
              },
            ),
            const SizedBox(height: 12),
            PickerField(
              label: 'Result',
              value: _f.outcome.label,
              onTap: () async {
                final o = await pickOption<OutcomeFilter>(context, title: 'Result', selected: _f.outcome, options: [for (final o in OutcomeFilter.values) (o, o.label, null)]);
                if (o != null) _set(_f.copyWith(outcome: o));
              },
            ),
            const SizedBox(height: 18),
            Row(children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: () {
                    widget.onClear();
                    Navigator.pop(context);
                  },
                  child: const Text('Clear filters'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(child: FilledButton(onPressed: () => Navigator.pop(context), child: const Text('Show trades'))),
            ]),
          ]),
        ),
      ),
    );
  }
}

// ── Activity ────────────────────────────────────────────────────────────

class _ActivityTab extends ConsumerStatefulWidget {
  const _ActivityTab({required this.filters, required this.setFilters});
  final HistoryFilters filters;
  final ValueChanged<HistoryFilters> setFilters;

  @override
  ConsumerState<_ActivityTab> createState() => _ActivityTabState();
}

class _ActivityTabState extends ConsumerState<_ActivityTab> {
  bool _orders = false;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final account = widget.filters.accountId;
    final journal = _orders ? null : ref.watch(journalProvider(account));
    final orders = _orders ? ref.watch(ordersProvider(account)) : null;
    Color eventTone(String type) => switch (type) {
          'SIGNAL' => c.info,
          'RISK_REJECTED' => c.warning,
          'ORDER_FILLED' => c.positive,
          'POSITION_CLOSED' => c.primary,
          _ => c.subtle,
        };
    Widget body;
    if (!_orders) {
      final r = journal!;
      body = r.error != null && r.data == null
          ? ErrorView(error: r.error, onRetry: () => ref.read(journalProvider(account).notifier).load())
          : r.data == null
              ? const ListSkeleton(rows: 6, height: 58)
              : r.data!.isEmpty
                  ? const AppCard(child: EmptyState(icon: Icons.checklist_rounded, title: 'No activity yet', message: 'Every signal, risk decision, order and exit is written here as the bot works — including trades it decided not to take, and why.'))
                  : AppCard(
                      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                      child: Column(children: [
                        for (final e in r.data!)
                          Container(
                            padding: const EdgeInsets.symmetric(vertical: 11),
                            decoration: BoxDecoration(border: e == r.data!.last ? null : Border(bottom: BorderSide(color: c.border))),
                            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Padding(padding: const EdgeInsets.only(top: 5), child: Container(width: 9, height: 9, decoration: BoxDecoration(color: eventTone(e.eventType), shape: BoxShape.circle))),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                  Text(e.message, style: const TextStyle(fontSize: 14)),
                                  const SizedBox(height: 2),
                                  Text('${formatDateTime(e.occurredAt)} · ${humanize(e.eventType)}', style: tnum(context.text.labelSmall?.copyWith(fontWeight: FontWeight.w500, letterSpacing: 0, fontSize: 12))),
                                ]),
                              ),
                            ]),
                          ),
                      ]),
                    );
    } else {
      final r = orders!;
      body = r.error != null && r.data == null
          ? ErrorView(error: r.error, onRetry: () => ref.read(ordersProvider(account).notifier).load())
          : r.data == null
              ? const ListSkeleton(rows: 6, height: 58)
              : r.data!.isEmpty
                  ? const AppCard(child: EmptyState(icon: Icons.checklist_rounded, title: 'No orders yet', message: 'Orders are what 2kPilot sent to the broker to open or close trades.'))
                  : AppCard(
                      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                      child: Column(children: [
                        for (final o in r.data!)
                          Container(
                            padding: const EdgeInsets.symmetric(vertical: 11),
                            decoration: BoxDecoration(border: o == r.data!.last ? null : Border(bottom: BorderSide(color: c.border))),
                            child: Row(children: [
                              Expanded(
                                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                  Text('${o.purpose == 'ENTRY' ? 'Open' : 'Close'} ${o.symbol} · ${o.side == 'BUY' ? 'Buy' : 'Sell'}', style: const TextStyle(fontWeight: FontWeight.w600)),
                                  Text('${formatDateTime(o.createdAt)}${o.brokerMessage != null ? ' · ${o.brokerMessage}' : ''}', style: tnum(context.text.labelSmall?.copyWith(fontWeight: FontWeight.w500, letterSpacing: 0, fontSize: 12))),
                                ]),
                              ),
                              if (o.environment != null) ...[EnvBadge(o.environment!), const SizedBox(width: 8)],
                              Text(humanize(o.status),
                                  style: TextStyle(
                                    fontSize: 12.5,
                                    fontWeight: FontWeight.w700,
                                    color: o.status == 'FILLED' ? c.positive : (o.status == 'REJECTED' || o.status == 'FAILED') ? c.negative : c.muted,
                                  )),
                            ]),
                          ),
                      ]),
                    );
    }
    return RefreshIndicator(
      onRefresh: () async {
        if (_orders) {
          await ref.read(ordersProvider(account).notifier).load();
        } else {
          await ref.read(journalProvider(account).notifier).load();
        }
      },
      child: ListView(padding: const EdgeInsets.fromLTRB(16, 12, 16, 32), physics: const AlwaysScrollableScrollPhysics(), children: [
        _AccountFilter(filters: widget.filters, setFilters: widget.setFilters),
        const SizedBox(height: 12),
        SegmentedButton<bool>(
          showSelectedIcon: false,
          segments: const [ButtonSegment(value: false, label: Text('Bot decisions')), ButtonSegment(value: true, label: Text('Orders'))],
          selected: {_orders},
          onSelectionChanged: (s) => setState(() => _orders = s.first),
        ),
        const SizedBox(height: 12),
        body,
        const SizedBox(height: 12),
        const Notice(message: 'Decisions the bot did not take are listed too, with the reason (for example a risk limit). Nothing here is ever deleted.'),
      ]),
    );
  }
}
