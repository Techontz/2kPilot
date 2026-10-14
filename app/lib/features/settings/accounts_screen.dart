import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/format.dart';
import '../../core/models/models.dart';
import '../../core/web_links.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/badges.dart';
import '../../ui/widgets/dialogs.dart';
import '../../ui/widgets/states.dart';
import '../shell/trading_control.dart';

/// Settings → Accounts: which account Home/History show, its risk profile,
/// trading on/off — and DEMO/LIVE (real money is authorised on the website).
class AccountsScreen extends ConsumerWidget {
  const AccountsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final res = ref.watch(accountsProvider);
    final accounts = res.data;
    final selected = ref.watch(currentAccountProvider);
    final profiles = ref.watch(riskProfilesProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Accounts')),
      body: RefreshIndicator(
        onRefresh: () async => Future.wait([ref.read(accountsProvider.notifier).load(), ref.read(statusProvider.notifier).load(), ref.read(riskProfilesProvider.notifier).load()]),
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 40), physics: const AlwaysScrollableScrollPhysics(), children: [
          const RealMoneyCard(),
          const SizedBox(height: 18),
          const SectionHeader('Your accounts',
              subtitle: 'The account you use is what Home and History show. Each account needs a risk profile and its own “Trading enabled” switch before anything can trade on it.'),
          if (accounts == null)
            res.error != null ? ErrorView(error: res.error, onRetry: () => ref.read(accountsProvider.notifier).load()) : const ListSkeleton(rows: 2, height: 220)
          else if (accounts.isEmpty)
            AppCard(
              child: EmptyState(
                icon: Icons.cable_rounded,
                title: 'No accounts yet',
                message: 'Start with Paper (no money) or connect a Deriv demo account — on the website.',
                action: FilledButton.icon(onPressed: () => WebLinks.open(WebLinks.addBroker), icon: const Icon(Icons.open_in_new_rounded, size: 18), label: const Text('Add broker')),
              ),
            )
          else
            for (final a in accounts)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: AccountSettingsCard(account: a, selected: a.id == selected?.id, profiles: profiles.data, profilesError: profiles.error),
              ),
        ]),
      ),
    );
  }
}

class AccountSettingsCard extends ConsumerStatefulWidget {
  const AccountSettingsCard({super.key, required this.account, required this.selected, required this.profiles, this.profilesError});
  final Account account;
  final bool selected;
  final List<RiskProfile>? profiles;
  final ApiException? profilesError;

  @override
  ConsumerState<AccountSettingsCard> createState() => _AccountSettingsCardState();
}

class _AccountSettingsCardState extends ConsumerState<AccountSettingsCard> {
  String? _busy;
  String? _error;

  Future<void> _patch(String what, Map<String, Object?> body, String success) async {
    setState(() {
      _busy = what;
      _error = null;
    });
    try {
      await ref.read(apiClientProvider).patch('/accounts/${widget.account.id}', body: body);
      await ref.read(accountsProvider.notifier).load();
      if (mounted) showSnack(context, success);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
      showApiError(context, e, title: 'Not changed');
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final a = widget.account;
    final profiles = widget.profiles;
    return AppCard(
      border: a.isLive ? Border(top: BorderSide(color: c.live, width: 3)) : (widget.selected ? Border.all(color: c.soft(c.primary, 0.6), width: 1.5) : null),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [ConnectionDot(a.connectionStatus), const SizedBox(width: 8), Flexible(child: Text(a.label, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.text.titleMedium))]),
              const SizedBox(height: 3),
              Text('${a.broker} · ${a.brokerAccountId} · ${a.connectionStatus.label}', maxLines: 1, overflow: TextOverflow.ellipsis, style: context.text.bodySmall),
            ]),
          ),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            EnvBadge(a.environment),
            const SizedBox(height: 4),
            Text(formatCurrency(a.balance, a.currency), style: tnum(const TextStyle(fontWeight: FontWeight.w700))),
          ]),
        ]),
        const SizedBox(height: 12),
        Align(
          alignment: Alignment.centerLeft,
          child: widget.selected
              ? const Pill('In use on Home and History', tone: PillTone.primary, icon: Icons.check_circle_rounded)
              : OutlinedButton(
                  onPressed: () {
                    ref.read(selectedAccountIdProvider.notifier).select(a.id);
                    showSnack(context, 'Using ${a.label}', detail: 'Home and History now show this account.');
                  },
                  child: const Text('Use this account'),
                ),
        ),
        Divider(height: 28, color: c.border),
        if (widget.profilesError != null)
          ErrorView(error: widget.profilesError, onRetry: () => ref.read(riskProfilesProvider.notifier).load())
        else
          PickerField(
            label: 'Risk profile',
            enabled: _busy == null && profiles != null,
            value: profiles == null ? 'Loading…' : (a.riskProfile?.name ?? 'None (this account cannot trade)'),
            onTap: () async {
              final id = await pickOption<String>(context, title: 'Risk profile', selected: a.riskProfile?.id ?? '', options: [
                ('', 'None (this account cannot trade)', null),
                for (final p in profiles!) (p.id, p.name, null),
              ]);
              if (id != null && id != (a.riskProfile?.id ?? '')) _patch('profile', {'risk_profile_id': id.isEmpty ? null : id}, 'Risk profile saved');
            },
          ),
        const SizedBox(height: 6),
        Text('The limits every trade on this account must pass: stake, daily loss, losses in a row. Edit them in Risk limits.', style: context.text.bodySmall?.copyWith(fontSize: 12.5)),
        Divider(height: 28, color: c.border),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('Trading enabled', style: TextStyle(fontWeight: FontWeight.w700)),
          subtitle: Text(a.tradingEnabled
              ? 'On: strategies may trade on this account (the risk engine still decides every trade).'
              : 'Off: nothing can trade on this account, even when trading is started.'),
          value: a.tradingEnabled,
          onChanged: _busy != null ? null : (v) => _patch('trading', {'trading_enabled': v}, v ? 'Trading enabled on this account' : 'Trading switched off on this account'),
        ),
        if (_error != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text(_error!, style: TextStyle(color: c.negative, fontWeight: FontWeight.w600))),
      ]),
    );
  }
}

