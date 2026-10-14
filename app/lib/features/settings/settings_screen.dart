import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/dialogs.dart';
import '../../ui/widgets/states.dart';
import '../shell/app_shell.dart';

/// SETTINGS — accounts, risk limits, notifications, security, brokers, system.
class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final user = ref.watch(userProvider);
    final unread = ref.watch(unreadProvider.select((r) => r.data ?? 0));
    final theme = ref.watch(themeModeProvider);

    Widget tile(IconData icon, String title, String subtitle, String route, {Widget? trailing}) => ListTile(
          minTileHeight: 64,
          leading: IconBubble(icon, size: 38),
          title: Text(title),
          subtitle: Text(subtitle),
          trailing: trailing ?? Icon(Icons.chevron_right_rounded, color: c.subtle),
          onTap: () => context.push(route),
        );

    return TabPage(
      title: 'Settings',
      onRefresh: () async {},
      children: [
        if (user != null && user.email.isNotEmpty)
          AppCard(
            child: Row(children: [
              CircleAvatar(
                radius: 24,
                backgroundColor: c.soft(c.primary, 0.2),
                child: Text(user.name.isEmpty ? '?' : user.name.characters.first.toUpperCase(), style: TextStyle(color: c.brandInk, fontWeight: FontWeight.w900, fontSize: 20)),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(user.name, style: context.text.titleMedium),
                  Text(user.email, style: context.text.bodySmall),
                ]),
              ),
            ]),
          ),
        const SizedBox(height: 14),
        _Group(children: [
          tile(Icons.account_balance_wallet_outlined, 'Accounts', 'Risk profile, trading on/off, Demo or real money', '/settings/accounts'),
          tile(Icons.shield_outlined, 'Risk limits', 'The limits every trade must pass', '/settings/risk'),
          tile(
            Icons.notifications_none_rounded,
            'Notifications',
            'Alerts and push notifications',
            '/settings/notifications',
            trailing: Row(mainAxisSize: MainAxisSize.min, children: [
              if (unread > 0) Badge(label: Text('$unread'), backgroundColor: c.primary),
              const SizedBox(width: 6),
              Icon(Icons.chevron_right_rounded, color: c.subtle),
            ]),
          ),
        ]),
        const SizedBox(height: 14),
        _Group(children: [
          tile(Icons.lock_outline_rounded, 'Security', 'Signed-in devices, two-factor, password', '/settings/security'),
          tile(Icons.cable_rounded, 'Brokers', 'Connections to Deriv and Paper', '/settings/brokers'),
          tile(Icons.monitor_heart_outlined, 'System status', 'Engine, database and safety settings', '/settings/system'),
        ]),
        const SizedBox(height: 14),
        _Group(children: [
          ListTile(
            minTileHeight: 64,
            leading: const IconBubble(Icons.dark_mode_outlined, size: 38),
            title: const Text('Appearance'),
            subtitle: Text(switch (theme) { ThemeMode.light => 'Light', ThemeMode.dark => 'Dark', _ => 'Same as the phone' }),
            trailing: Icon(Icons.chevron_right_rounded, color: c.subtle),
            onTap: () async {
              final m = await pickOption<ThemeMode>(context, title: 'Appearance', selected: theme, options: const [
                (ThemeMode.system, 'Same as the phone', null),
                (ThemeMode.dark, 'Dark', null),
                (ThemeMode.light, 'Light', null),
              ]);
              if (m != null) ref.read(themeModeProvider.notifier).set(m);
            },
          ),
          tile(Icons.info_outline_rounded, 'About 2kPilot', 'Version, website, licences', '/settings/about'),
        ]),
        const SizedBox(height: 20),
        OutlinedButton.icon(
          style: OutlinedButton.styleFrom(foregroundColor: c.negative, side: BorderSide(color: c.soft(c.negative, 0.4))),
          onPressed: () => confirmSignOut(context, ref),
          icon: const Icon(Icons.logout_rounded),
          label: const Text('Sign out'),
        ),
        const SizedBox(height: 8),
        Text('Signing out does not stop your trading — it keeps running on the server. Press Stop first if you want it to stop.', textAlign: TextAlign.center, style: context.text.bodySmall),
      ],
    );
  }
}

Future<void> confirmSignOut(BuildContext context, WidgetRef ref) async {
  final ok = await confirmAction(
    context,
    title: 'Sign out of 2kPilot?',
    body: const ['This phone stops receiving your alerts. Your trading keeps running on the server until you press Stop.'],
    confirmLabel: 'Sign out',
  );
  if (ok) await ref.read(authProvider.notifier).signOut();
}

class _Group extends StatelessWidget {
  const _Group({required this.children});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => AppCard(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Column(children: [
          for (var i = 0; i < children.length; i++) ...[
            children[i],
            if (i < children.length - 1) Divider(indent: 70, color: context.c.border),
          ],
        ]),
      );
}
