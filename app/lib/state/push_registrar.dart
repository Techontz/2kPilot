import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api/api_client.dart';
import '../core/auth/secure_store.dart';
import '../core/push/push_service.dart';
import 'providers.dart';

class PushState {
  const PushState({required this.available, this.reason, required this.enabled, required this.asked, this.permission = PushPermission.notDetermined, this.busy = false, this.error});
  final bool available;
  final String? reason;
  final bool enabled;

  /// The pre-permission explainer was shown (or answered) on this device.
  final bool asked;
  final PushPermission permission;
  final bool busy;
  final String? error;

  PushState copyWith({bool? enabled, bool? asked, PushPermission? permission, bool? busy, String? Function()? error}) => PushState(
        available: available,
        reason: reason,
        enabled: enabled ?? this.enabled,
        asked: asked ?? this.asked,
        permission: permission ?? this.permission,
        busy: busy ?? this.busy,
        error: error != null ? error() : this.error,
      );
}

/// Registers this device's FCM token with the backend
/// (POST/DELETE /api/mobile/devices) and keeps it current.
class PushRegistrar extends StateNotifier<PushState> {
  PushRegistrar({required this.push, required this.api, required this.store, required this.appVersion})
      : super(PushState(available: push.available, reason: push.unavailableReason, enabled: false, asked: !push.available)) {
    _load();
  }

  final PushService push;
  final ApiClient api;
  final SecureStore store;
  final String appVersion;
  StreamSubscription<String>? _refresh;
  final Completer<void> _ready = Completer<void>();

  Future<void> get ready => _ready.future;

  Future<void> _load() async {
    final asked = await store.read(StoreKeys.pushAsked) == '1';
    final enabled = await store.read(StoreKeys.pushEnabled) == '1';
    if (mounted) state = state.copyWith(asked: asked || !push.available, enabled: enabled && push.available);
    if (!_ready.isCompleted) _ready.complete();
    if (push.available) {
      _refresh = push.tokenRefresh.listen((token) {
        if (state.enabled) _register(token);
      });
    }
  }

  static String get platform {
    try {
      return Platform.isIOS ? 'ios' : 'android';
    } catch (_) {
      return 'android';
    }
  }

  Future<void> _register(String token) async {
    await api.post('/mobile/devices', body: {'fcm_token': token, 'platform': platform, 'app_version': appVersion});
    await store.write(StoreKeys.pushToken, token);
  }

  /// After sign-in: register again if push was on (the token may have changed).
  Future<void> syncAfterSignIn() async {
    await ready;
    if (!push.available || !state.enabled) return;
    try {
      if (await push.permission() != PushPermission.granted) return;
      final token = await push.token();
      if (token != null) await _register(token);
    } catch (_) {}
  }

  /// "Not now" on the explainer screen.
  Future<void> dismissExplainer() async {
    await store.write(StoreKeys.pushAsked, '1');
    if (mounted) state = state.copyWith(asked: true);
  }

  /// Ask for permission and register. Returns true when push is on.
  Future<bool> enable() async {
    if (!push.available) return false;
    state = state.copyWith(busy: true, error: () => null);
    await store.write(StoreKeys.pushAsked, '1');
    try {
      final permission = await push.requestPermission();
      if (permission != PushPermission.granted) {
        state = state.copyWith(busy: false, asked: true, permission: permission, enabled: false,
            error: () => 'Notifications are blocked for 2kPilot. Allow them in your phone’s Settings, then try again.');
        return false;
      }
      final token = await push.token();
      if (token == null) throw const ApiException(0, 'no_token', 'Could not get a push token from this device.');
      await _register(token);
      await store.write(StoreKeys.pushEnabled, '1');
      state = state.copyWith(busy: false, asked: true, permission: permission, enabled: true);
      return true;
    } on ApiException catch (e) {
      state = state.copyWith(busy: false, asked: true, error: () => e.message);
      return false;
    } catch (_) {
      state = state.copyWith(busy: false, asked: true, error: () => 'Push notifications could not be turned on.');
      return false;
    }
  }

  /// Stop pushes to this device (the in-app list keeps everything).
  Future<void> disable() async {
    state = state.copyWith(busy: true, error: () => null);
    try {
      await unregister();
      await store.write(StoreKeys.pushEnabled, null);
      state = state.copyWith(busy: false, enabled: false);
    } on ApiException catch (e) {
      state = state.copyWith(busy: false, error: () => e.message);
    }
  }

  /// Before sign-out: this device should stop receiving the user's alerts.
  Future<void> unregister() async {
    final token = await store.read(StoreKeys.pushToken);
    if (token == null) return;
    await api.delete('/mobile/devices', body: {'fcm_token': token});
    await store.write(StoreKeys.pushToken, null);
  }

  @override
  void dispose() {
    _refresh?.cancel();
    super.dispose();
  }
}

final pushRegistrarProvider = StateNotifierProvider<PushRegistrar, PushState>((ref) => PushRegistrar(
      push: ref.watch(pushServiceProvider),
      api: ref.watch(apiClientProvider),
      store: ref.watch(secureStoreProvider),
      appVersion: ref.watch(appVersionProvider),
    ));
