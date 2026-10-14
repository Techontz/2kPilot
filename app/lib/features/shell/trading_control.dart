import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/models/models.dart';
import '../../core/status.dart';
import '../../core/web_links.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/badges.dart';
import '../../ui/widgets/dialogs.dart';

/// STOP is one tap — never confirmed, retried until it gets through.
Future<void> stopTrading(BuildContext context, WidgetRef ref) async {
  final busy = ref.read(stoppingProvider.notifier);
  if (busy.state) return;
  busy.state = true;
  try {
    final status = await ref.read(tradingActionsProvider).stop();
    ref.read(statusProvider.notifier).set(status);
    if (context.mounted) showSnack(context, 'Trading stopped', detail: 'No new trades will open. Open trades stay open until they finish.');
  } catch (e) {
    if (context.mounted) {
      showSnack(context, 'Could not stop trading',
          detail: '${e is ApiException ? e.message : 'The server did not answer.'} Press Stop again — it is always safe.', error: true, duration: const Duration(seconds: 15));
    }
  } finally {
    busy.state = false;
  }
}

final stoppingProvider = StateProvider<bool>((ref) => false);

/// Start asks once. The wording comes from a status fetched as the dialog
/// opens, and starting in LIVE sends `live: true` (the server refuses LIVE
/// without it), so a dialog that said "Demo" can never start real money.
Future<void> requestStart(BuildContext context) async {
  final started = await showDialog<TradingStatus>(context: context, builder: (_) => const StartDialog());
  if (started != null && context.mounted) {
    showSnack(context, 'Trading started', detail: 'Active strategies may now trade in ${modeInfo[started.tradingMode]?.label ?? started.tradingMode} mode.');
  }
}

class StartDialog extends ConsumerStatefulWidget {
  const StartDialog({super.key});

  @override
  ConsumerState<StartDialog> createState() => _StartDialogState();
}

class _StartDialogState extends ConsumerState<StartDialog> {
  TradingStatus? _shown;
  bool _checking = true;
  bool _starting = false;
  String? _error;
  ApiException? _webOnly;

  @override
  void initState() {
    super.initState();
    _check();
  }

  Future<void> _check() async {
    final fresh = await ref.read(statusProvider.notifier).load();
    if (!mounted) return;
    setState(() {
      _checking = false;
      _shown = fresh;
      if (fresh == null) _error = "Can't check your trading status right now. Wait a moment and try again.";
    });
  }

  Future<void> _start() async {
    final shown = _shown;
    if (shown == null) return;
    setState(() {
      _starting = true;
      _error = null;
    });
    try {
      final next = await ref.read(tradingActionsProvider).resume(live: shown.isLive);
      ref.read(statusProvider.notifier).set(next);
      if (mounted) Navigator.pop(context, next);
    } on ApiException catch (e) {
      if (e.code == 'live_confirmation_required') {
        // The mode changed since this dialog opened: show the LIVE wording and ask again.
        final fresh = await ref.read(statusProvider.notifier).load();
        if (!mounted) return;
        setState(() {
          _shown = fresh ?? _shown;
          _error = 'Your trading is in LIVE mode now — this would use REAL money. Read the warning and confirm again.';
        });
      } else if (e.isWebOnly) {
        setState(() => _webOnly = e);
      } else {
        setState(() => _error = e.message);
      }
    } catch (_) {
      if (mounted) setState(() => _error = 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _starting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final shown = _shown;
    final live = shown?.isLive ?? false;
    final engine = shown == null ? null : engineHealthView(shown);
    final muted = context.text.bodyMedium?.copyWith(color: c.muted);
    return AlertDialog(
      icon: live ? Icon(Icons.warning_rounded, color: c.live, size: 34) : null,
      title: Text(shown == null ? 'Start trading?' : live ? 'Start trading with REAL money?' : 'Start trading in Demo?'),
      content: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (shown == null && _checking) Text('Checking your trading mode…', style: muted),
          if (shown != null)
            Text.rich(
              TextSpan(style: muted, children: [
                const TextSpan(text: 'Your active strategies may open trades'),
                if (live)
                  TextSpan(text: ' on LIVE accounts with real money.', style: TextStyle(color: c.live, fontWeight: FontWeight.w800))
                else ...[
                  const TextSpan(text: ' on Paper and demo accounts — '),
                  TextSpan(text: 'virtual money only', style: TextStyle(color: c.fg, fontWeight: FontWeight.w800)),
                  const TextSpan(text: '.'),
                ],
                const TextSpan(text: ' Every trade still passes your risk limits. It keeps running on the server after you close the app, until you press Stop.'),
              ]),
            ),
          if (engine != null && !engine.active)
            Padding(padding: const EdgeInsets.only(top: 10), child: Text('${engine.label}: ${engine.message}', style: TextStyle(color: c.warning, fontWeight: FontWeight.w600))),
          if (shown?.platformHalted ?? false)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text('An administrator has paused trading for everyone. Nothing will trade until it is resumed.', style: TextStyle(color: c.warning, fontWeight: FontWeight.w600)),
            ),
          if (_webOnly != null)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Do this on the 2kPilot website', style: TextStyle(color: c.fg, fontWeight: FontWeight.w800)),
                const SizedBox(height: 4),
                Text(_webOnly!.message, style: muted),
                const SizedBox(height: 8),
                OutlinedButton.icon(onPressed: () => WebLinks.open(WebLinks.home), icon: const Icon(Icons.open_in_new_rounded, size: 18), label: const Text('Open the website')),
              ]),
            ),
          if (_error != null)
            Padding(padding: const EdgeInsets.only(top: 10), child: Semantics(liveRegion: true, child: Text(_error!, style: TextStyle(color: c.negative, fontWeight: FontWeight.w600)))),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: Text('Cancel', style: TextStyle(color: c.fg))),
        FilledButton(
          key: const Key('confirm-start'),
          style: FilledButton.styleFrom(backgroundColor: live ? c.live : c.positive, foregroundColor: live ? c.onLive : c.onPositive),
          onPressed: _starting || shown == null || _webOnly != null ? null : _start,
          child: Text(_starting ? 'Starting…' : live ? 'Start with real money' : 'Start trading'),
        ),
      ],
    );
  }
}

