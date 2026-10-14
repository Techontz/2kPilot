import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/auth/auth_controller.dart';
import '../../core/web_links.dart';
import '../../state/providers.dart';
import '../../state/push_registrar.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/brand.dart';

/// The dark brand frame shared by the sign-in screens.
class AuthFrame extends StatelessWidget {
  const AuthFrame({super.key, required this.children});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Scaffold(
      body: Container(
        decoration: BoxDecoration(
          gradient: RadialGradient(center: const Alignment(0.9, -1.1), radius: 1.5, colors: [c.soft(c.primary, c.isDark ? 0.35 : 0.16), c.background]),
        ),
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(24, 24, 24, 24),
              child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 440), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children)),
            ),
          ),
        ),
      ),
    );
  }
}

String _friendly(ApiException e) {
  if (e.status == 429 && e.code != 'mfa_locked') {
    final wait = e.retryAfter;
    return wait == null ? 'Too many attempts. Wait a moment and try again.' : 'Too many attempts. Try again in ${wait >= 60 ? '${(wait / 60).ceil()} min' : '$wait s'}.';
  }
  return e.message;
}

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;
  bool _obscure = true;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_email.text.trim().isEmpty || _password.text.isEmpty) {
      setState(() => _error = 'Enter your email and password.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(authProvider.notifier).login(_email.text, _password.text);
      TextInput.finishAutofillContext();
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = _friendly(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final auth = ref.watch(authProvider);
    final notice = auth is SignedOut ? auth.message : null;
    return AuthFrame(children: [
      const Center(child: LogoMark(size: 72)),
      const SizedBox(height: 18),
      const Center(child: Wordmark(size: 30)),
      const SizedBox(height: 28),
      Text('Sign in', style: context.text.headlineMedium),
      const SizedBox(height: 6),
      Text('Use the same email and password as on the website.', style: context.text.bodySmall?.copyWith(fontSize: 14)),
      if (notice != null) ...[
        const SizedBox(height: 14),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: c.soft(c.warning, 0.1), borderRadius: BorderRadius.circular(12), border: Border.all(color: c.soft(c.warning, 0.3))),
          child: Text(notice, style: TextStyle(color: c.fg, fontWeight: FontWeight.w600)),
        ),
      ],
      const SizedBox(height: 22),
      AutofillGroup(
        child: Column(children: [
          TextField(
            key: const Key('login-email'),
            controller: _email,
            keyboardType: TextInputType.emailAddress,
            autofillHints: const [AutofillHints.email, AutofillHints.username],
            autocorrect: false,
            textInputAction: TextInputAction.next,
            decoration: const InputDecoration(labelText: 'Email', prefixIcon: Icon(Icons.mail_outline_rounded)),
          ),
          const SizedBox(height: 14),
          TextField(
            key: const Key('login-password'),
            controller: _password,
            obscureText: _obscure,
            autofillHints: const [AutofillHints.password],
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => _submit(),
            decoration: InputDecoration(
              labelText: 'Password',
              prefixIcon: const Icon(Icons.lock_outline_rounded),
              suffixIcon: IconButton(
                tooltip: _obscure ? 'Show password' : 'Hide password',
                onPressed: () => setState(() => _obscure = !_obscure),
                icon: Icon(_obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
              ),
            ),
          ),
        ]),
      ),
      if (_error != null) ...[
        const SizedBox(height: 12),
        Semantics(liveRegion: true, child: Text(_error!, style: TextStyle(color: c.negative, fontWeight: FontWeight.w700))),
      ],
      const SizedBox(height: 22),
      SizedBox(
        height: 54,
        child: FilledButton(
          key: const Key('login-submit'),
          onPressed: _busy ? null : _submit,
          child: _busy ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.4, color: Colors.white)) : const Text('Sign in', style: TextStyle(fontSize: 16)),
        ),
      ),
      const SizedBox(height: 18),
      Row(mainAxisAlignment: MainAxisAlignment.center, children: [
        Text('New to 2kPilot?', style: context.text.bodySmall?.copyWith(fontSize: 14)),
        TextButton(onPressed: () => WebLinks.open(WebLinks.signup), child: const Text('Create an account')),
      ]),
      Center(child: TextButton(onPressed: () => WebLinks.open(WebLinks.page('/login')), child: Text('Forgot your password? Use the website', style: TextStyle(color: c.muted)))),
    ]);
  }
}

class MfaScreen extends ConsumerStatefulWidget {
  const MfaScreen({super.key});

  @override
  ConsumerState<MfaScreen> createState() => _MfaScreenState();
}

