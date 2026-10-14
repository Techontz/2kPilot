import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:twokpilot/core/auth/secure_store.dart';
import 'package:twokpilot/core/push/push_service.dart';
import 'package:twokpilot/state/providers.dart';
import 'package:twokpilot/state/push_registrar.dart';

import 'helpers.dart';

class FakePush implements PushService {
  final refresh = StreamController<String>.broadcast();
  PushPermission answer = PushPermission.granted;
  String? tokenValue = 'fcm-1';

  @override
  bool get available => true;
  @override
  String? get unavailableReason => null;
  @override
  Future<PushPermission> permission() async => answer;
  @override
  Future<PushPermission> requestPermission() async => answer;
  @override
  Future<String?> token() async => tokenValue;
  @override
  Stream<String> get tokenRefresh => refresh.stream;
  @override
  Stream<PushTap> get taps => const Stream.empty();
  @override
  Stream<Map<String, String>> get foregroundMessages => const Stream.empty();
  @override
  PushTap? takeLaunchTap() => null;
}

void main() {
  test('without Firebase config, createPushService returns a no-op service', () async {
    final push = await createPushService(initializeFirebase: () async => throw Exception('No GoogleService-Info.plist'));
    expect(push, isA<NoopPushService>());
    expect(push.available, isFalse);
    expect(push.unavailableReason, contains('Firebase'));
    expect(await push.requestPermission(), PushPermission.unavailable);
    expect(await push.token(), isNull);
  });

  test('a failing push set-up after Firebase starts also degrades to no-op', () async {
    final push = await createPushService(initializeFirebase: () async {}, create: () async => throw StateError('plugin'));
    expect(push, isA<NoopPushService>());
  });

  test('the registrar with no-op push never calls the backend', () async {
    final adapter = MockAdapter((_) => const Reply(200, {'ok': true}));
    final c = makeContainer(adapter);
    addTearDown(c.dispose);
    final reg = c.read(pushRegistrarProvider.notifier);
    await reg.ready;
    expect(c.read(pushRegistrarProvider).available, isFalse);
    expect(c.read(pushRegistrarProvider).asked, isTrue, reason: 'no explainer when push is unavailable');
    expect(await reg.enable(), isFalse);
    await reg.syncAfterSignIn();
    await reg.unregister();
    expect(adapter.calls, isEmpty);
  });

  test('enable registers the FCM token; token refresh re-registers; sign-out unregisters', () async {
    final adapter = MockAdapter((_) => const Reply(200, {'ok': true}));
    final push = FakePush();
    final store = MemorySecureStore({StoreKeys.token: 't', StoreKeys.user: '{"id":"u-1"}'});
    final c = makeContainer(adapter, push: push, store: store);
    addTearDown(c.dispose);
    final reg = c.read(pushRegistrarProvider.notifier);
    await reg.ready;
    expect(c.read(pushRegistrarProvider).asked, isFalse, reason: 'the explainer is due');
    expect(await reg.enable(), isTrue);
    final post = adapter.named('POST', '/mobile/devices').single.json;
    expect(post['fcm_token'], 'fcm-1');
    expect(post['platform'], anyOf('ios', 'android'));
    expect(post.containsKey('app_version'), isTrue);
    expect(store.values[StoreKeys.pushEnabled], '1');

    push.refresh.add('fcm-2');
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(adapter.named('POST', '/mobile/devices').last.json['fcm_token'], 'fcm-2');

    c.read(authProvider.notifier).beforeSignOut = () => reg.unregister();
    await c.read(authProvider.notifier).restore();
    await c.read(authProvider.notifier).signOut();
    final del = adapter.named('DELETE', '/mobile/devices');
    expect(del.single.json, {'fcm_token': 'fcm-2'});
    expect(adapter.calls.map((x) => x.toString()).toList().indexOf('DELETE /mobile/devices'), lessThan(adapter.calls.map((x) => x.toString()).toList().indexOf('POST /mobile/auth/logout')),
        reason: 'unregister while the token is still valid');
  });

  test('denied permission: push stays off with an explanation', () async {
    final adapter = MockAdapter((_) => const Reply(200, {'ok': true}));
    final push = FakePush()..answer = PushPermission.denied;
    final c = makeContainer(adapter, push: push);
    addTearDown(c.dispose);
    final reg = c.read(pushRegistrarProvider.notifier);
    await reg.ready;
    expect(await reg.enable(), isFalse);
    expect(c.read(pushRegistrarProvider).error, contains('blocked'));
    expect(adapter.calls, isEmpty);
  });

  test('notification taps route to the trade, else to notifications', () {
    expect(const PushTap({'trade_id': 't-9', 'type': 'trade.closed'}).route, '/trades/t-9');
    expect(const PushTap({'type': 'broker.disconnected'}).route, '/settings/notifications');
  });
}