/// The big Start / Stop on Home.
class BigTradingButton extends ConsumerWidget {
  const BigTradingButton({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final status = ref.watch(statusProvider.select((r) => r.data));
    final unknown = ref.watch(statusUnknownProvider);
    final busy = ref.watch(stoppingProvider);
    if (showsStart(status, unknown)) {
      return _BigButton(
        key: const Key('start-trading'),
        label: 'Start trading',
        icon: Icons.play_arrow_rounded,
        background: c.positive,
        foreground: c.onPositive,
        iconBackground: Colors.black.withValues(alpha: 0.15),
        onTap: () => requestStart(context),
      );
    }
    return _BigButton(
      key: const Key('stop-trading'),
      label: busy ? 'Stopping…' : 'Stop trading',
      icon: Icons.stop_rounded,
      background: c.soft(c.negative, 0.08),
      foreground: c.negative,
      iconBackground: c.negative,
      iconColor: c.onNegative,
      border: BorderSide(color: c.negative, width: 2),
      onTap: busy ? null : () => stopTrading(context, ref),
    );
  }
}

class _BigButton extends StatelessWidget {
  const _BigButton({super.key, required this.label, required this.icon, required this.background, required this.foreground, required this.iconBackground, this.iconColor, this.border, this.onTap});
  final String label;
  final IconData icon;
  final Color background;
  final Color foreground;
  final Color iconBackground;
  final Color? iconColor;
  final BorderSide? border;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: label,
      excludeSemantics: true,
      child: Material(
        color: background,
        shape: StadiumBorder(side: border ?? BorderSide.none),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: SizedBox(
            height: 60,
            child: Row(children: [
              const SizedBox(width: 8),
              Container(width: 44, height: 44, decoration: BoxDecoration(color: iconBackground, shape: BoxShape.circle), child: Icon(icon, color: iconColor ?? foreground, size: 26)),
              Expanded(child: Text(label, textAlign: TextAlign.center, style: TextStyle(color: foreground, fontSize: 17, fontWeight: FontWeight.w800))),
              const SizedBox(width: 52),
            ]),
          ),
        ),
      ),
    );
  }
}

