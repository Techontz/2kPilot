import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/config.dart';
import '../../core/format.dart';
import '../../core/models/models.dart';
import '../../core/status.dart';
import '../../core/web_links.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/badges.dart';
import '../../ui/widgets/brand.dart';
import '../../ui/widgets/dialogs.dart';
import '../../ui/widgets/states.dart';
import 'settings_screen.dart';

// ── Security ────────────────────────────────────────────────────────────

/// Signed-in devices and sign out. Two-factor set-up and the password are
/// website-only for the app.
class SecurityScreen extends ConsumerWidget {
  const SecurityScreen({super.key});

  Future<void> _revoke(BuildContext context, WidgetRef ref, DeviceToken d) => confirmAction(
        context,
        title: d.current ? 'Sign out this phone?' : 'Sign out “${d.name}”?',
        body: [d.current ? 'You will need to sign in again on this phone.' : 'That device is signed out straight away and has to sign in again.'],
        confirmLabel: 'Sign out device',
        destructive: true,
        onConfirm: () async {
          if (d.current) {
            await ref.read(authProvider.notifier).signOut();
            return null;
          }
          try {
            await ref.read(apiClientProvider).delete('/auth/tokens/${d.id}');
            ref.read(devicesProvider.notifier).load();
            if (context.mounted) showSnack(context, 'Device signed out', detail: d.name);
            return null;
          } on ApiException catch (e) {
            return e.message;
          }
        },
      );

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final user = ref.watch(userProvider);
    final res = ref.watch(devicesProvider);
    final devices = res.data;
    return Scaffold(
      appBar: AppBar(title: const Text('Security')),
      body: RefreshIndicator(
        onRefresh: () async => ref.read(devicesProvider.notifier).load(),
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 40), physics: const AlwaysScrollableScrollPhysics(), children: [
          AppCard(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                IconBubble(Icons.verified_user_outlined, color: (user?.mfaEnabled ?? false) ? c.positive : c.warning, size: 38),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Text('Two-factor authentication', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 15)),
                    Text((user?.mfaEnabled ?? false) ? 'On — a code from your authenticator app is needed to sign in.' : 'Off — turn it on to protect your account.', style: context.text.bodySmall),
                  ]),
                ),
              ]),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: () => showWebOnly(context, link: WebLinks.security, message: 'Setting up two-factor authentication, recovery codes and changing your password are done on the 2kPilot website, in Settings → Security.'),
                icon: const Icon(Icons.open_in_new_rounded, size: 18),
                label: Text((user?.mfaEnabled ?? false) ? 'Manage on the website' : 'Set up on the website'),
              ),
            ]),
          ),
          const SizedBox(height: 12),
          AppCard(
            child: Row(children: [
              const IconBubble(Icons.password_rounded, size: 38),
              const SizedBox(width: 12),
              Expanded(child: Text('Password', style: context.text.titleSmall?.copyWith(fontSize: 15))),
              TextButton(onPressed: () => showWebOnly(context, link: WebLinks.security, message: 'Change your password on the 2kPilot website, in Settings → Security.'), child: const Text('Change on web')),
            ]),
          ),
          const SizedBox(height: 18),
          const SectionHeader('Signed-in devices', subtitle: 'Phones signed in to your 2kPilot account. Sign out any you don’t recognise.'),
          if (devices == null)
            res.error != null ? ErrorView(error: res.error, onRetry: () => ref.read(devicesProvider.notifier).load()) : const ListSkeleton(rows: 2, height: 70)
          else if (devices.isEmpty)
            const AppCard(child: EmptyState(icon: Icons.phone_iphone_rounded, title: 'No devices'))
          else
            AppCard(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(children: [
                for (final d in devices)
                  ListTile(
                    minTileHeight: 68,
                    leading: Icon(Icons.phone_iphone_rounded, color: d.current ? c.brandInk : c.muted),
                    title: Row(children: [
                      Flexible(child: Text(d.name, maxLines: 1, overflow: TextOverflow.ellipsis)),
                      if (d.current) ...[const SizedBox(width: 8), const Pill('This phone', tone: PillTone.primary)],
                    ]),
                    subtitle: Text('Signed in ${formatDate(d.createdAt)} · last used ${formatRelative(d.lastUsedAt)}${d.expiresAt != null ? ' · expires ${formatDate(d.expiresAt)}' : ''}'),
                    trailing: IconButton(tooltip: 'Sign out ${d.name}', onPressed: () => _revoke(context, ref, d), icon: Icon(Icons.logout_rounded, color: c.negative)),
                  ),
              ]),
            ),
          const SizedBox(height: 20),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(foregroundColor: c.negative, side: BorderSide(color: c.soft(c.negative, 0.4))),
            onPressed: () => confirmSignOut(context, ref),
            icon: const Icon(Icons.logout_rounded),
            label: const Text('Sign out of this phone'),
          ),
        ]),
      ),
    );
  }
}

