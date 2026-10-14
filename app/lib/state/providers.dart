import 'dart:async';
import 'dart:io' show Platform;

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api/api_client.dart';
import '../core/auth/auth_controller.dart';
import '../core/auth/secure_store.dart';
import '../core/config.dart';
import '../core/models/models.dart';
import '../core/push/push_service.dart';
import '../core/trading_actions.dart';
import 'resource.dart';

// ── Infrastructure (overridden in tests and the debug demo mode) ─────────

final secureStoreProvider = Provider<SecureStore>((ref) => DeviceSecureStore());

/// Replaces the network (tests: a mock adapter; debug demo: canned data).
final httpAdapterProvider = Provider<HttpClientAdapter?>((ref) => null);

final pushServiceProvider = Provider<PushService>((ref) => NoopPushService());

final appVersionProvider = Provider<String>((ref) => '1.0.0');

final tokenHolderProvider = Provider<TokenHolder>((ref) => TokenHolder());

final Provider<ApiClient> apiClientProvider = Provider<ApiClient>((ref) {
  final tokens = ref.watch(tokenHolderProvider);
  final client = ApiClient(
    baseUrl: AppConfig.apiRoot,
    token: () => tokens.token,
    adapter: ref.watch(httpAdapterProvider),
    userAgent: '2kPilot-Mobile/${ref.watch(appVersionProvider)}',
  );
  client.onUnauthorized = () => ref.read(authProvider.notifier).handleUnauthorized();
  return client;
});

String defaultDeviceName() {
  try {
    if (Platform.isIOS) return '2kPilot app · iPhone';
    if (Platform.isAndroid) return '2kPilot app · Android';
  } catch (_) {}
  return '2kPilot app';
}

final deviceNameProvider = Provider<String>((ref) => defaultDeviceName());

final StateNotifierProvider<AuthController, AuthState> authProvider = StateNotifierProvider<AuthController, AuthState>((ref) {
  return AuthController(
    api: ref.watch(apiClientProvider),
    store: ref.watch(secureStoreProvider),
    tokens: ref.watch(tokenHolderProvider),
    deviceName: ref.watch(deviceNameProvider),
  );
});

/// The signed-in user's id ('' when signed out). Data providers watch it, so
/// everything is rebuilt for a new session and dropped on sign-out.
final sessionProvider = Provider<String>((ref) {
  final auth = ref.watch(authProvider);
  return auth is SignedIn ? (auth.user.id.isEmpty ? 'signed-in' : auth.user.id) : '';
});

final userProvider = Provider<User?>((ref) {
  final auth = ref.watch(authProvider);
  return auth is SignedIn ? auth.user : null;
});

final tradingActionsProvider = Provider<TradingActions>((ref) => TradingActions(ref.watch(apiClientProvider)));

/// Foreground (resumed/inactive) vs background: polling pauses in the background.
final appActiveProvider = StateProvider<bool>((ref) => true);

// ── Preferences ──────────────────────────────────────────────────────────

class ThemeModeController extends StateNotifier<ThemeMode> {
  ThemeModeController(this._store) : super(ThemeMode.system) {
    _store.read(StoreKeys.theme).then((v) {
      if (!mounted) return;
      state = switch (v) { 'light' => ThemeMode.light, 'dark' => ThemeMode.dark, _ => ThemeMode.system };
    });
  }
  final SecureStore _store;

  void set(ThemeMode mode) {
    state = mode;
    _store.write(StoreKeys.theme, mode == ThemeMode.system ? null : mode.name);
  }
}

final themeModeProvider = StateNotifierProvider<ThemeModeController, ThemeMode>((ref) => ThemeModeController(ref.watch(secureStoreProvider)));

class SelectedAccountController extends StateNotifier<String?> {
  SelectedAccountController(this._store) : super(null) {
    _store.read(StoreKeys.account).then((v) {
      if (mounted && state == null) state = v;
    });
  }
  final SecureStore _store;

  void select(String id) {
    state = id;
    _store.write(StoreKeys.account, id);
  }
}

final selectedAccountIdProvider = StateNotifierProvider<SelectedAccountController, String?>((ref) => SelectedAccountController(ref.watch(secureStoreProvider)));

// ── Resources ────────────────────────────────────────────────────────────

typedef ResourceProvider<T> = StateNotifierProvider<ResourceController<T>, Resource<T>>;
typedef ResourceFamily<T, A> = AutoDisposeStateNotifierProviderFamily<ResourceController<T>, Resource<T>, A>;

/// Wires a resource to the session and the app lifecycle. Signed out = idle.
ResourceController<T> resourceFor<T>(Ref ref, Future<T> Function(ApiClient api) fetch, {Duration? every}) {
  final signedIn = ref.watch(sessionProvider).isNotEmpty;
  final api = ref.watch(apiClientProvider);
  final controller = ResourceController<T>(() => fetch(api), interval: signedIn ? every : null, active: ref.read(appActiveProvider), autoload: signedIn);
  ref.listen<bool>(appActiveProvider, (_, active) {
    if (signedIn) controller.setActive(active);
  });
  return controller;
}

final statusProvider = ResourceProvider<TradingStatus>((ref) =>
    resourceFor(ref, (api) async => TradingStatus.fromJson(asJson(await api.get('/trading/status'))), every: const Duration(seconds: 5)));

final accountsProvider = ResourceProvider<List<Account>>((ref) =>
    resourceFor(ref, (api) async => asJsonList(await api.get('/accounts')).map(Account.fromJson).toList(), every: const Duration(seconds: 10)));

final unreadProvider = ResourceProvider<int>((ref) =>
    resourceFor(ref, (api) async => asJson(await api.get('/notifications/unread-count')).integer('count'), every: const Duration(seconds: 15)));

