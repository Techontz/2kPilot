import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/contracts.dart';
import '../../core/format.dart';
import '../../core/models/models.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/badges.dart';
import '../../ui/widgets/dialogs.dart';
import '../../ui/widgets/money.dart';
import '../../ui/widgets/states.dart';

/// One trade, start to finish: what it was, how it ended, and why the bot took
/// it (market check → signal → risk decision → order → broker → exit).
class TradeDetailScreen extends ConsumerWidget {
  const TradeDetailScreen({super.key, required this.tradeId});
  final String tradeId;

  Future<void> _close(BuildContext context, WidgetRef ref, Trade t) async {
    await confirmAction(
      context,
      title: 'Close this trade now?',
      body: [
        '${t.symbol} ${tradeDirection(t)} is closed at the current market price. The result is final.',
        if (t.contractFamily == 'MULTIPLIER') 'A Multiplier closed early keeps whatever profit or loss it has right now.',
      ],
      confirmLabel: 'Close trade',
      destructive: true,
      onConfirm: () async {
        try {
          await ref.read(tradingActionsProvider).closePosition(t.id);
          ref.read(tradeChainProvider(tradeId).notifier).load();
          if (context.mounted) showSnack(context, 'Close requested', detail: 'The broker is closing ${t.symbol}. It moves to Closed once it is done.');
          return null;
        } on ApiException catch (e) {
          return e.isWebOnly ? 'Do this on the 2kPilot website. ${e.message}' : e.message;
        }
      },
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final res = ref.watch(tradeChainProvider(tradeId));
    final chain = res.data;
    final t = chain?.trade;
    final currency = t?.account?.currency;
    return Scaffold(
      appBar: AppBar(
        title: t == null
            ? const Text('Trade')
            : Row(children: [Text(t.symbol, style: context.text.headlineSmall), const SizedBox(width: 10), DirectionText(t, size: 14)]),
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.read(tradeChainProvider(tradeId).notifier).load(),
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 40), physics: const AlwaysScrollableScrollPhysics(), children: [
          if (res.error != null && chain == null)
            ErrorView(error: res.error, onRetry: () => ref.read(tradeChainProvider(tradeId).notifier).load())
          else if (chain == null || t == null)
            const ListSkeleton(rows: 4, height: 90)
          else ...[
            Wrap(spacing: 8, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
              if (t.account != null) EnvBadge(t.account!.environment),
              OutcomeBadge(t),
              Text(
                t.source == 'MANUAL' ? 'Manual trade' : t.source == 'EXTERNAL' ? 'Opened outside 2kPilot' : '${t.strategy ?? 'Strategy'}${t.strategyVersion != null ? ' v${t.strategyVersion}' : ''}',
                style: context.text.bodySmall?.copyWith(fontSize: 13.5),
              ),
              if (t.isSimulated) Text('· simulated', style: context.text.bodySmall?.copyWith(color: c.subtle)),
            ]),
            const SizedBox(height: 14),
            Container(
              padding: const EdgeInsets.all(18),
              decoration: BoxDecoration(color: c.raised, borderRadius: BorderRadius.circular(18)),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(t.isOpen ? 'CURRENT P/L (NOT FINAL)' : 'RESULT', style: context.text.labelSmall?.copyWith(letterSpacing: 1.2)),
                const SizedBox(height: 4),
                PnlText(t.netPnl ?? t.unrealizedPnl, currency: currency, style: context.text.displaySmall),
              ]),
            ),
            if (t.isOpen && t.contractFamily != 'RISE_FALL') ...[
              const SizedBox(height: 12),
              OutlinedButton.icon(
                style: OutlinedButton.styleFrom(foregroundColor: c.negative, side: BorderSide(color: c.soft(c.negative, 0.5))),
                onPressed: () => _close(context, ref, t),
                icon: const Icon(Icons.cancel_outlined),
                label: const Text('Close this trade…'),
              ),
            ],
            if (t.isOpen && t.contractFamily == 'RISE_FALL')
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text("Rise/Fall contracts can't be closed early — this one settles on its own at expiry.", style: context.text.bodySmall),
              ),
            const SizedBox(height: 14),
            AppCard(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
              child: KeyValueList([
                ('Contract', KV(tradeContractLabel(t) + (t.contractType != null ? ' (${t.contractType})' : ''))),
                if (t.contractFamily == 'RISE_FALL') ('Duration', KV(durationText(t.duration, t.durationUnit))),
                (isContractTrade(t) ? 'Stake' : 'Size', KV(sizeText(t, currency))),
                ('Opened', KV(formatDateTime(t.entryTime))),
                ('Entry', KV(formatPrice(t.entrySpot ?? t.entryPrice, t.symbol))),
                if (t.expiresAt != null) ('Expires', KV(formatDateTime(t.expiresAt))),
                ('Closed', KV(t.exitTime != null ? formatDateTime(t.exitTime) : 'Still open')),
                ('Exit', KV(t.exitTime != null ? formatPrice(t.exitSpot ?? t.exitPrice, t.symbol) : emDash)),
                if (t.exitReason != null) ('Why it closed', KV(humanize(t.exitReason!))),
                ('Fees', KV(formatCurrency(t.fees ?? t.commission ?? '0', currency))),
                if (t.payout != null) ('Payout', KV(formatCurrency(t.payout, currency))),
                ('Held for', KV(formatDuration(t.durationSeconds))),
                if (t.brokerContractId != null) ('Broker contract', KV(t.brokerContractId!)),
              ]),
            ),
            if (t.longcode != null) ...[
              const SizedBox(height: 16),
              Text('WHAT THE BROKER SAYS', style: context.text.labelSmall?.copyWith(letterSpacing: 1.2)),
              const SizedBox(height: 6),
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(color: c.raised, borderRadius: BorderRadius.circular(14)),
                child: Text(t.longcode!, style: context.text.bodyMedium?.copyWith(color: c.muted)),
              ),
            ],
            const SizedBox(height: 16),
            AppCard(
              padding: EdgeInsets.zero,
              child: Theme(
                data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                child: Column(children: [
                  ExpansionTile(
                    initiallyExpanded: true,
                    title: const Text('Why the bot took this trade'),
                    childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
                    expandedCrossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (chain.evaluation != null) ...[
                        Text(chain.evaluation!.summary),
                        const SizedBox(height: 8),
                        ChecksList(chain.evaluation!.checks),
                      ] else if (chain.signal != null)
                        Text(chain.signal!.reasons.join('; '))
                      else
                        Text(t.source == 'STRATEGY' ? 'The market check was not stored.' : 'Not opened by a strategy.', style: TextStyle(color: c.muted)),
                    ],
                  ),
                  Divider(color: c.border, height: 1),
                  ExpansionTile(
                    title: Text('Risk checks (${chain.signal?.riskChecks.where((r) => r.passed).length ?? 0}/${chain.signal?.riskChecks.length ?? 0} passed)'),
                    childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
                    expandedCrossAxisAlignment: CrossAxisAlignment.start,
                    children: [chain.signal?.riskChecks.isNotEmpty ?? false ? ChecksList(chain.signal!.riskChecks) : Text('No risk checks stored.', style: TextStyle(color: c.muted))],
                  ),
                  Divider(color: c.border, height: 1),
                  ExpansionTile(
                    title: Text('Orders sent to the broker (${chain.orders.length})'),
                    childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
                    expandedCrossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (chain.orders.isEmpty) Text(emDash, style: TextStyle(color: c.muted)),
                      for (final o in chain.orders)
                        Container(
                          width: double.infinity,
                          margin: const EdgeInsets.only(bottom: 8),
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(borderRadius: BorderRadius.circular(10), border: Border.all(color: c.border)),
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text('${o.purpose == 'ENTRY' ? 'Open' : 'Close'} · ${humanize(o.status)}', style: const TextStyle(fontWeight: FontWeight.w600)),
                            Text('fill ${o.fillPrice ?? emDash}${o.brokerMessage != null ? ' · ${o.brokerMessage}' : ''}', style: tnum(context.text.bodySmall)),
                          ]),
                        ),
                    ],
                  ),
                  Divider(color: c.border, height: 1),
                  ExpansionTile(
                    title: Text('Timeline (${chain.events.length})'),
                    childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
                    expandedCrossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (chain.events.isEmpty) Text('No events.', style: TextStyle(color: c.muted)),
                      for (final e in chain.events)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text('${formatDateTime(e.occurredAt)} · ${humanize(e.eventType)}', style: tnum(context.text.labelSmall?.copyWith(fontWeight: FontWeight.w600, letterSpacing: 0))),
                            Text(e.message),
                          ]),
                        ),
                    ],
                  ),
                ]),
              ),
            ),
          ],
        ]),
      ),
    );
  }
}

class ChecksList extends StatelessWidget {
  const ChecksList(this.items, {super.key});
  final List<RiskCheck> items;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final i in items)
        Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(i.passed ? Icons.check_circle_rounded : Icons.cancel_rounded, size: 17, color: i.passed ? c.positive : c.negative, semanticLabel: i.passed ? 'passed' : 'failed'),
            const SizedBox(width: 8),
            Expanded(
              child: Text.rich(TextSpan(children: [
                TextSpan(text: i.rule, style: TextStyle(color: c.fg, fontWeight: FontWeight.w600)),
                TextSpan(text: ' — ${i.detail}', style: TextStyle(color: c.subtle)),
              ]), style: const TextStyle(fontSize: 13.5)),
            ),
          ]),
        ),
    ]);
  }
}