// ── System status ───────────────────────────────────────────────────────

const _supervisor = {
  'running': (Tone.positive, 'Running'),
  'degraded': (Tone.warning, 'Running · attention'),
  'stale': (Tone.warning, 'Not responding'),
  'not_started': (Tone.warning, 'Not started'),
  'disabled': (Tone.neutral, 'Disabled on this server'),
  'unknown': (Tone.neutral, 'Unknown'),
};

class SystemStatusScreen extends ConsumerWidget {
  const SystemStatusScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final res = ref.watch(systemStatusProvider);
    final s = res.data;
    final accounts = ref.watch(accountsProvider.select((r) => r.data));
    Widget pill(Tone t, String label, {bool dot = false}) => Pill(label, tone: pillToneOf(t), dot: dot);
    return Scaffold(
      appBar: AppBar(title: const Text('System status')),
      body: RefreshIndicator(
        onRefresh: () async => ref.read(systemStatusProvider.notifier).load(),
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 40), physics: const AlwaysScrollableScrollPhysics(), children: [
          Text('Health of the trading engine, the database and the server’s safety settings. Refreshes every 15 seconds.', style: context.text.bodySmall?.copyWith(fontSize: 13.5)),
          const SizedBox(height: 12),
          if (s == null)
            res.error != null ? ErrorView(error: res.error, onRetry: () => ref.read(systemStatusProvider.notifier).load()) : const ListSkeleton(rows: 3, height: 90)
          else ...[
            Builder(builder: (_) {
              final view = engineHealthView(s.trading.copyWith(engineSummary: s.engineSummary));
              final svc = s.engineService;
              final sup = s.engineSupervisor;
              return AppCard(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                child: KeyValueList([
                  ('Trading engine', pill(view.tone, view.label, dot: true)),
                  (
                    'Engine API service',
                    svc != null
                        ? (svc.status == 'online'
                            ? pill(Tone.positive, 'Online${svc.version != null ? ' · v${svc.version}' : ''}')
                            : pill(Tone.negative, svc.status == 'error' ? 'Answering with an error' : 'Unreachable'))
                        : (s.engineStatus == 'ok' ? pill(Tone.positive, 'Reachable${s.engineVersion != null ? ' · v${s.engineVersion}' : ''}') : pill(Tone.negative, 'Unreachable')),
                  ),
                  ('Trading supervisor', sup != null ? pill(_supervisor[sup.state]?.$1 ?? Tone.neutral, _supervisor[sup.state]?.$2 ?? sup.state, dot: true) : KV(s.trading.engineState)),
                  ('Supervisor heartbeat', KV(s.trading.engineHeartbeatAt != null ? formatRelative(s.trading.engineHeartbeatAt) : 'Never')),
                  ('Database', s.database == 'ok' ? pill(Tone.positive, 'OK') : pill(Tone.negative, 'Error')),
                  ('Platform', s.trading.platformHalted ? pill(Tone.negative, 'Halted by an administrator', dot: true) : pill(Tone.positive, 'Normal')),
                  ('Real-money (LIVE) lock', s.liveTradingEnabled ? const Pill('Unlocked', tone: PillTone.live) : pill(Tone.positive, 'Locked')),
                  ('Two-factor required for everyone', KV(s.mfaRequired ? 'Yes' : 'No')),
                ]),
              );
            }),
            if (s.engineSummary != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(s.engineSummary!.message, style: context.text.bodySmall)),
          ],
          const SizedBox(height: 18),
          const SectionHeader('Broker connections', subtitle: 'As reported by the trading engine for each of your accounts.'),
          if (accounts == null)
            const ListSkeleton(rows: 2, height: 60)
          else if (accounts.isEmpty)
            Text('No broker accounts yet.', style: context.text.bodySmall)
          else
            AppCard(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(children: [
                for (final a in accounts)
                  ListTile(
                    title: Row(children: [Flexible(child: Text(a.label, maxLines: 1, overflow: TextOverflow.ellipsis)), const SizedBox(width: 8), EnvBadge(a.environment)]),
                    subtitle: Text('${a.broker}${a.connectionDetail != null ? ' · ${a.connectionDetail}' : ''}${a.lastConnectedAt != null ? ' · last connected ${formatRelative(a.lastConnectedAt)}' : ''}'),
                    trailing: _ConnectionPill(a.connectionStatus),
                  ),
              ]),
            ),
          const SizedBox(height: 14),
          Text('Platform controls and the audit log are on the website.', style: context.text.bodySmall),
        ]),
      ),
    );
  }
}

