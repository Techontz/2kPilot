import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/auth/auth_controller.dart';
import 'core/config.dart';
import 'features/auth/auth_screens.dart';
import 'features/history/history_screen.dart';
import 'features/history/trade_detail_screen.dart';
import 'features/home/home_screen.dart';
import 'features/settings/accounts_screen.dart';
import 'features/settings/notifications_screen.dart';
import 'features/settings/risk_screen.dart';
import 'features/settings/settings_screen.dart';
import 'features/settings/system_screens.dart';
import 'features/shell/app_shell.dart';
import 'features/strategies/backtest_report_screen.dart';
import 'features/strategies/strategies_screen.dart';
import 'state/providers.dart';
import 'state/push_registrar.dart';

final rootNavigatorKey = GlobalKey<NavigatorState>();

const _authPages = {'/splash', '/login', '/mfa', '/push-intro'};

/// Where the router should send the user, given the session (pure; unit-tested).
String? authRedirect({required AuthState auth, required bool pushExplainerDue, required Uri location}) {
  final path = location.path;
  switch (auth) {
    case AuthRestoring():
      return path == '/splash' ? null : '/splash';
    case SignedOut():
      if (path == '/login') return null;
      final from = _authPages.contains(path) || path == '/' ? null : location.toString();
      return from == null ? '/login' : Uri(path: '/login', queryParameters: {'from': from}).toString();
    case MfaPending():
      return path == '/mfa' ? null : '/mfa';
    case SignedIn():
      if (pushExplainerDue) return path == '/push-intro' ? null : '/push-intro';
      if (_authPages.contains(path) || path == '/') {
        final from = location.queryParameters['from'];
        if (from != null && from.startsWith('/') && !from.startsWith('//')) return from;
        return AppConfig.demoRoute.isNotEmpty ? AppConfig.demoRoute : '/home';
      }
      return null;
  }
}

class _RouterRefresh extends ChangeNotifier {
  void ping() => notifyListeners();
}

final routerProvider = Provider<GoRouter>((ref) {
  final refresh = _RouterRefresh();
  ref.listen(authProvider, (_, _) => refresh.ping());
  ref.listen(pushRegistrarProvider.select((p) => p.asked), (_, _) => refresh.ping());
  ref.onDispose(refresh.dispose);

  Page<void> modal(Widget child) => MaterialPage<void>(fullscreenDialog: false, child: child);

  final router = GoRouter(
    navigatorKey: rootNavigatorKey,
    initialLocation: '/splash',
    refreshListenable: refresh,
    redirect: (context, state) {
      final auth = ref.read(authProvider);
      final push = ref.read(pushRegistrarProvider);
      return authRedirect(auth: auth, pushExplainerDue: auth is SignedIn && push.available && !push.asked, location: state.uri);
    },
    routes: [
      GoRoute(path: '/', redirect: (_, _) => '/home'),
      GoRoute(path: '/splash', builder: (_, _) => const SplashScreen()),
      GoRoute(path: '/login', builder: (_, _) => const LoginScreen()),
      GoRoute(path: '/mfa', builder: (_, _) => const MfaScreen()),
      GoRoute(path: '/push-intro', builder: (_, _) => const PushIntroScreen()),
      StatefulShellRoute.indexedStack(
        builder: (context, state, shell) => AppShell(shell: shell),
        branches: [
          StatefulShellBranch(routes: [GoRoute(path: '/home', builder: (_, _) => const HomeScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: '/strategies', builder: (_, s) => StrategiesScreen(initialTab: s.uri.queryParameters['tab']))]),
          StatefulShellBranch(routes: [GoRoute(path: '/history', builder: (_, s) => HistoryScreen(initialTab: s.uri.queryParameters['tab']))]),
          StatefulShellBranch(routes: [GoRoute(path: '/settings', builder: (_, _) => const SettingsScreen())]),
        ],
      ),
      GoRoute(path: '/trades/:id', pageBuilder: (_, s) => modal(TradeDetailScreen(tradeId: s.pathParameters['id']!))),
      GoRoute(path: '/strategies/backtests/:id', pageBuilder: (_, s) => modal(BacktestReportScreen(id: s.pathParameters['id']!))),
      GoRoute(path: '/settings/accounts', pageBuilder: (_, _) => modal(const AccountsScreen())),
      GoRoute(path: '/settings/risk', pageBuilder: (_, _) => modal(const RiskScreen())),
      GoRoute(path: '/settings/notifications', pageBuilder: (_, _) => modal(const NotificationsScreen())),
      GoRoute(path: '/settings/security', pageBuilder: (_, _) => modal(const SecurityScreen())),
      GoRoute(path: '/settings/system', pageBuilder: (_, _) => modal(const SystemStatusScreen())),
      GoRoute(path: '/settings/brokers', pageBuilder: (_, _) => modal(const BrokersScreen())),
      GoRoute(path: '/settings/about', pageBuilder: (_, _) => modal(const AboutScreen())),
    ],
    errorBuilder: (context, state) => Scaffold(
      appBar: AppBar(),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Text('Page not found', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
            const SizedBox(height: 12),
            FilledButton(onPressed: () => GoRouter.of(context).go('/home'), child: const Text('Go to Home')),
          ]),
        ),
      ),
    ),
  );
  ref.onDispose(router.dispose);
  return router;
});
