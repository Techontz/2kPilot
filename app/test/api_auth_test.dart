import 'package:flutter_test/flutter_test.dart';
import 'package:twokpilot/core/api/api_client.dart';
import 'package:twokpilot/core/auth/auth_controller.dart';
import 'package:twokpilot/core/auth/secure_store.dart';
import 'package:twokpilot/core/models/models.dart';
import 'package:twokpilot/router.dart';
import 'package:twokpilot/state/providers.dart';

import 'helpers.dart';

const _ok = {'token': 'new-token', 'token_type': 'Bearer', 'expires_at': '2026-11-10T00:00:00Z', 'user': userJson};

void main() {
  group('API client', () {
    test('sends the bearer token and JSON headers, never a cookie/CSRF', () async {
      final adapter = MockAdapter((_) => const Reply(200, {'count': 2}));
      final c = makeContainer(adapter);
      addTearDown(c.dispose);
      c.read(tokenHolderProvider).token = 'tok-123';
      await c.read(apiClientProvider).get('/notifications/unread-count');
      final h = adapter.calls.single.headers;
      expect(h['Authorization'], 'Bearer tok-123');
      expect(h['Accept'], 'application/json');
      expect(h.keys.map((k) => k.toLowerCase()), isNot(contains('x-xsrf-token')));
    });

    test('normalises errors: code, message, field errors, Retry-After', () async {
      final adapter = MockAdapter((_) => const Reply(429, {'message': 'Slow down', 'code': 'too_many'}, headers: {'retry-after': ['7']}));
      final c = makeContainer(adapter);
      addTearDown(c.dispose);
      await expectLater(
        c.read(apiClientProvider).post('/x'),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 429).having((e) => e.code, 'code', 'too_many').having((e) => e.retryAfter, 'retryAfter', 7)),
      );
      adapter.handler = (_) => const Reply(422, {'message': 'Invalid', 'errors': {'name': ['Required']}});
      await expectLater(
        c.read(apiClientProvider).post('/x'),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'validation_error').having((e) => e.field('name'), 'field', 'Required')),
      );
    });

    test('web-only refusals are recognised (live_requires_web, web_only)', () async {
      for (final code in ['live_requires_web', 'web_only']) {
        final adapter = MockAdapter((_) => Reply(403, {'message': 'Use the website', 'code': code}));
        final c = makeContainer(adapter);
        addTearDown(c.dispose);
        await expectLater(c.read(apiClientProvider).put('/trading/mode', body: {'mode': 'LIVE'}), throwsA(isA<ApiException>().having((e) => e.isWebOnly, 'isWebOnly', isTrue)));
      }
      expect(const ApiException(403, 'forbidden', 'x').isWebOnly, isFalse);
    });

    test('parses Retry-After as seconds or an HTTP date', () {
      expect(parseRetryAfter('12'), 12);
      expect(parseRetryAfter(null), isNull);
      expect(parseRetryAfter('Sat, 10 Oct 2026 12:00:30 GMT', now: DateTime.utc(2026, 10, 10, 12)), 30);
      expect(parseRetryAfter('garbage'), isNull);
    });
  });

  group('auth flow', () {
    test('login stores the token in secure storage and signs in', () async {
      final adapter = MockAdapter((call) => call.path == '/mobile/auth/login' ? const Reply(200, _ok) : const Reply(404, {}));
      final store = MemorySecureStore();
      final c = makeContainer(adapter, signedIn: false, store: store);
      addTearDown(c.dispose);
      await c.read(authProvider.notifier).restore();
      expect(c.read(authProvider), isA<SignedOut>());
      final outcome = await c.read(authProvider.notifier).login(' test@example.com ', 'secret');
      expect(outcome, LoginOutcome.signedIn);
      expect(c.read(authProvider), isA<SignedIn>());
      expect(store.values[StoreKeys.token], 'new-token');
      expect(c.read(tokenHolderProvider).token, 'new-token');
      final body = adapter.calls.single.json;
      expect(body['email'], 'test@example.com');
      expect(body['device_name'], isNotEmpty);
    });

    test('MFA: wrong code stays on the code step, right code signs in', () async {
      var codeCalls = 0;
      final adapter = MockAdapter((call) {
        if (call.path == '/mobile/auth/login') return const Reply(200, {'mfa_required': true, 'mfa_token': 'mfa-1'});
        codeCalls++;
        return codeCalls == 1 ? const Reply(422, {'message': 'That code is not valid.', 'code': 'invalid_code'}) : const Reply(200, _ok);
      });
      final store = MemorySecureStore();
      final c = makeContainer(adapter, signedIn: false, store: store);
      addTearDown(c.dispose);
      expect(await c.read(authProvider.notifier).login('a@b.c', 'pw'), LoginOutcome.mfaRequired);
      expect(c.read(authProvider), isA<MfaPending>());
      expect(store.values[StoreKeys.token], isNull, reason: 'no token before the second factor');
      await expectLater(c.read(authProvider.notifier).verifyMfa('111111'), throwsA(isA<ApiException>()));
      expect(c.read(authProvider), isA<MfaPending>());
      await c.read(authProvider.notifier).verifyMfa('123 456');
      expect(adapter.calls.last.json, {'mfa_token': 'mfa-1', 'code': '123456'});
      expect(c.read(authProvider), isA<SignedIn>());
      expect(store.values[StoreKeys.token], 'new-token');
    });

    test('MFA expired or locked returns to the password step', () async {
      for (final reply in [const Reply(422, {'message': 'Your sign-in expired.', 'code': 'mfa_expired'}), const Reply(429, {'message': 'Too many wrong codes.', 'code': 'mfa_locked'})]) {
        final adapter = MockAdapter((call) => call.path == '/mobile/auth/login' ? const Reply(200, {'mfa_required': true, 'mfa_token': 'm'}) : reply);
        final c = makeContainer(adapter, signedIn: false);
        addTearDown(c.dispose);
        await c.read(authProvider.notifier).login('a@b.c', 'pw');
        await expectLater(c.read(authProvider.notifier).verifyMfa('000000'), throwsA(isA<ApiException>()));
        expect(c.read(authProvider), isA<SignedOut>());
      }
    });

    test('a 401 anywhere clears the token and returns to sign-in', () async {
      final adapter = MockAdapter((_) => const Reply(401, {'message': 'Unauthenticated.'}));
      final store = MemorySecureStore({StoreKeys.token: 'old', StoreKeys.user: '{"id":"u-1","name":"T","email":"t@e.st"}'});
      final c = makeContainer(adapter, store: store);
      addTearDown(c.dispose);
      await c.read(authProvider.notifier).restore();
      await Future<void>.delayed(Duration.zero);
      await expectLater(c.read(apiClientProvider).get('/overview'), throwsA(isA<ApiException>()));
      await Future<void>.delayed(Duration.zero);
      expect(c.read(authProvider), isA<SignedOut>());
      expect(store.values[StoreKeys.token], isNull);
      expect(c.read(tokenHolderProvider).token, isNull);
    });

    test('sign-out revokes the token and forgets it even when offline', () async {
      final adapter = MockAdapter((_) => throw StateError('offline'));
      final store = MemorySecureStore({StoreKeys.token: 'old', StoreKeys.user: '{"id":"u-1"}'});
      final c = makeContainer(adapter, store: store);
      addTearDown(c.dispose);
      await c.read(authProvider.notifier).restore();
      await c.read(authProvider.notifier).signOut();
      expect(c.read(authProvider), isA<SignedOut>());
      expect(store.values.containsKey(StoreKeys.token), isFalse);
    });
  });

  group('router redirects', () {
    test('signed out goes to sign-in and remembers the deep link', () {
      expect(authRedirect(auth: const SignedOut(), pushExplainerDue: false, location: Uri.parse('/trades/t1')), '/login?from=%2Ftrades%2Ft1');
      expect(authRedirect(auth: const MfaPending(mfaToken: 'x', email: 'e'), pushExplainerDue: false, location: Uri.parse('/home')), '/mfa');
    });

    test('signed in: explainer once, then back to the deep link', () {
      const user = SignedIn(_user);
      expect(authRedirect(auth: user, pushExplainerDue: true, location: Uri.parse('/home')), '/push-intro');
      expect(authRedirect(auth: user, pushExplainerDue: false, location: Uri.parse('/login?from=%2Ftrades%2Ft1')), '/trades/t1');
      expect(authRedirect(auth: user, pushExplainerDue: false, location: Uri.parse('/login?from=%2F%2Fevil.com')), '/home');
      expect(authRedirect(auth: user, pushExplainerDue: false, location: Uri.parse('/history')), isNull);
    });
  });
}

const _user = User(id: 'u-1', name: 'T', email: 't@e.st', role: 'user', mfaEnabled: true, mfaRequired: false);