class _ConnectionPill extends StatelessWidget {
  const _ConnectionPill(this.status);
  final ConnectionStatus status;

  @override
  Widget build(BuildContext context) => Pill(
        status.label,
        dot: true,
        tone: switch (status) {
          ConnectionStatus.connected => PillTone.positive,
          ConnectionStatus.reconnecting => PillTone.warning,
          ConnectionStatus.error => PillTone.negative,
          _ => PillTone.neutral,
        },
      );
}

// ── Brokers (read-only) ─────────────────────────────────────────────────

class BrokersScreen extends ConsumerStatefulWidget {
  const BrokersScreen({super.key});

  @override
  ConsumerState<BrokersScreen> createState() => _BrokersScreenState();
}

class _BrokersScreenState extends ConsumerState<BrokersScreen> {
  String? _busy;

  Future<void> _run(String key, Future<void> Function() fn, String success) async {
    setState(() => _busy = key);
    try {
      await fn();
      await ref.read(accountsProvider.notifier).load();
      if (mounted) showSnack(context, success);
    } catch (e) {
      if (mounted) showApiError(context, e, webLink: WebLinks.brokers);
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final res = ref.watch(accountsProvider);
    final accounts = res.data;
    final api = ref.read(apiClientProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Brokers')),
      body: RefreshIndicator(
        onRefresh: () async => ref.read(accountsProvider.notifier).load(),
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 40), physics: const AlwaysScrollableScrollPhysics(), children: [
          Notice(
            title: 'Connect a broker on the website',
            message: 'Adding, disconnecting and removing brokers is done on the 2kPilot website. Here you can check each connection and reconnect it.',
            action: OutlinedButton.icon(onPressed: () => WebLinks.open(WebLinks.addBroker), icon: const Icon(Icons.open_in_new_rounded, size: 18), label: const Text('Add a broker')),
          ),
          const SizedBox(height: 14),
          if (accounts == null)
            res.error != null ? ErrorView(error: res.error, onRetry: () => ref.read(accountsProvider.notifier).load()) : const ListSkeleton(rows: 2, height: 180)
          else if (accounts.isEmpty)
            const AppCard(child: EmptyState(icon: Icons.cable_rounded, title: 'No broker connected yet', message: 'Start with Paper (no money) or connect Deriv demo on the website.'))
          else
            for (final a in accounts)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: AppCard(
                  border: Border(top: BorderSide(color: a.isLive ? c.live : a.environment == AccountEnvironment.demo ? c.demo : c.subtle, width: 3)),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    Row(children: [
                      Container(
                        width: 44,
                        height: 44,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(10),
                          gradient: LinearGradient(
                            begin: Alignment.topLeft,
                            end: Alignment.bottomRight,
                            colors: a.isLive ? const [Color(0xFFD6392E), Color(0xFF8A1A14)] : a.environment == AccountEnvironment.demo ? const [Color(0xFF9E4FE0), Color(0xFF5A1389)] : const [Color(0xFF3C3C40), Color(0xFF141416)],
                          ),
                        ),
                        child: Text(a.label.isEmpty ? '?' : a.label[0].toUpperCase(), style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 18)),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(a.broker, style: context.text.labelSmall?.copyWith(letterSpacing: 0)),
                          Text(a.label, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.text.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
                          Text('${a.brokerAccountId}${a.server.isNotEmpty ? ' · ${a.server}' : ''}', maxLines: 1, overflow: TextOverflow.ellipsis, style: tnum(context.text.labelSmall?.copyWith(letterSpacing: 0))),
                        ]),
                      ),
                      EnvBadge(a.environment),
                    ]),
                    const SizedBox(height: 12),
                    Align(alignment: Alignment.centerLeft, child: _ConnectionPill(a.connectionStatus)),
                    if (a.connectionDetail != null && a.connectionStatus != ConnectionStatus.connected) Padding(padding: const EdgeInsets.only(top: 4), child: Text(a.connectionDetail!, style: context.text.bodySmall)),
                    const SizedBox(height: 12),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 2),
                      decoration: BoxDecoration(color: c.raised, borderRadius: BorderRadius.circular(12)),
                      child: KeyValueList([
                        ('Balance', KV(formatCurrency(a.balance, a.currency))),
                        ('Equity', KV(formatCurrency(a.equity, a.currency))),
                        ('Last sync', KV(formatRelative(a.syncedAt))),
                        ('Trading', a.tradingEnabled ? const Pill('Enabled', tone: PillTone.positive) : const Pill('Off')),
                      ]),
                    ),
                    const SizedBox(height: 12),
                    Row(children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: _busy != null ? null : () => _run('sync:${a.id}', () => api.post('/accounts/${a.id}/sync'), 'Account synced'),
                          icon: const Icon(Icons.sync_rounded, size: 18),
                          label: Text(_busy == 'sync:${a.id}' ? 'Syncing…' : 'Sync now'),
                        ),
                      ),
                      if (a.connectionStatus != ConnectionStatus.connected || !a.connectionEnabled) ...[
                        const SizedBox(width: 8),
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: _busy != null ? null : () => _run('re:${a.id}', () => api.post('/brokers/${a.connectionId}/reconnect'), 'Reconnecting…'),
                            icon: const Icon(Icons.power_rounded, size: 18),
                            label: Text(_busy == 're:${a.id}' ? 'Reconnecting…' : 'Reconnect'),
                          ),
                        ),
                      ],
                    ]),
                  ]),
                ),
              ),
        ]),
      ),
    );
  }
}

