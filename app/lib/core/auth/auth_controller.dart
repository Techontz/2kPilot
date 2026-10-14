import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../models/models.dart';
import 'secure_store.dart';

sealed class AuthState {
  const AuthState();
}

/// Reading the stored token at start-up.
class AuthRestoring extends AuthState {
  const AuthRestoring();
}

class SignedOut extends AuthState {
  const SignedOut({this.message});

  /// Why the user is here (e.g. the session ended), shown on the sign-in screen.
  final String? message;
}

/// Password accepted; waiting for the two-factor code.
class MfaPending extends AuthState {
  const MfaPending({required this.mfaToken, required this.email});
  final String mfaToken;
  final String email;
}

class SignedIn extends AuthState {
  const SignedIn(this.user);
  final User user;
}

/// The bearer token currently in use (memory copy of the secure store).
class TokenHolder {
  String? token;
}

/// Sign-in result for the login form.
enum LoginOutcome { signedIn, mfaRequired }

/// Native sign-in against the mobile token endpoints:
/// POST /api/mobile/auth/login → token, or {mfa_required, mfa_token} → POST /api/mobile/auth/mfa.
class AuthController extends StateNotifier<AuthState> {
  AuthController({required this.api, required this.store, required this.tokens, required this.deviceName}) : super(const AuthRestoring());

  final ApiClient api;
  final SecureStore store;
  final TokenHolder tokens;
  final String deviceName;

  /// Runs before the token is revoked on sign-out (push unregistration).
  Future<void> Function()? beforeSignOut;

  Future<void> restore() async {
    final token = await store.read(StoreKeys.token);
    if (token == null || token.isEmpty) {
      state = const SignedOut();
      return;
    }
    tokens.token = token;
    User? user;
    final cached = await store.read(StoreKeys.user);
    if (cached != null) {
      try {
        user = User.fromJson(asJson(jsonDecode(cached)));
      } catch (_) {}
    }
    if (user != null) {
      state = SignedIn(user);
      refreshUser(); // in the background; a 401 signs out via the API client
      return;
    }
    try {
      final me = asJson(await api.get('/auth/me'));
      await _signedIn(token, User.fromJson(me.obj('user') ?? me));
    } on ApiException catch (e) {
      if (e.status == 401) {
        await _clear();
        state = const SignedOut(message: 'Your session ended. Sign in again.');
      } else {
        // Offline at start-up: keep the token, show what we can.
        state = SignedIn(const User(id: '', name: '', email: '', role: 'user', mfaEnabled: false, mfaRequired: false));
      }
    }
  }

  Future<void> refreshUser() async {
    try {
      final me = asJson(await api.get('/auth/me'));
      final user = User.fromJson(me.obj('user') ?? me);
      if (state is SignedIn) {
        state = SignedIn(user);
        await store.write(StoreKeys.user, jsonEncode(user.toJson()));
      }
    } on ApiException {
      // 401 is handled by the API client; anything else keeps the cached user.
    }
  }

  Future<LoginOutcome> login(String email, String password) async {
    final res = asJson(await api.post('/mobile/auth/login', body: {'email': email.trim(), 'password': password, 'device_name': deviceName}));
    if (res.boolean('mfa_required')) {
      state = MfaPending(mfaToken: res.str('mfa_token'), email: email.trim());
      return LoginOutcome.mfaRequired;
    }
    await _complete(res);
    return LoginOutcome.signedIn;
  }

  Future<void> verifyMfa(String code) async {
    final pending = state;
    if (pending is! MfaPending) throw const ApiException(422, 'mfa_expired', 'Your sign-in expired. Enter your password again.');
    try {
      final res = asJson(await api.post('/mobile/auth/mfa', body: {'mfa_token': pending.mfaToken, 'code': code.replaceAll(' ', '').trim()}));
      await _complete(res);
    } on ApiException catch (e) {
      if (e.code == 'mfa_expired' || e.code == 'mfa_locked') state = SignedOut(message: e.message);
      rethrow;
    }
  }

  void cancelMfa() => state = const SignedOut();

  Future<void> _complete(Json res) async {
    final token = res.str('token');
    if (token.isEmpty) throw const ApiException(500, 'invalid_response', 'The server did not return a sign-in token.');
    await _signedIn(token, User.fromJson(res.obj('user') ?? const {}));
  }

  Future<void> _signedIn(String token, User user) async {
    tokens.token = token;
    await store.write(StoreKeys.token, token);
    await store.write(StoreKeys.user, jsonEncode(user.toJson()));
    state = SignedIn(user);
  }

  /// Sign this device out: unregister push, revoke the token, forget it.
  Future<void> signOut() async {
    try {
      await beforeSignOut?.call();
    } catch (_) {}
    try {
      await api.post('/mobile/auth/logout');
    } catch (_) {
      // Offline or already revoked: the local token is forgotten either way.
    }
    await _clear();
    state = const SignedOut();
  }

  /// A 401: the token expired or was revoked (e.g. from another device).
  Future<void> handleUnauthorized() async {
    if (state is SignedOut || state is MfaPending) return;
    await _clear();
    state = const SignedOut(message: 'Your session ended. Sign in again.');
  }

  Future<void> _clear() async {
    tokens.token = null;
    await store.write(StoreKeys.token, null);
    await store.write(StoreKeys.user, null);
  }
}
