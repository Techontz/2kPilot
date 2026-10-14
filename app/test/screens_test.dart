// Widget tests for the main screens, driven by the debug demo backend.
// With SCREENSHOT_DIR set they also save a PNG of every screen:
//   SCREENSHOT_DIR=/tmp/shots flutter test test/screens_test.dart
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/intl.dart';
import 'package:twokpilot/app.dart';
import 'package:twokpilot/core/auth/secure_store.dart';
import 'package:twokpilot/core/demo/demo_backend.dart';
import 'package:twokpilot/core/push/push_service.dart';
import 'package:twokpilot/router.dart';
import 'package:twokpilot/state/providers.dart';

import 'helpers.dart';

final _dir = Platform.environment['SCREENSHOT_DIR'];
const shotKey = ValueKey('shot');

Future<void> shot(WidgetTester tester, String name) async {
  if (_dir == null) return;
  final boundary = tester.renderObject<RenderRepaintBoundary>(find.byKey(shotKey));
  await tester.runAsync(() async {
    final image = await boundary.toImage(pixelRatio: tester.view.devicePixelRatio);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    Directory(_dir!).createSync(recursive: true);
    File('$_dir/$name.png').writeAsBytesSync(bytes!.buffer.asUint8List());
  });
}

Future<ProviderContainer> launch(WidgetTester tester, {required String theme, String scenario = ''}) async {
  phoneSurface(tester);
  tester.platformDispatcher.accessibilityFeaturesTestValue = const FakeAccessibilityFeatures(disableAnimations: true);
  addTearDown(tester.platformDispatcher.clearAccessibilityFeaturesTestValue);
  await tester.pumpWidget(RepaintBoundary(key: shotKey, child: ProviderScope(
    overrides: [
      ...demoOverrides(scenario: scenario, latency: Duration.zero, store: {StoreKeys.theme: theme}),
      pushServiceProvider.overrideWithValue(NoopPushService()),
    ],
    child: const TwoKPilotApp(),
  )));
  await settle(tester, 15);
  return ProviderScope.containerOf(tester.element(find.byType(TwoKPilotApp)));
}

Future<void> go(WidgetTester tester, ProviderContainer c, String path) async {
  c.read(routerProvider).go(path);
  await settle(tester, 10);
}

Future<void> push(WidgetTester tester, ProviderContainer c, String path) async {
  c.read(routerProvider).push(path);
  await settle(tester, 10);
}

Future<void> finish(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox());
  await tester.pump(const Duration(seconds: 1));
}