// ── About ───────────────────────────────────────────────────────────────

class AboutScreen extends ConsumerWidget {
  const AboutScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final version = ref.watch(appVersionProvider);
    final c = context.c;
    return Scaffold(
      appBar: AppBar(title: const Text('About')),
      body: ListView(padding: const EdgeInsets.fromLTRB(20, 12, 20, 40), children: [
        const Center(child: LogoMark(size: 84)),
        const SizedBox(height: 16),
        const Center(child: Wordmark(size: 30)),
        const SizedBox(height: 6),
        Center(child: Text('Version $version', style: tnum(context.text.bodySmall))),
        const SizedBox(height: 20),
        Text(
          '2kPilot runs your trading strategies on the server, on Paper and Deriv accounts. Every trade passes your risk limits first, and you can stop everything with one tap.',
          textAlign: TextAlign.center,
          style: context.text.bodyMedium?.copyWith(color: c.muted),
        ),
        const SizedBox(height: 10),
        Text('Trading involves risk. Past results — including tests on history — do not guarantee future results.', textAlign: TextAlign.center, style: context.text.bodySmall),
        const SizedBox(height: 24),
        AppCard(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Column(children: [
            ListTile(leading: const Icon(Icons.language_rounded), title: const Text('2kPilot website'), trailing: const Icon(Icons.open_in_new_rounded, size: 18), onTap: () => WebLinks.open(WebLinks.home)),
            ListTile(
              leading: const Icon(Icons.description_outlined),
              title: const Text('Open-source licences'),
              trailing: const Icon(Icons.chevron_right_rounded),
              onTap: () => showLicensePage(context: context, applicationName: '2kPilot', applicationVersion: version),
            ),
            if (!AppConfig.apiBaseUrl.startsWith('https://2kpilot.techon.co.tz'))
              ListTile(leading: const Icon(Icons.dns_outlined), title: const Text('Server'), subtitle: Text(AppConfig.apiBaseUrl)),
          ]),
        ),
      ]),
    );
  }
}
