import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme.dart';

/// The 2K app tile.
class LogoMark extends StatelessWidget {
  const LogoMark({super.key, this.size = 36});
  final double size;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(size * 0.26),
        boxShadow: [BoxShadow(color: const Color(0xFF6E28B4).withValues(alpha: 0.45), blurRadius: 16, offset: const Offset(0, 6), spreadRadius: -6)],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(size * 0.22),
        child: Image.asset('assets/brand/icon-192.png', width: size, height: size, fit: BoxFit.cover, semanticLabel: '2kPilot'),
      ),
    );
  }
}

/// "2k" in the foreground colour followed by "Pilot" in lavender.
class Wordmark extends StatelessWidget {
  const Wordmark({super.key, this.size = 22, this.onDark = false});
  final double size;
  final bool onDark;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final style = TextStyle(fontFamily: fontFamily, fontSize: size, fontWeight: FontWeight.w900, letterSpacing: -size * 0.04, height: 1);
    return Semantics(
      label: '2kPilot',
      excludeSemantics: true,
      child: Text.rich(TextSpan(children: [
        TextSpan(text: '2k', style: style.copyWith(color: onDark ? Colors.white : c.fg)),
        TextSpan(text: 'Pilot', style: style.copyWith(color: onDark ? const Color(0xFFC8A2F0) : c.brandInk)),
      ])),
    );
  }
}

class Logo extends StatelessWidget {
  const Logo({super.key, this.size = 22, this.onDark = false});
  final double size;
  final bool onDark;

  @override
  Widget build(BuildContext context) => Row(mainAxisSize: MainAxisSize.min, children: [
        LogoMark(size: size * 1.55),
        SizedBox(width: size * 0.45),
        Wordmark(size: size, onDark: onDark),
      ]);
}

/// Abstract cover artwork for strategies and tests: a chart motif on a
/// one-hue purple/graphite background, picked deterministically from the
/// name. Never green or red (those mean profit, loss and real money).
class Artwork extends StatelessWidget {
  const Artwork({super.key, required this.seed, this.size, this.width, this.height, this.radius = 10, this.values});
  final String seed;
  final double? size;
  final double? width;
  final double? height;
  final double radius;

  /// A real series (e.g. the balance) instead of a motif.
  final List<double>? values;

  static const _palettes = [
    [Color(0xFF9E4FE0), Color(0xFF5A1389)],
    [Color(0xFF2E2E31), Color(0xFF0E0E10)],
    [Color(0xFF7B34C9), Color(0xFF33094F)],
    [Color(0xFFA66BE6), Color(0xFF6C25B0)],
    [Color(0xFF3C3C40), Color(0xFF18181A)],
    [Color(0xFF5A1389), Color(0xFF1D0533)],
  ];

  static int hash(String text) {
    var h = 2166136261;
    for (final code in text.codeUnits) {
      h = ((h ^ code) * 16777619) & 0xFFFFFFFF;
    }
    return h;
  }

  @override
  Widget build(BuildContext context) {
    final h = hash(seed);
    final palette = _palettes[h % _palettes.length];
    return ExcludeSemantics(
      child: Container(
        width: size ?? width,
        height: size ?? height,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(radius),
          gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: palette),
          boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.25), blurRadius: 18, offset: const Offset(0, 8), spreadRadius: -8)],
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(radius),
          child: CustomPaint(painter: _MotifPainter(seed: h, text: seed.toLowerCase(), values: values)),
        ),
      ),
    );
  }
}

class _MotifPainter extends CustomPainter {
  _MotifPainter({required this.seed, required this.text, this.values});
  final int seed;
  final String text;
  final List<double>? values;

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width, h = size.height;
    final line = Paint()
      ..color = Colors.white
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round
      ..strokeWidth = math.max(1.6, w * 0.03);
    final faint = Paint()
      ..color = Colors.white.withValues(alpha: 0.18)
      ..style = PaintingStyle.fill;

    // Soft glow in a corner.
    canvas.drawCircle(Offset(w * 0.85, h * 0.1), w * 0.6, Paint()..shader = RadialGradient(colors: [Colors.white.withValues(alpha: 0.14), Colors.transparent]).createShader(Rect.fromCircle(center: Offset(w * 0.85, h * 0.1), radius: w * 0.6)));

