import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:twokpilot/core/api/api_client.dart';
import 'package:twokpilot/core/trading_actions.dart';
import 'package:twokpilot/features/shell/trading_control.dart';
import 'package:twokpilot/state/providers.dart';
import 'package:twokpilot/ui/theme.dart';
import 'package:twokpilot/ui/widgets/states.dart';

import 'helpers.dart';

/// Status is served from [state]; stop/resume/mode mutate it like the server.
MockAdapter fakeServer(Map<String, Object?> state, {bool requireLiveFlag = true, int stopFailures = 0}) {
  var failures = stopFailures;
  return MockAdapter((call) {
    switch ('${call.method} ${call.path}') {
      case 'GET /trading/status':
        return Reply(200, state);
      case 'POST /trading/stop':
        if (failures > 0) {
          failures--;
          return const Reply(429, {'message': 'Too many requests'}, headers: {'retry-after': ['1']});
        }
        state['kill_switch_engaged'] = true;
        return Reply(200, state);
      case 'POST /trading/resume':
        if (requireLiveFlag && state['trading_mode'] == 'LIVE' && call.json['live'] != true) {
          return const Reply(422, {'message': 'Confirm LIVE.', 'code': 'live_confirmation_required'});
        }
        state['kill_switch_engaged'] = false;
        return Reply(200, state);
      case 'PUT /trading/mode':
        if (state['kill_switch_engaged'] != true) return const Reply(409, {'message': 'Stop first', 'code': 'stop_first'});
        state['trading_mode'] = call.json['mode'];
        return Reply(200, state);
    }
    return const Reply(200, <String, Object>{});
  });
}

Widget host(ProviderContainer c, Widget child) => UncontrolledProviderScope(
      container: c,
      child: MaterialApp(theme: buildTheme(Brightness.dark), home: Scaffold(body: Center(child: child))),
    );