/// Compact Start / Stop in the top bar of every tab: Stop is always one tap away.
class TradingToggle extends ConsumerWidget {
  const TradingToggle({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final status = ref.watch(statusProvider.select((r) => r.data));
    final unknown = ref.watch(statusUnknownProvider);
    final busy = ref.watch(stoppingProvider);
    if (status == null && !unknown) return const SizedBox(width: 48);
    final start = showsStart(status, unknown);
    return Tooltip(
      message: start ? 'Start trading' : 'Stop trading',
      child: Semantics(
        button: true,
        label: start ? 'Start trading' : 'Stop trading',
        excludeSemantics: true,
        child: Material(
          color: start ? c.positive : c.soft(c.negative, 0.12),
          shape: StadiumBorder(side: start ? BorderSide.none : BorderSide(color: c.negative, width: 1.6)),
          child: InkWell(
            customBorder: const StadiumBorder(),
            onTap: start ? () => requestStart(context) : (busy ? null : () => stopTrading(context, ref)),
            child: SizedBox(
              height: 40,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  Icon(start ? Icons.play_arrow_rounded : Icons.stop_rounded, size: 20, color: start ? c.onPositive : c.negative),
                  const SizedBox(width: 4),
                  Text(start ? 'Start' : (busy ? '…' : 'Stop'), style: TextStyle(fontWeight: FontWeight.w800, fontSize: 14, color: start ? c.onPositive : c.negative)),
                ]),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// The always-visible DEMO / LIVE indicator — and the way back to Demo.
class ModePill extends ConsumerWidget {
  const ModePill({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final status = ref.watch(statusProvider.select((r) => r.data));
    final unknown = ref.watch(statusUnknownProvider);
    if (unknown) {
      // Never show a last-known DEMO/LIVE that may be wrong.
      return Semantics(
        label: 'Status unknown — reconnecting',
        child: Container(
          height: 30,
          padding: const EdgeInsets.symmetric(horizontal: 10),
          decoration: BoxDecoration(color: c.hover, borderRadius: BorderRadius.circular(999)),
          child: Row(mainAxisSize: MainAxisSize.min, children: [Icon(Icons.wifi_off_rounded, size: 14, color: c.muted), const SizedBox(width: 4), Text('Reconnecting…', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: c.muted))]),
        ),
      );
    }
    if (status == null) return const SizedBox.shrink();
    final live = status.isLive;
    return Semantics(
      button: true,
      label: live ? 'LIVE mode — real money. Change mode' : 'Demo mode — virtual money. Change mode',
      excludeSemantics: true,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: () => showModeSheet(context),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 9),
          child: Container(
            height: 30,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            decoration: BoxDecoration(
              color: live ? c.live : Colors.transparent,
              borderRadius: BorderRadius.circular(999),
              border: Border.all(color: live ? c.live : c.soft(c.demo, 0.6), width: 1.4),
              boxShadow: live ? [BoxShadow(color: c.live.withValues(alpha: 0.45), blurRadius: 14, spreadRadius: -2)] : null,
            ),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              StatusDot(color: live ? c.onLive : c.demo, size: 7, pulse: live),
              const SizedBox(width: 7),
              Text(live ? 'LIVE' : 'DEMO', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w900, letterSpacing: 1.5, color: live ? c.onLive : c.demo)),
              const SizedBox(width: 2),
              Icon(Icons.expand_more_rounded, size: 16, color: live ? c.onLive : c.demo),
            ]),
          ),
        ),
      ),
    );
  }
}

/// Return to Demo works in one tap (stopping first when needed); authorising
/// real money is website-only.
Future<void> returnToDemo(BuildContext context, WidgetRef ref) async {
  try {
    final status = await ref.read(tradingActionsProvider).returnToDemo();
    ref.read(statusProvider.notifier).set(status);
    if (context.mounted) showSnack(context, 'Back in Demo mode', detail: 'Real-money trading is off. Trading is stopped — press Start to trade with virtual money.');
  } catch (e) {
    await ref.read(statusProvider.notifier).load();
    if (context.mounted) showApiError(context, e, title: 'Could not return to Demo');
  }
}

Future<void> showModeSheet(BuildContext context) {
  return showModalBottomSheet<void>(useRootNavigator: true, context: context, builder: (_) => const _ModeSheet());
}

class _ModeSheet extends ConsumerStatefulWidget {
  const _ModeSheet();

  @override
  ConsumerState<_ModeSheet> createState() => _ModeSheetState();
}

class _ModeSheetState extends ConsumerState<_ModeSheet> {
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final status = ref.watch(statusProvider.select((r) => r.data));
    final live = status?.isLive ?? false;
    final revoked = !live ? status?.liveRevokedReason : null;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(live ? 'LIVE — real money' : 'Demo — virtual money', style: context.text.titleLarge?.copyWith(color: live ? c.live : c.demo)),
          const SizedBox(height: 6),
          Text(modeInfo[live ? 'LIVE' : 'DEMO']!.explanation, style: context.text.bodyMedium?.copyWith(color: c.muted)),
          if (revoked != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(revoked, style: TextStyle(color: c.warning, fontWeight: FontWeight.w600))),
          const SizedBox(height: 18),
          if (live)
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                key: const Key('return-to-demo'),
                onPressed: _busy
                    ? null
                    : () async {
                        setState(() => _busy = true);
                        await returnToDemo(context, ref);
                        if (context.mounted) Navigator.pop(context);
                      },
                icon: const Icon(Icons.verified_user_rounded),
                label: Text(_busy ? 'Returning…' : 'Return to Demo'),
              ),
            )
          else ...[
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(color: c.raised, borderRadius: BorderRadius.circular(14)),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Icon(Icons.lock_outline_rounded, color: c.brandInk),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    'Real-money trading is authorised on the 2kPilot website only. It needs a LIVE account with a risk profile, two-factor authentication, your password and a typed confirmation.',
                    style: context.text.bodySmall?.copyWith(fontSize: 13.5),
                  ),
                ),
              ]),
            ),
            const SizedBox(height: 14),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: () {
                  Navigator.pop(context);
                  WebLinks.open(WebLinks.realMoney);
                },
                icon: const Icon(Icons.open_in_new_rounded, size: 18),
                label: const Text('Authorize real money on the website'),
              ),
            ),
          ],
        ]),
      ),
    );
  }
}
