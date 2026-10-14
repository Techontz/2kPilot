import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/models/models.dart';
import '../../core/status.dart';
import '../../core/web_links.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/brand.dart';
import 'trading_control.dart';

/// Bottom tabs: Home, Strategies, History, Settings.
class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.shell});
  final StatefulNavigationShell shell;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final unread = ref.watch(unreadProvider.select((r) => r.data ?? 0));
    final c = context.c;
    return Scaffold(
      body: shell,
      bottomNavigationBar: DecoratedBox(
        decoration: BoxDecoration(border: Border(top: BorderSide(color: c.border))),
        child: NavigationBar(
          selectedIndex: shell.currentIndex,
          onDestinationSelected: (i) => shell.goBranch(i, initialLocation: i == shell.currentIndex),
          labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
          destinations: [
            const NavigationDestination(icon: Icon(Icons.home_outlined), selectedIcon: Icon(Icons.home_rounded), label: 'Home'),
            const NavigationDestination(icon: Icon(Icons.auto_graph_outlined), selectedIcon: Icon(Icons.auto_graph_rounded), label: 'Strategies'),
            const NavigationDestination(icon: Icon(Icons.receipt_long_outlined), selectedIcon: Icon(Icons.receipt_long_rounded), label: 'History'),
            NavigationDestination(
              icon: Badge(isLabelVisible: unread > 0, label: Text(unread > 99 ? '99+' : '$unread'), backgroundColor: c.primary, child: const Icon(Icons.settings_outlined)),
              selectedIcon: Badge(isLabelVisible: unread > 0, label: Text(unread > 99 ? '99+' : '$unread'), backgroundColor: c.primary, child: const Icon(Icons.settings_rounded)),
              label: 'Settings',
              tooltip: unread > 0 ? 'Settings, $unread unread notifications' : 'Settings',
            ),
          ],
        ),
      ),
    );
  }
}

/// A main tab: top bar with DEMO/LIVE and Start/Stop, the safety banners,
/// and pull-to-refresh content.
class TabPage extends ConsumerWidget {
  const TabPage({super.key, required this.title, this.showLogo = false, this.children, this.body, this.onRefresh, this.bottom, this.actions = const []});
  final String title;
  final bool showLogo;
  final List<Widget>? children;
  final Widget? body;
  final Future<void> Function()? onRefresh;
  final PreferredSizeWidget? bottom;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    Widget content = body ??
        ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
          physics: const AlwaysScrollableScrollPhysics(),
          children: children ?? const [],
        );
    if (onRefresh != null) {
      content = RefreshIndicator(
        onRefresh: () async {
          await Future.wait([refreshCore(ref), onRefresh!()]);
        },
        child: content,
      );
    }
    return Scaffold(
      appBar: AppBar(
        toolbarHeight: 60,
        titleSpacing: 16,
        title: showLogo ? const Logo(size: 21) : Semantics(header: true, child: Text(title, style: context.text.headlineSmall)),
        actions: [...actions, const ModePill(), const SizedBox(width: 8), const TradingToggle(), const SizedBox(width: 12)],
        bottom: bottom,
      ),
      body: Column(children: [const SafetyBanners(), Expanded(child: content)]),
    );
  }
}

/// A loud strip for a LIVE (real money) account, the platform halt, engine
/// health (offline only when its API cannot be reached), being offline, and
/// the two-factor nudge.
class SafetyBanners extends ConsumerWidget {
  const SafetyBanners({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final account = ref.watch(currentAccountProvider);
    final status = ref.watch(statusProvider.select((r) => r.data));
    final offline = ref.watch(offlineProvider);
    final user = ref.watch(userProvider);
    final engine = status == null ? null : engineHealthView(status);
    final items = <Widget>[];

    if (offline) {
      items.add(_Banner(
        icon: Icons.cloud_off_rounded,
        color: c.warning,
        title: "You're offline",
        message: "Can't reach 2kPilot. Showing the last known data — Stop still works when you're back.",
      ));
    }
    if (status?.platformHalted ?? false) {
      items.add(_Banner(
        icon: Icons.report_rounded,
        color: c.negative,
        title: 'Trading is halted platform-wide by an administrator',
        message: 'No new orders for anyone.${status!.platformHaltReason != null ? ' Reason: ${status.platformHaltReason}' : ''}',
      ));
    }
    if (engine != null && engine.banner && !offline) {
      final color = switch (engine.tone) { Tone.negative => c.negative, Tone.info => c.brandInk, _ => c.warning };
      items.add(_Banner(icon: engine.tone == Tone.info ? Icons.info_outline_rounded : Icons.warning_amber_rounded, color: color, title: engine.label, message: engine.message, calm: engine.tone == Tone.info));
    }
    if (user != null && user.id.isNotEmpty && !user.mfaEnabled) {
      items.add(_Banner(
        icon: Icons.shield_outlined,
        color: c.warning,
        title: 'Protect this account',
        message: 'Turn on two-factor authentication on the website.',
        calm: true,
        onTap: () => WebLinks.open(WebLinks.security),
      ));
    }

    return Column(mainAxisSize: MainAxisSize.min, children: [
      if (account?.environment == AccountEnvironment.live)
        Semantics(
          container: true,
          label: 'LIVE account. Real money.',
          child: Container(
            width: double.infinity,
            color: c.live,
            padding: const EdgeInsets.symmetric(vertical: 7, horizontal: 16),
            child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              Icon(Icons.report_rounded, size: 16, color: c.onLive),
              const SizedBox(width: 8),
              Text('LIVE ACCOUNT — REAL MONEY', style: TextStyle(color: c.onLive, fontWeight: FontWeight.w900, fontSize: 12, letterSpacing: 1.6)),
            ]),
          ),
        ),
      if (items.isNotEmpty) Padding(padding: const EdgeInsets.fromLTRB(16, 8, 16, 4), child: Column(children: [for (final i in items) Padding(padding: const EdgeInsets.only(bottom: 6), child: i)])),
    ]);
  }
}

class _Banner extends StatelessWidget {
  const _Banner({required this.icon, required this.color, required this.title, required this.message, this.calm = false, this.onTap});
  final IconData icon;
  final Color color;
  final String title;
  final String message;
  final bool calm;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Semantics(
      container: true,
      liveRegion: !calm,
      child: Material(
        color: calm ? c.raised : c.soft(color, 0.1),
        borderRadius: BorderRadius.circular(14),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(14),
          child: Container(
            padding: const EdgeInsets.fromLTRB(10, 9, 12, 9),
            decoration: BoxDecoration(borderRadius: BorderRadius.circular(14), border: Border.all(color: c.soft(color, calm ? 0.25 : 0.35))),
            child: Row(children: [
              Container(width: 28, height: 28, decoration: BoxDecoration(color: c.soft(color, 0.18), shape: BoxShape.circle), child: Icon(icon, size: 16, color: color)),
              const SizedBox(width: 10),
              Expanded(
                child: Text.rich(
                  TextSpan(children: [
                    TextSpan(text: title, style: TextStyle(fontWeight: FontWeight.w800, color: calm ? c.fg : color)),
                    TextSpan(text: ' — $message', style: TextStyle(color: c.muted)),
                  ]),
                  style: const TextStyle(fontSize: 13, height: 1.35),
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (onTap != null) Icon(Icons.chevron_right_rounded, color: c.subtle),
            ]),
          ),
        ),
      ),
    );
  }
}