void main() {
  testApp('Stop is one tap: no confirmation, POST /trading/stop at once', (tester) async {
    final state = tradingStatus(kill: false);
    final adapter = fakeServer(state);
    final c = makeContainer(adapter);
    addTearDown(c.dispose);
    await c.read(authProvider.notifier).restore();
    await tester.pumpWidget(host(c, const BigTradingButton()));
    await settle(tester, 3);
    expect(find.text('Stop trading'), findsOneWidget);
    await tester.tap(find.byKey(const Key('stop-trading')));
    await settle(tester, 3);
    expect(find.byType(AlertDialog), findsNothing, reason: 'Stop is never confirmed');
    expect(adapter.named('POST', '/trading/stop'), hasLength(1));
    expect(find.text('Start trading'), findsOneWidget);
  });

  testApp('Start in DEMO confirms with Demo wording and sends live:false', (tester) async {
    final state = tradingStatus(kill: true);
    final adapter = fakeServer(state);
    final c = makeContainer(adapter);
    addTearDown(c.dispose);
    await c.read(authProvider.notifier).restore();
    await tester.pumpWidget(host(c, const BigTradingButton()));
    await settle(tester, 3);
    await tester.tap(find.byKey(const Key('start-trading')));
    await settle(tester, 3);
    expect(find.text('Start trading in Demo?'), findsOneWidget);
    expect(adapter.named('POST', '/trading/resume'), isEmpty, reason: 'nothing starts before the confirmation');
    await tester.tap(find.byKey(const Key('confirm-start')));
    await settle(tester, 3);
    expect(adapter.named('POST', '/trading/resume').single.json, {'confirm': true, 'live': false});
    expect(find.byType(AlertDialog), findsNothing);
  });

  testApp('Start in LIVE shows the real-money wording and sends live:true', (tester) async {
    final state = tradingStatus(mode: 'LIVE', kill: true);
    final adapter = fakeServer(state);
    final c = makeContainer(adapter);
    addTearDown(c.dispose);
    await c.read(authProvider.notifier).restore();
    await tester.pumpWidget(host(c, const BigTradingButton()));
    await settle(tester, 3);
    await tester.tap(find.byKey(const Key('start-trading')));
    await settle(tester, 3);
    expect(find.text('Start trading with REAL money?'), findsOneWidget);
    expect(find.text('Start with real money'), findsOneWidget);
    await tester.tap(find.byKey(const Key('confirm-start')));
    await settle(tester, 3);
    expect(adapter.named('POST', '/trading/resume').single.json, {'confirm': true, 'live': true});
  });

  testApp('live_confirmation_required: the dialog switches to LIVE wording and asks again', (tester) async {
    final state = tradingStatus(mode: 'DEMO', kill: true);
    final adapter = fakeServer(state);
    final c = makeContainer(adapter);
    addTearDown(c.dispose);
    await c.read(authProvider.notifier).restore();
    await tester.pumpWidget(host(c, const BigTradingButton()));
    await settle(tester, 3);
    await tester.tap(find.byKey(const Key('start-trading')));
    await settle(tester, 3);
    expect(find.text('Start trading in Demo?'), findsOneWidget);
    state['trading_mode'] = 'LIVE'; // changed elsewhere while the dialog was open
    await tester.tap(find.byKey(const Key('confirm-start')));
    await settle(tester, 3);
    expect(find.text('Start trading with REAL money?'), findsOneWidget);
    expect(find.textContaining('this would use REAL money'), findsOneWidget);
    expect(state['kill_switch_engaged'], isTrue, reason: 'nothing started');
    await tester.tap(find.byKey(const Key('confirm-start')));
    await settle(tester, 3);
    expect(adapter.named('POST', '/trading/resume').last.json['live'], isTrue);
    expect(state['kill_switch_engaged'], isFalse);
  });

  testApp('live_requires_web on Start: explained, with a website button', (tester) async {
    final adapter = MockAdapter((call) => call.path == '/trading/resume'
        ? const Reply(403, {'message': 'Real money is authorised on the website.', 'code': 'live_requires_web'})
        : Reply(200, tradingStatus(mode: 'LIVE', kill: true)));
    final c = makeContainer(adapter);
    addTearDown(c.dispose);
    await c.read(authProvider.notifier).restore();
    await tester.pumpWidget(host(c, const BigTradingButton()));
    await settle(tester, 3);
    await tester.tap(find.byKey(const Key('start-trading')));
    await settle(tester, 3);
    await tester.tap(find.byKey(const Key('confirm-start')));
    await settle(tester, 3);
    expect(find.text('Do this on the 2kPilot website'), findsOneWidget);
    expect(find.text('Open the website'), findsOneWidget);
  });

  testApp('ErrorView turns web-only refusals into "Do this on the website"', (tester) async {
    final c = makeContainer(MockAdapter((_) => const Reply(200, {})));
    addTearDown(c.dispose);
    await tester.pumpWidget(host(c, const ErrorView(error: ApiException(403, 'web_only', 'Two-factor set-up is on the website.'))));
    expect(find.text('Do this on the 2kPilot website'), findsOneWidget);
    expect(find.text('Open the website'), findsOneWidget);
    await tester.pumpWidget(host(c, const ErrorView(error: ApiException(0, 'network_error', 'Cannot reach the 2kPilot server.')) ));
    expect(find.text("You're offline"), findsOneWidget);
  });

  group('trading actions', () {
    test('Return to Demo stops first when the server says stop_first', () async {
      final state = tradingStatus(mode: 'LIVE', kill: false);
      final adapter = fakeServer(state);
      final c = makeContainer(adapter);
      addTearDown(c.dispose);
      final status = await c.read(tradingActionsProvider).returnToDemo();
      expect(status.tradingMode, 'DEMO');
      expect(adapter.calls.map((x) => x.toString()), ['PUT /trading/mode', 'POST /trading/stop', 'PUT /trading/mode']);
    });

    test('Stop retries through 429 using Retry-After', () async {
      final state = tradingStatus(kill: false);
      final adapter = fakeServer(state, stopFailures: 2);
      final c = makeContainer(adapter);
      addTearDown(c.dispose);
      final waits = <Duration>[];
      final actions = TradingActions(c.read(apiClientProvider), sleep: (d) async => waits.add(d));
      final status = await actions.stop();
      expect(status.killSwitchEngaged, isTrue);
      expect(adapter.named('POST', '/trading/stop'), hasLength(3));
      expect(waits, [const Duration(seconds: 1), const Duration(seconds: 1)]);
    });

    test('withRetry gives up on other errors immediately', () async {
      var calls = 0;
      await expectLater(
        withRetry(() async {
          calls++;
          throw const ApiException(500, 'boom', 'x');
        }, sleep: (_) async {}),
        throwsA(isA<ApiException>()),
      );
      expect(calls, 1);
    });
  });
}
