import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:twokpilot/core/auth/secure_store.dart';
import 'package:twokpilot/core/push/push_service.dart';
import 'package:twokpilot/state/providers.dart';

/// A recorded request.
class Call {
  Call(this.method, this.path, this.body, this.headers, this.query);
  final String method;
  final String path;
  final Object? body;
  final Map<String, dynamic> headers;
  final Map<String, dynamic> query;

  Map<String, dynamic> get json => body is Map ? Map<String, dynamic>.from(body as Map) : const {};

  @override
  String toString() => '$method $path';
}

class Reply {
  const Reply(this.status, this.body, {this.headers = const {}});
  final int status;
  final Object? body;
  final Map<String, List<String>> headers;
}

/// A mocked dio adapter: answers from [handler] and records every call.
class MockAdapter implements HttpClientAdapter {
  MockAdapter(this.handler);
  Reply Function(Call call) handler;
  final calls = <Call>[];

  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async {
    var path = options.uri.path;
    final root = Uri.parse(options.baseUrl).path;
    if (path.startsWith(root)) path = path.substring(root.length);
    final call = Call(options.method, path, options.data, options.headers, options.uri.queryParameters);
    calls.add(call);
    final reply = handler(call);
    return ResponseBody.fromString(jsonEncode(reply.body), reply.status, headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
      ...reply.headers,
    });
  }

  @override
  void close({bool force = false}) {}

  List<Call> named(String method, String path) => calls.where((c) => c.method == method && c.path == path).toList();
}

Map<String, Object?> tradingStatus({
  String mode = 'DEMO',
  bool kill = false,
  bool locked = false,
  bool halted = false,
  String engine = 'running',
  Map<String, Object?>? summary,
}) =>
    {
      'trading_mode': mode,
      'kill_switch_engaged': kill,
      'kill_switch_reason': null,
      'live_trading_locked': locked,
      'platform_halted': halted,
      'platform_halt_reason': null,
      'engine_state': engine,
      'engine_detail': 'ok',
      'new_orders_permitted': true,
      'engine_summary': ?summary,
    };

const userJson = {'id': 'u-1', 'name': 'Test User', 'email': 'test@example.com', 'role': 'user', 'mfa_enabled': true, 'mfa_required': false};

/// A container whose network is [adapter], signed in when [signedIn].
ProviderContainer makeContainer(HttpClientAdapter adapter, {bool signedIn = true, MemorySecureStore? store, PushService? push}) {
  final s = store ??
      MemorySecureStore(signedIn
          ? {StoreKeys.token: 'tok-123', StoreKeys.user: jsonEncode(userJson), StoreKeys.pushAsked: '1'}
          : {StoreKeys.pushAsked: '1'});
  final container = ProviderContainer(overrides: [
    httpAdapterProvider.overrideWithValue(adapter),
    secureStoreProvider.overrideWithValue(s),
    pushServiceProvider.overrideWithValue(push ?? NoopPushService()),
  ]);
  _live.add(container);
  return container;
}

final _live = <ProviderContainer>[];

/// testWidgets that disposes the containers it made before the pending-timer
/// check (polling timers live in the providers).
void testApp(String description, Future<void> Function(WidgetTester tester) body) {
  testWidgets(description, (tester) async {
    try {
      await body(tester);
    } finally {
      await tester.pumpWidget(const SizedBox());
      for (final c in _live) {
        c.dispose();
      }
      _live.clear();
      await tester.pump(const Duration(seconds: 1));
    }
  });
}

bool _fontsLoaded = false;

/// Real fonts (Figtree + Material icons) so golden screenshots look like the app.
Future<void> loadAppFonts() async {
  if (_fontsLoaded) return;
  _fontsLoaded = true;
  final figtree = FontLoader('Figtree');
  for (final w in ['Regular', 'Medium', 'SemiBold', 'Bold', 'ExtraBold', 'Black']) {
    figtree.addFont(Future.value(ByteData.sublistView(File('assets/fonts/Figtree-$w.ttf').readAsBytesSync())));
  }
  await figtree.load();
  final root = Platform.environment['FLUTTER_ROOT'] ?? '/Users/conradbuberwa/development/flutter';
  final icons = File('$root/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf');
  if (icons.existsSync()) {
    final loader = FontLoader('MaterialIcons')..addFont(Future.value(ByteData.sublistView(icons.readAsBytesSync())));
    await loader.load();
  }
}

/// iPhone-sized test surface.
void phoneSurface(WidgetTester tester, {double dpr = 3}) {
  tester.view.physicalSize = Size(390 * dpr, 844 * dpr);
  tester.view.devicePixelRatio = dpr;
  addTearDown(tester.view.reset);
}

Future<void> settle(WidgetTester tester, [int frames = 12]) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}
