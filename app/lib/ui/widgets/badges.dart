import 'package:flutter/material.dart';

import '../../core/contracts.dart';
import '../../core/models/models.dart';
import '../../core/status.dart';
import '../theme.dart';

enum PillTone { neutral, positive, negative, warning, info, live, demo, primary }

PillTone pillToneOf(Tone t) => switch (t) {
      Tone.positive => PillTone.positive,
      Tone.negative => PillTone.negative,
      Tone.warning => PillTone.warning,
      Tone.neutral => PillTone.neutral,
      Tone.live => PillTone.live,
      Tone.info => PillTone.info,
    };

Color toneColor(BuildContext context, Tone t) {
  final c = context.c;
  return switch (t) {
    Tone.positive => c.positive,
    Tone.negative => c.negative,
    Tone.warning => c.warning,
    Tone.neutral => c.subtle,
    Tone.live => c.live,
    Tone.info => c.info,
  };
}

/// Small status pill (semantic 2kPilot colours).
class Pill extends StatelessWidget {
  const Pill(this.label, {super.key, this.tone = PillTone.neutral, this.dot = false, this.icon, this.semantics});

  final String label;
  final PillTone tone;
  final bool dot;
  final IconData? icon;
  final String? semantics;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final (Color bg, Color fg, Color ring) = switch (tone) {
      PillTone.neutral => (c.hover, c.muted, c.border),
      PillTone.positive => (c.soft(c.positive), c.positive, c.soft(c.positive, 0.28)),
      PillTone.negative => (c.soft(c.negative), c.negative, c.soft(c.negative, 0.28)),
      PillTone.warning => (c.soft(c.warning), c.warning, c.soft(c.warning, 0.28)),
      PillTone.info => (c.soft(c.info), c.info, c.soft(c.info, 0.28)),
      PillTone.live => (c.live, c.onLive, c.live),
      PillTone.demo => (Colors.transparent, c.demo, c.soft(c.demo, 0.6)),
      PillTone.primary => (c.soft(c.primary, 0.14), c.brandInk, c.soft(c.primary, 0.3)),
    };
    return Semantics(
      label: semantics,
      child: Container(
        height: 24,
        padding: const EdgeInsets.symmetric(horizontal: 10),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(999), border: Border.all(color: ring)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (dot) ...[Container(width: 6, height: 6, decoration: BoxDecoration(color: fg, shape: BoxShape.circle)), const SizedBox(width: 6)],
          if (icon != null) ...[Icon(icon, size: 13, color: fg), const SizedBox(width: 4)],
          Text(label, maxLines: 1, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: fg, height: 1.1)),
        ]),
      ),
    );
  }
}

/// PAPER / DEMO (calm, outlined purple) vs LIVE (solid red, real money).
class EnvBadge extends StatelessWidget {
  const EnvBadge(this.env, {super.key});
  final AccountEnvironment env;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final (String label, String title) = switch (env) {
      AccountEnvironment.paper => ('PAPER', 'Simulated by 2kPilot — no money'),
      AccountEnvironment.demo => ('DEMO', 'Demo account — virtual money'),
      AccountEnvironment.live => ('LIVE', 'LIVE account — REAL MONEY'),
      AccountEnvironment.unknown => ('UNKNOWN', 'The broker did not confirm demo or live — never trades'),
    };
    final (Color bg, Color fg, Color ring) = switch (env) {
      AccountEnvironment.paper => (c.hover, c.muted, c.border),
      AccountEnvironment.demo => (Colors.transparent, c.demo, c.soft(c.demo, 0.6)),
      AccountEnvironment.live => (c.live, c.onLive, c.live),
      AccountEnvironment.unknown => (c.soft(c.warning), c.warning, c.soft(c.warning, 0.3)),
    };
    return Semantics(
      label: title,
      excludeSemantics: true,
      child: Container(
        height: 22,
        padding: const EdgeInsets.symmetric(horizontal: 8),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(999), border: Border.all(color: ring, width: 1.2)),
        child: Center(
          widthFactor: 1,
          child: Text(label,
              style: TextStyle(fontSize: 11, fontWeight: env == AccountEnvironment.live ? FontWeight.w900 : FontWeight.w800, letterSpacing: 1.0, color: fg, height: 1)),
        ),
      ),
    );
  }
}

