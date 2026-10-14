import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/auth/auth_controller.dart';
import 'core/push/push_service.dart';
import 'router.dart';
import 'state/providers.dart';
import 'state/push_registrar.dart';
import 'ui/theme.dart';

class TwoKPilotApp extends ConsumerStatefulWidget {
  const TwoKPilotApp({super.key});

  @override
  ConsumerState<TwoKPilotApp> createState() => _TwoKPilotAppState();
}

class _TwoKPilotAppState extends ConsumerState<TwoKPilotApp> {
  late final AppLifecycleListener _lifecycle;
  final _subs = <StreamSubscription<Object?>>[];
  PushTap? _pendingTap;

  @override
  void initState() {
    super.initState();
    final auth = ref.read(authProvider.notifier);
    auth.beforeSignOut = () => ref.read(pushRegistrarProvider.notifier).unregister();
    auth.restore();

    _lifecycle = AppLifecycleListener(onStateChange: (s) {
      ref.read(appActiveProvider.notifier).state = s == AppLifecycleState.resumed || s == AppLifecycleState.inactive;
    });

    final push = ref.read(pushServiceProvider);
    _pendingTap = push.takeLaunchTap();
    _subs.add(push.taps.listen(_openTap));
    _subs.add(push.foregroundMessages.listen((_) {
      // Something happened: refresh what the screens show.
      ref.read(unreadProvider.notifier).load();
      ref.read(statusProvider.notifier).load();
      ref.read(accountsProvider.notifier).load();
    }));
  }

  void _openTap(PushTap tap) {
    if (ref.read(authProvider) is! SignedIn) {
      _pendingTap = tap;
      return;
    }
    final accountId = tap.data['account_id'];
    if (accountId != null && accountId.isNotEmpty) ref.read(selectedAccountIdProvider.notifier).select(accountId);
    ref.read(routerProvider).push(tap.route);
    ref.read(unreadProvider.notifier).load();
  }

  @override
  void dispose() {
    _lifecycle.dispose();
    for (final s in _subs) {
      s.cancel();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<AuthState>(authProvider, (prev, next) {
      if (next is SignedIn && prev is! SignedIn) {
        ref.read(pushRegistrarProvider.notifier).syncAfterSignIn();
        final tap = _pendingTap;
        _pendingTap = null;
        if (tap != null) Future<void>.delayed(const Duration(milliseconds: 300), () => _openTap(tap));
      }
    });
    final router = ref.watch(routerProvider);
    final mode = ref.watch(themeModeProvider);
    return MaterialApp.router(
      title: '2kPilot',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(Brightness.light),
      darkTheme: buildTheme(Brightness.dark),
      themeMode: mode,
      routerConfig: router,
    );
  }
}