/// Current mode, the one-tap way back to Demo, and where real money is authorised (the website).
class RealMoneyCard extends ConsumerStatefulWidget {
  const RealMoneyCard({super.key});

  @override
  ConsumerState<RealMoneyCard> createState() => _RealMoneyCardState();
}

class _RealMoneyCardState extends ConsumerState<RealMoneyCard> {
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final status = ref.watch(statusProvider.select((r) => r.data));
    if (status == null) return const Skeleton(height: 160, radius: 16);
    final live = status.isLive;
    return AppCard(
      color: live ? c.soft(c.live, 0.1) : null,
      border: live ? Border.all(color: c.live, width: 2) : null,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: Text('Real-money (LIVE) trading', style: context.text.titleMedium?.copyWith(fontWeight: FontWeight.w800))),
          live ? const Pill('LIVE — REAL MONEY', tone: PillTone.live, dot: true) : const Pill('DEMO', tone: PillTone.demo),
        ]),
        const SizedBox(height: 6),
        Text(
          live
              ? 'LIVE mode is on: only real-money accounts may trade. Paper and demo accounts are paused.'
              : 'You are in Demo mode: only Paper and demo accounts can trade. Real money is never touched.',
          style: context.text.bodySmall?.copyWith(fontSize: 13.5),
        ),
        if (!live && status.liveRevokedReason != null)
          Padding(padding: const EdgeInsets.only(top: 10), child: Notice(tone: NoticeTone.warning, title: 'LIVE mode was turned off', message: '${status.liveRevokedReason} Authorise again on the website to trade with real money.')),
        const SizedBox(height: 14),
        if (live) ...[
          FilledButton.icon(
            onPressed: _busy
                ? null
                : () async {
                    setState(() => _busy = true);
                    await returnToDemo(context, ref);
                    if (mounted) setState(() => _busy = false);
                  },
            icon: const Icon(Icons.verified_user_rounded),
            label: Text(_busy ? 'Returning…' : 'Return to Demo'),
          ),
          const SizedBox(height: 6),
          Text('One tap: trading is stopped first if needed, then Demo is switched on.', style: context.text.bodySmall?.copyWith(fontSize: 12.5)),
          if (status.liveAuthorizedAt != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text('Authorised ${formatDateTime(status.liveAuthorizedAt)}.', style: context.text.bodySmall?.copyWith(fontSize: 12.5))),
        ] else if (status.liveTradingLocked) ...[
          const Notice(title: 'Locked on this server', message: 'Real-money trading is locked on this server. The server administrator must enable it.'),
        ] else ...[
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(foregroundColor: c.live, side: BorderSide(color: c.soft(c.live, 0.6))),
            onPressed: () => WebLinks.open(WebLinks.realMoney),
            icon: const Icon(Icons.open_in_new_rounded, size: 18),
            label: const Text('Authorize real money on the website'),
          ),
          const SizedBox(height: 6),
          Text('For your safety this is website-only. It needs a LIVE account with a risk profile, two-factor authentication, your password and a typed confirmation.', style: context.text.bodySmall?.copyWith(fontSize: 12.5)),
        ],
      ]),
    );
  }
}