/// The account Home and History look at (remembered on this device).
final currentAccountProvider = Provider<Account?>((ref) {
  final list = ref.watch(accountsProvider.select((r) => r.data)) ?? const <Account>[];
  final id = ref.watch(selectedAccountIdProvider);
  if (list.isEmpty) return null;
  return list.where((a) => a.id == id).firstOrNull ?? list.first;
});

/// The status when it can be trusted; null while unknown (never a stale DEMO/LIVE).
final statusUnknownProvider = Provider<bool>((ref) => ref.watch(statusProvider.select((r) => r.stale)));

final offlineProvider = Provider<bool>((ref) {
  final status = ref.watch(statusProvider.select((r) => r.error));
  return status?.isNetwork ?? false;
});

final overviewProvider = StateNotifierProvider.autoDispose.family<ResourceController<Overview>, Resource<Overview>, String>((ref, accountId) =>
    resourceFor(ref, (api) async => Overview.fromJson(asJson(await api.get('/overview', query: {'account_id': accountId.isEmpty ? null : accountId}))),
        every: const Duration(seconds: 10)));

final strategiesProvider = StateNotifierProvider.autoDispose<ResourceController<List<Strategy>>, Resource<List<Strategy>>>((ref) =>
    resourceFor(ref, (api) async => asJsonList(await api.get('/strategies')).map(Strategy.fromJson).toList(), every: const Duration(seconds: 20)));

final riskProfilesProvider = StateNotifierProvider.autoDispose<ResourceController<List<RiskProfile>>, Resource<List<RiskProfile>>>((ref) =>
    resourceFor(ref, (api) async => asJsonList(await api.get('/risk/profiles')).map(RiskProfile.fromJson).toList()));

final positionsProvider = StateNotifierProvider.autoDispose.family<ResourceController<List<Trade>>, Resource<List<Trade>>, String>((ref, accountId) =>
    resourceFor(ref, (api) async => asJsonList(await api.get('/positions', query: {'account_id': accountId})).map(Trade.fromJson).toList(),
        every: const Duration(seconds: 5)));

final tradeChainProvider = StateNotifierProvider.autoDispose.family<ResourceController<TradeChain>, Resource<TradeChain>, String>((ref, id) =>
    resourceFor(ref, (api) async => TradeChain.fromJson(asJson(await api.get('/trades/$id'))), every: const Duration(seconds: 10)));

final backtestsProvider = StateNotifierProvider.autoDispose<ResourceController<List<Backtest>>, Resource<List<Backtest>>>((ref) =>
    resourceFor(ref, (api) async => asJsonList(await api.get('/backtests')).map(Backtest.fromJson).toList(), every: const Duration(seconds: 5)));

final backtestProvider = StateNotifierProvider.autoDispose.family<ResourceController<Backtest>, Resource<Backtest>, String>((ref, id) =>
    resourceFor(ref, (api) async => Backtest.fromJson(asJson(await api.get('/backtests/$id'))), every: const Duration(seconds: 3)));

final backtestTradesProvider = StateNotifierProvider.autoDispose.family<ResourceController<List<BacktestTrade>>, Resource<List<BacktestTrade>>, String>((ref, id) =>
    resourceFor(ref, (api) async => asJsonList(await api.get('/backtests/$id/trades')).map(BacktestTrade.fromJson).toList()));

typedef EvaluationsData = ({List<Evaluation> evaluations, List<Signal> signals});

final evaluationsProvider = StateNotifierProvider.autoDispose.family<ResourceController<EvaluationsData>, Resource<EvaluationsData>, (String, int)>((ref, arg) =>
    resourceFor(ref, (api) async {
      final j = asJson(await api.get('/assignments/${arg.$1}/evaluations', query: {'per_page': arg.$2}));
      return (
        evaluations: Paginated.fromJson(j['evaluations'], Evaluation.fromJson).data,
        signals: j.objList('signals').map(Signal.fromJson).toList(),
      );
    }, every: const Duration(seconds: 30)));

final notificationsProvider = StateNotifierProvider.autoDispose.family<ResourceController<Paginated<AppNotification>>, Resource<Paginated<AppNotification>>, String>((ref, filter) =>
    resourceFor(ref, (api) async => Paginated.fromJson(await api.get('/notifications', query: {
          'unread': filter == 'unread' ? 1 : null,
          'severity': filter == 'critical' ? 'critical' : null,
          'per_page': 100,
        }), AppNotification.fromJson), every: const Duration(seconds: 15)));

final systemStatusProvider = StateNotifierProvider.autoDispose<ResourceController<SystemStatus>, Resource<SystemStatus>>((ref) =>
    resourceFor(ref, (api) async => SystemStatus.fromJson(asJson(await api.get('/system/status'))), every: const Duration(seconds: 15)));

final riskUsageProvider = StateNotifierProvider.autoDispose.family<ResourceController<RiskUsage>, Resource<RiskUsage>, String>((ref, accountId) =>
    resourceFor(ref, (api) async => RiskUsage.fromJson(asJson(await api.get('/risk/usage/$accountId'))), every: const Duration(seconds: 15)));

final devicesProvider = StateNotifierProvider.autoDispose<ResourceController<List<DeviceToken>>, Resource<List<DeviceToken>>>((ref) =>
    resourceFor(ref, (api) async => asJsonList(await api.get('/auth/tokens')).map(DeviceToken.fromJson).toList()));

/// Refresh the live data now (pull-to-refresh, a push arrived, app resumed).
Future<void> refreshCore(WidgetRef ref) async {
  await Future.wait([
    ref.read(statusProvider.notifier).load(),
    ref.read(accountsProvider.notifier).load(),
    ref.read(unreadProvider.notifier).load(),
  ]);
}
