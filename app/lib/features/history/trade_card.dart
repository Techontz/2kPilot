import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../core/contracts.dart';
import '../../core/format.dart';
import '../../core/models/models.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/badges.dart';
import '../../ui/widgets/money.dart';
import '../../ui/widgets/states.dart';

/// One trade as a card (History, Home): direction, contract, P/L, and for
/// open Rise/Fall contracts the time left.
class TradeCard extends StatelessWidget {
  const TradeCard({super.key, required this.trade, required this.onTap, this.open = false, this.showAccount = false, this.now, this.flat = false});
  /// Inside another card (Home): a raised row instead of a card.
  final bool flat;
  final Trade trade;
  final VoidCallback onTap;
  final bool open;
  final bool showAccount;
  final DateTime? now;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final t = trade;
    final currency = t.account?.currency;
    final left = t.contractFamily == 'RISE_FALL' ? formatCountdown(t.expiresAt, now: now) : null;
    final small = context.text.bodySmall?.copyWith(fontSize: 12.5);
    final strong = tnum(TextStyle(color: c.fg, fontWeight: FontWeight.w600, fontSize: 12.5));
    return Semantics(
      button: true,
      label: '${t.symbol} ${tradeDirection(t)}, ${open ? 'current' : 'result'} ${formatSignedCurrency(open ? t.unrealizedPnl : t.netPnl, currency)}. Details',
      excludeSemantics: true,
      child: AppCard(
        onTap: onTap,
        color: flat ? c.raised : null,
        border: flat ? Border.all(color: Colors.transparent) : null,
        radius: flat ? 12 : 16,
        padding: EdgeInsets.all(flat ? 12 : 14),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          open && t.contractFamily == 'RISE_FALL' ? CountdownRing(trade: t, now: now ?? DateTime.now()) : DirectionTile(up: tradeIsUp(t)),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(
                  child: Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                    Text(t.symbol, style: const TextStyle(fontSize: 15.5, fontWeight: FontWeight.w800)),
                    DirectionText(t),
                    OutcomeBadge(t),
                  ]),
                ),
                const SizedBox(width: 8),
                PnlText(open ? t.unrealizedPnl : t.netPnl, currency: currency, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
              ]),
              const SizedBox(height: 4),
              Text('${tradeContractLabel(t)} · ${t.strategy ?? (t.source == 'MANUAL' ? 'Manual' : emDash)}', maxLines: 1, overflow: TextOverflow.ellipsis, style: small),
              const SizedBox(height: 6),
              Wrap(spacing: 12, runSpacing: 2, children: [
                Text.rich(TextSpan(children: [TextSpan(text: isContractTrade(t) ? 'Stake ' : 'Size '), TextSpan(text: sizeText(t, currency), style: strong)]), style: small),
                if (open) ...[
                  Text.rich(TextSpan(children: [const TextSpan(text: 'Opened '), TextSpan(text: formatTime(t.entryTime), style: tnum(small))]), style: small),
                  if (left != null)
                    Row(mainAxisSize: MainAxisSize.min, children: [
                      Icon(Icons.timer_outlined, size: 13, color: c.fg),
                      const SizedBox(width: 3),
                      Text('$left left', style: strong.copyWith(fontWeight: FontWeight.w800)),
                    ]),
                ] else ...[
                  Text.rich(TextSpan(children: [const TextSpan(text: 'Held '), TextSpan(text: formatDuration(t.durationSeconds), style: strong)]), style: small),
                  Text.rich(TextSpan(children: [const TextSpan(text: 'Fees '), TextSpan(text: formatCurrency(t.fees ?? t.commission ?? '0', currency), style: strong)]), style: small),
                ],
              ]),
              if (!open) Padding(padding: const EdgeInsets.only(top: 2), child: Text('Closed ${formatTime(t.exitTime)}', style: small?.copyWith(color: c.subtle))),
              if (showAccount && t.account != null)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Row(children: [
                    Flexible(child: Text(t.account!.label, maxLines: 1, overflow: TextOverflow.ellipsis, style: small)),
                    const SizedBox(width: 6),
                    EnvBadge(t.account!.environment),
                  ]),
                ),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// Rise/Fall: a ring that empties as the contract runs out.
class CountdownRing extends StatelessWidget {
  const CountdownRing({super.key, required this.trade, required this.now, this.size = 44});
  final Trade trade;
  final DateTime now;
  final double size;

  @override
  Widget build(BuildContext context) {
    final start = parseTime(trade.entryTime);
    final end = parseTime(trade.expiresAt);
    final up = tradeIsUp(trade);
    if (start == null || end == null || !end.isAfter(start)) return DirectionTile(up: up, size: size);
    final c = context.c;
    final color = up ? c.positive : c.negative;
    final left = (end.difference(now).inMilliseconds / end.difference(start).inMilliseconds).clamp(0.0, 1.0);
    return ExcludeSemantics(
      child: SizedBox(
        width: size,
        height: size,
        child: CustomPaint(
          painter: _RingPainter(left, color, c.hover),
          child: Icon(up ? Icons.trending_up_rounded : Icons.trending_down_rounded, color: color, size: size * 0.4),
        ),
      ),
    );
  }
}

class _RingPainter extends CustomPainter {
  _RingPainter(this.left, this.color, this.track);
  final double left;
  final Color color;
  final Color track;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    final stroke = size.width * 0.09;
    final r = rect.deflate(stroke / 2 + 1);
    canvas.drawArc(r, 0, math.pi * 2, false, Paint()
      ..color = track
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke);
    canvas.drawArc(r, -math.pi / 2, math.pi * 2 * left, false, Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeWidth = stroke);
  }

  @override
  bool shouldRepaint(covariant _RingPainter old) => old.left != left || old.color != color;
}
