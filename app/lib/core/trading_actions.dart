/// The trading controls' requests, ported from the web's lib/tradingActions.ts.
/// Each returns the full trading status the server answers with.
library;

import 'dart:math';

import 'api/api_client.dart';
import 'models/models.dart';

typedef Sleep = Future<void> Function(Duration);

Future<void> _wait(Duration d) => Future<void>.delayed(d);

/// Run a request that must get through (STOP TRADING): a 429 waits for
/// Retry-After and tries again, a network failure is retried. Anything else —
/// or running out of tries — throws the last error.
Future<T> withRetry<T>(
  Future<T> Function() call, {
  int maxRetries = 3,
  Duration fallbackDelay = const Duration(seconds: 1),
  Duration maxDelay = const Duration(seconds: 10),
  Sleep sleep = _wait,
}) async {
  var retries = 0;
  while (true) {
    try {
      return await call();
    } on ApiException catch (e) {
      if ((e.status == 429 || e.status == 0) && retries < maxRetries) {
        retries++;
        final ms = e.retryAfter != null ? e.retryAfter! * 1000 : fallbackDelay.inMilliseconds;
        await sleep(Duration(milliseconds: min(maxDelay.inMilliseconds, max(250, ms))));
        continue;
      }
      rethrow;
    }
  }
}

class TradingActions {
  const TradingActions(this.api, {this.sleep = _wait});
  final ApiClient api;
  final Sleep sleep;

  /// STOP TRADING — always allowed, never confirmed, retried until it gets through.
  Future<TradingStatus> stop([String reason = 'Stopped from the mobile app']) =>
      withRetry(() async => TradingStatus.fromJson(asJson(await api.post('/trading/stop', body: {'reason': reason}))), sleep: sleep);

  /// Start trading. [live] says the user confirmed the LIVE (real-money)
  /// wording; the server refuses LIVE without it (`live_confirmation_required`).
  Future<TradingStatus> resume({required bool live}) async =>
      TradingStatus.fromJson(asJson(await api.post('/trading/resume', body: {'confirm': true, 'live': live})));

  /// Leave LIVE in one tap. The mode can only change while trading is stopped,
  /// so this stops trading first when needed (always safe), then switches to DEMO.
  Future<TradingStatus> returnToDemo() async {
    Future<TradingStatus> toDemo() async => TradingStatus.fromJson(asJson(await api.put('/trading/mode', body: {'mode': 'DEMO'})));
    try {
      return await toDemo();
    } on ApiException catch (e) {
      if (e.code != 'stop_first') rethrow;
      await stop('Returning to Demo');
      return toDemo();
    }
  }

  /// Stops trading, then closes every open trade on all the user's accounts.
  Future<({int closed, int failed, TradingStatus? status})> closeAll(String reason) async {
    final res = asJson(await api.post('/trading/close-positions', body: {'confirm': true, 'reason': reason}));
    final failed = res['failed'] is List ? (res['failed'] as List).length : 0;
    return (closed: res.integer('closed'), failed: failed, status: res.obj('status') == null ? null : TradingStatus.fromJson(res.obj('status')!));
  }

  /// Close one open position at the market price.
  Future<Json> closePosition(String tradeId) async => asJson(await api.post('/positions/$tradeId/close', body: {'confirm': true}));
}