void main() {
  setUpAll(() async {
    Intl.defaultLocale = 'en_US';
    await loadAppFonts();
  });

  for (final theme in ['dark', 'light']) {
    testWidgets('main screens render with demo data ($theme)', (tester) async {
      final c = await launch(tester, theme: theme);

      // Home
      expect(find.text('Stop trading'), findsOneWidget);
      expect(find.text('Bot running'), findsOneWidget);
      expect(find.textContaining(r'$10,482.35'), findsWidgets);
      expect(find.text('DEMO'), findsWidgets);
      await shot(tester, '01-home-$theme');
      await tester.drag(find.byType(ListView).first, const Offset(0, -900));
      await settle(tester, 5);
      expect(find.text('Active trades'), findsOneWidget);
      await shot(tester, '02-home-scrolled-$theme');
      await tester.drag(find.byType(ListView).first, const Offset(0, -900));
      await settle(tester, 5);
      await shot(tester, '03-home-chart-$theme');

      // Strategies
      await go(tester, c, '/strategies');
      expect(find.text('Adaptive Trend & Momentum'), findsWidgets);
      expect(find.text('Your strategies'), findsOneWidget);
      await shot(tester, '04-strategies-$theme');
      await go(tester, c, '/strategies?tab=templates');
      expect(find.text('Template library'), findsOneWidget);
      await shot(tester, '05-templates-$theme');
      await tester.tap(find.text('RSI reversal'));
      await settle(tester, 8);
      expect(find.text('Use this template'), findsOneWidget);
      await shot(tester, '06-template-sheet-$theme');
      await tester.tapAt(const Offset(200, 40));
      await settle(tester, 8);
      await go(tester, c, '/strategies?tab=backtests');
      expect(find.textContaining('Running 64%'), findsOneWidget);
      await shot(tester, '07-tests-$theme');
      await push(tester, c, '/strategies/backtests/bt-1');
      expect(find.text('Test report'), findsOneWidget);
      expect(find.text('Qualifies for demo forward testing'), findsWidgets);
      await shot(tester, '08-test-report-$theme');
      await tester.drag(find.byType(ListView).first, const Offset(0, -1100));
      await settle(tester, 5);
      await shot(tester, '09-test-report-charts-$theme');
      c.read(routerProvider).pop();
      await settle(tester, 6);

      // Activate (sheet)
      await go(tester, c, '/strategies?tab=mine');
      await tester.ensureVisible(find.text('Activate on another market').first);
      await settle(tester, 3);
      await tester.tap(find.text('Activate on another market').first);
      await settle(tester, 12);
      expect(find.text('Activate Adaptive Trend & Momentum'), findsOneWidget);
      expect(find.text('Rise/Fall'), findsWidgets);
      await shot(tester, '10-activate-$theme');
      await tester.tap(find.text('Cancel').last);
      await settle(tester, 8);

      // History
      await go(tester, c, '/history?tab=open');
      expect(find.text('Close all open trades…'), findsOneWidget);
      await shot(tester, '11-history-open-$theme');
      await go(tester, c, '/history?tab=closed');
      await settle(tester, 6);
      expect(find.textContaining('finished trade'), findsOneWidget);
      await shot(tester, '12-history-closed-$theme');
      await go(tester, c, '/history?tab=activity');
      await settle(tester, 6);
      await shot(tester, '13-history-activity-$theme');
      await push(tester, c, '/trades/t-open-2');
      expect(find.text('Close this trade…'), findsOneWidget);
      await shot(tester, '14-trade-detail-$theme');
      c.read(routerProvider).pop();
      await settle(tester, 6);

      // Settings
      await go(tester, c, '/settings');
      expect(find.text('Risk limits'), findsOneWidget);
      await shot(tester, '15-settings-$theme');
      for (final (path, label, name) in [
        ('/settings/accounts', 'Real-money (LIVE) trading', '16-accounts'),
        ('/settings/risk', 'Risk profiles', '17-risk'),
        ('/settings/notifications', 'Push notifications on this phone', '18-notifications'),
        ('/settings/security', 'Signed-in devices', '19-security'),
        ('/settings/system', 'Broker connections', '20-system'),
        ('/settings/brokers', 'Connect a broker on the website', '21-brokers'),
        ('/settings/about', 'Open-source licences', '22-about'),
      ]) {
        await push(tester, c, path);
        expect(find.text(label), findsWidgets, reason: path);
        await shot(tester, '$name-$theme');
        c.read(routerProvider).pop();
        await settle(tester, 6);
      }

      // Mode sheet
      await go(tester, c, '/home');
      await tester.tap(find.bySemanticsLabel(RegExp('Demo mode')));
      await settle(tester, 8);
      expect(find.text('Authorize real money on the website'), findsOneWidget);
      await shot(tester, '23-mode-sheet-$theme');
      await finish(tester);
    });
  }

  testWidgets('LIVE account: solid red banner and badge, one-tap Return to Demo', (tester) async {
    final c = await launch(tester, theme: 'dark', scenario: 'live');
    expect(find.text('LIVE ACCOUNT — REAL MONEY'), findsOneWidget);
    expect(find.text('LIVE'), findsWidgets);
    expect(find.text('Real money — every loss is real.'), findsOneWidget);
    await shot(tester, '24-home-live-dark');
    await tester.tap(find.bySemanticsLabel(RegExp('LIVE mode')));
    await settle(tester, 8);
    await shot(tester, '25-live-mode-sheet-dark');
    await tester.tap(find.byKey(const Key('return-to-demo')));
    await settle(tester, 10);
    expect(c.read(statusProvider).data!.tradingMode, 'DEMO');
    await finish(tester);
  });

  testWidgets('stopped: Start confirms in Demo', (tester) async {
    await launch(tester, theme: 'light', scenario: 'stopped');
    expect(find.text('Nothing will trade right now'), findsOneWidget);
    await tester.tap(find.byKey(const Key('start-trading')));
    await settle(tester, 8);
    expect(find.text('Start trading in Demo?'), findsOneWidget);
    await shot(tester, '26-start-dialog-light');
    await finish(tester);
  });

  testWidgets('sign-in screen', (tester) async {
    phoneSurface(tester);
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
    addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
    await tester.pumpWidget(RepaintBoundary(key: shotKey, child: ProviderScope(
      overrides: [
        httpAdapterProvider.overrideWithValue(MockAdapter((_) => const Reply(422, {'message': 'Email or password is incorrect.', 'code': 'invalid_credentials'}))),
        secureStoreProvider.overrideWithValue(MemorySecureStore({StoreKeys.pushAsked: '1'})),
      ],
      child: const TwoKPilotApp(),
    )));
    await settle(tester, 10);
    expect(find.text('Sign in'), findsWidgets);
    await tester.enterText(find.byKey(const Key('login-email')), 'amani@example.com');
    await tester.enterText(find.byKey(const Key('login-password')), 'wrong');
    await tester.tap(find.byKey(const Key('login-submit')));
    await settle(tester, 6);
    expect(find.text('Email or password is incorrect.'), findsOneWidget);
    await shot(tester, '00-sign-in-dark');
    await finish(tester);
  });
}