class StatusDot extends StatelessWidget {
  const StatusDot({super.key, required this.color, this.size = 10, this.pulse = false});
  final Color color;
  final double size;
  final bool pulse;

  @override
  Widget build(BuildContext context) {
    final dot = Container(width: size, height: size, decoration: BoxDecoration(color: color, shape: BoxShape.circle));
    if (!pulse || context.reduceMotion) return dot;
    return _Pulse(color: color, size: size, child: dot);
  }
}

class _Pulse extends StatefulWidget {
  const _Pulse({required this.color, required this.size, required this.child});
  final Color color;
  final double size;
  final Widget child;

  @override
  State<_Pulse> createState() => _PulseState();
}

class _PulseState extends State<_Pulse> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1800))..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: widget.size,
      height: widget.size,
      child: Stack(clipBehavior: Clip.none, alignment: Alignment.center, children: [
        AnimatedBuilder(
          animation: _c,
          builder: (_, _) => Transform.scale(
            scale: 1 + _c.value * 1.6,
            child: Opacity(
              opacity: (1 - _c.value) * 0.55,
              child: Container(width: widget.size, height: widget.size, decoration: BoxDecoration(color: widget.color, shape: BoxShape.circle)),
            ),
          ),
        ),
        widget.child,
      ]),
    );
  }
}

class ConnectionDot extends StatelessWidget {
  const ConnectionDot(this.status, {super.key});
  final ConnectionStatus status;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final color = switch (status) {
      ConnectionStatus.connected => c.positive,
      ConnectionStatus.disconnected => c.subtle,
      ConnectionStatus.reconnecting => c.warning,
      ConnectionStatus.error => c.negative,
    };
    return Semantics(label: status.label, child: StatusDot(color: color, size: 9, pulse: status == ConnectionStatus.connected));
  }
}

/// Won / Lost / Closed early / Break-even / Open.
class OutcomeBadge extends StatelessWidget {
  const OutcomeBadge(this.trade, {super.key});
  final Trade trade;

  @override
  Widget build(BuildContext context) {
    if (trade.isOpen) return const Pill('Open', tone: PillTone.info, dot: true);
    final pnl = double.tryParse(trade.netPnl ?? '') ?? 0;
    return switch (trade.outcome) {
      'WON' => const Pill('Won', tone: PillTone.positive),
      'LOST' => const Pill('Lost', tone: PillTone.negative),
      'CANCELLED' => const Pill('Cancelled'),
      'SOLD' => Pill('Closed early', tone: pnl > 0 ? PillTone.positive : pnl < 0 ? PillTone.negative : PillTone.neutral),
      _ => pnl == 0 ? const Pill('Break-even') : (pnl > 0 ? const Pill('Profit', tone: PillTone.positive) : const Pill('Loss', tone: PillTone.negative)),
    };
  }
}

/// "↗ Rise" / "↘ Fall" (the text carries the meaning, not just the colour).
class DirectionText extends StatelessWidget {
  const DirectionText(this.trade, {super.key, this.size = 12.5});
  final Trade trade;
  final double size;

  @override
  Widget build(BuildContext context) {
    final up = tradeIsUp(trade);
    final color = up ? context.c.positive : context.c.negative;
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(up ? Icons.north_east_rounded : Icons.south_east_rounded, size: size + 2, color: color),
      const SizedBox(width: 2),
      Text(tradeDirection(trade), style: TextStyle(fontSize: size, fontWeight: FontWeight.w700, color: color)),
    ]);
  }
}

/// Square direction tile used as a trade row's "cover".
class DirectionTile extends StatelessWidget {
  const DirectionTile({super.key, required this.up, this.size = 44});
  final bool up;
  final double size;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final color = up ? c.positive : c.negative;
    return ExcludeSemantics(
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(color: c.soft(color), borderRadius: BorderRadius.circular(10)),
        child: Icon(up ? Icons.trending_up_rounded : Icons.trending_down_rounded, color: color, size: size * 0.48),
      ),
    );
  }
}