    final series = values;
    if (series != null && series.length > 1) {
      final lo = series.reduce(math.min), hi = series.reduce(math.max);
      final span = (hi - lo).abs() < 1e-9 ? 1.0 : hi - lo;
      final path = Path();
      for (var i = 0; i < series.length; i++) {
        final x = w * 0.08 + (w * 0.84) * i / (series.length - 1);
        final y = h * 0.78 - (h * 0.5) * (series[i] - lo) / span;
        i == 0 ? path.moveTo(x, y) : path.lineTo(x, y);
      }
      canvas.drawPath(path, line);
      return;
    }

    final rnd = math.Random(seed);
    if (text.contains('breakout') || text.contains('highest')) {
      final box = RRect.fromRectAndRadius(Rect.fromLTWH(w * 0.14, h * 0.42, w * 0.46, h * 0.24), const Radius.circular(3));
      canvas.drawRRect(box, faint);
      final p = Path()..moveTo(w * 0.1, h * 0.6);
      for (final (x, y) in [(0.2, 0.5), (0.28, 0.58), (0.36, 0.46), (0.44, 0.56), (0.54, 0.44), (0.64, 0.34), (0.74, 0.26), (0.88, 0.14)]) {
        p.lineTo(w * x, h * y);
      }
      canvas.drawPath(p, line);
      canvas.drawCircle(Offset(w * 0.88, h * 0.14), w * 0.04, Paint()..color = Colors.white);
    } else if (text.contains('cross') || text.contains('ema') || text.contains('moving')) {
      final a = Path()
        ..moveTo(w * 0.08, h * 0.7)
        ..cubicTo(w * 0.3, h * 0.66, w * 0.4, h * 0.3, w * 0.92, h * 0.26);
      final b = Path()
        ..moveTo(w * 0.08, h * 0.4)
        ..cubicTo(w * 0.3, h * 0.44, w * 0.54, h * 0.7, w * 0.92, h * 0.62);
      canvas.drawPath(a, line);
      canvas.drawPath(b, Paint()
        ..color = Colors.white.withValues(alpha: 0.5)
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round
        ..strokeWidth = line.strokeWidth);
      canvas.drawCircle(Offset(w * 0.44, h * 0.52), w * 0.05, Paint()..color = Colors.white);
    } else if (text.contains('rsi') || text.contains('bollinger') || text.contains('reversion')) {
      final dash = Paint()
        ..color = Colors.white.withValues(alpha: 0.45)
        ..strokeWidth = 1.4;
      for (var x = w * 0.06; x < w * 0.94; x += w * 0.08) {
        canvas.drawLine(Offset(x, h * 0.3), Offset(x + w * 0.04, h * 0.3), dash);
        canvas.drawLine(Offset(x, h * 0.72), Offset(x + w * 0.04, h * 0.72), dash);
      }
      final p = Path()..moveTo(w * 0.06, h * 0.52);
      for (var i = 1; i <= 8; i++) {
        p.quadraticBezierTo(w * (0.06 + 0.11 * i - 0.055), h * (i.isOdd ? 0.26 : 0.78), w * (0.06 + 0.11 * i), h * 0.52);
      }
      canvas.drawPath(p, line);
    } else {
      // Candles / momentum bars with a trend line.
      final n = 8;
      for (var i = 0; i < n; i++) {
        final x = w * (0.12 + i * 0.1);
        final hh = h * (0.08 + rnd.nextDouble() * 0.22);
        final up = rnd.nextBool();
        canvas.drawRRect(
          RRect.fromRectAndRadius(Rect.fromLTWH(x, h * 0.72 - hh, w * 0.055, hh), const Radius.circular(1.5)),
          Paint()..color = Colors.white.withValues(alpha: up ? 0.85 : 0.4),
        );
      }
      final p = Path()
        ..moveTo(w * 0.08, h * 0.5)
        ..cubicTo(w * 0.3, h * 0.32, w * 0.45, h * 0.28, w * 0.55, h * 0.42)
        ..cubicTo(w * 0.7, h * 0.52, w * 0.8, h * 0.3, w * 0.92, h * 0.2);
      canvas.drawPath(p, line);
    }
  }

  @override
  bool shouldRepaint(covariant _MotifPainter old) => old.seed != seed || old.values != values;
}