class _MfaScreenState extends ConsumerState<MfaScreen> {
  final _code = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_code.text.trim().isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(authProvider.notifier).verifyMfa(_code.text);
    } on ApiException catch (e) {
      // invalid_code stays here; mfa_expired / mfa_locked return to the password step.
      if (mounted) setState(() => _error = _friendly(e));
      _code.clear();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final auth = ref.watch(authProvider);
    final email = auth is MfaPending ? auth.email : '';
    return AuthFrame(children: [
      const Center(child: LogoMark(size: 60)),
      const SizedBox(height: 24),
      Text('Two-factor code', style: context.text.headlineMedium),
      const SizedBox(height: 6),
      Text('Enter the 6-digit code from your authenticator app for $email. A recovery code also works.', style: context.text.bodySmall?.copyWith(fontSize: 14)),
      const SizedBox(height: 22),
      TextField(
        key: const Key('mfa-code'),
        controller: _code,
        autofocus: true,
        keyboardType: TextInputType.visiblePassword,
        autofillHints: const [AutofillHints.oneTimeCode],
        textAlign: TextAlign.center,
        maxLength: 20,
        style: tnum(const TextStyle(fontSize: 26, fontWeight: FontWeight.w800, letterSpacing: 6)),
        decoration: const InputDecoration(hintText: '000000', counterText: ''),
        onChanged: (v) {
          if (RegExp(r'^\d{6}$').hasMatch(v.trim())) _submit();
        },
        onSubmitted: (_) => _submit(),
      ),
      if (_error != null) ...[const SizedBox(height: 12), Semantics(liveRegion: true, child: Text(_error!, style: TextStyle(color: c.negative, fontWeight: FontWeight.w700)))],
      const SizedBox(height: 20),
      SizedBox(
        height: 54,
        child: FilledButton(
          key: const Key('mfa-submit'),
          onPressed: _busy ? null : _submit,
          child: _busy ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.4, color: Colors.white)) : const Text('Verify'),
        ),
      ),
      const SizedBox(height: 10),
      TextButton(onPressed: () => ref.read(authProvider.notifier).cancelMfa(), child: const Text('Back to sign in')),
    ]);
  }
}

/// Pre-permission explainer, shown once after sign-in when push is available.
class PushIntroScreen extends ConsumerWidget {
  const PushIntroScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final push = ref.watch(pushRegistrarProvider);
    Widget point(IconData icon, String title, String text) => Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(width: 40, height: 40, decoration: BoxDecoration(color: c.soft(c.primary, 0.18), shape: BoxShape.circle), child: Icon(icon, color: c.brandInk, size: 21)),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15.5)),
                const SizedBox(height: 2),
                Text(text, style: context.text.bodySmall?.copyWith(fontSize: 13.5)),
              ]),
            ),
          ]),
        );
    return AuthFrame(children: [
      Center(
        child: Container(
          width: 84,
          height: 84,
          decoration: BoxDecoration(shape: BoxShape.circle, color: c.soft(c.primary, 0.2)),
          child: Icon(Icons.notifications_active_rounded, size: 42, color: c.brandInk),
        ),
      ),
      const SizedBox(height: 22),
      Text('Know what your bot is doing', textAlign: TextAlign.center, style: context.text.headlineMedium),
      const SizedBox(height: 8),
      Text('Turn on notifications to hear about it the moment something happens — even when the app is closed.', textAlign: TextAlign.center, style: context.text.bodySmall?.copyWith(fontSize: 14)),
      const SizedBox(height: 26),
      point(Icons.swap_vert_rounded, 'Trades opened and closed', 'With the result, so you never have to keep checking.'),
      point(Icons.shield_outlined, 'Risk limits reached', 'When a daily limit or losing streak stops trading for the day.'),
      point(Icons.power_off_outlined, 'Connection problems', 'If your broker disconnects or the platform is halted.'),
      if (push.error != null) Padding(padding: const EdgeInsets.only(bottom: 10), child: Text(push.error!, textAlign: TextAlign.center, style: TextStyle(color: c.negative, fontWeight: FontWeight.w600))),
      const SizedBox(height: 8),
      SizedBox(
        height: 54,
        child: FilledButton(
          onPressed: push.busy
              ? null
              : () async {
                  await ref.read(pushRegistrarProvider.notifier).enable();
                },
          child: Text(push.busy ? 'Turning on…' : 'Turn on notifications'),
        ),
      ),
      const SizedBox(height: 8),
      TextButton(onPressed: push.busy ? null : () => ref.read(pushRegistrarProvider.notifier).dismissExplainer(), child: Text('Not now', style: TextStyle(color: c.muted))),
      const SizedBox(height: 4),
      Text('You can change this any time in Settings → Notifications.', textAlign: TextAlign.center, style: context.text.bodySmall),
    ]);
  }
}

/// Shown while the stored token is read at start-up.
class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context) => const Scaffold(backgroundColor: Color(0xFF121212), body: Center(child: LogoMark(size: 96)));
}
