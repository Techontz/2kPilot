import 'dart:math' as math;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../theme.dart';

class BarPoint {
  const BarPoint(this.label, this.value, [this.detail]);
  final String label;
  final double value;
  final String? detail;
}

/// Profit/loss per period: green above zero, red below.
class PnlBars extends StatelessWidget {
  const PnlBars({super.key, required this.bars, required this.format, required this.semanticLabel, this.height = 180});
  final List<BarPoint> bars;
  final String Function(double) format;
  final String semanticLabel;
  final double height;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final maxUp = bars.fold<double>(0, (m, b) => math.max(m, b.value));
    final maxDown = bars.fold<double>(0, (m, b) => math.max(m, -b.value));
    final top = maxUp == 0 ? (maxDown == 0 ? 1.0 : maxDown * 0.25) : maxUp * 1.1;
    final bottom = maxDown == 0 ? 0.0 : -maxDown * 1.1;
    final width = bars.isEmpty ? 6.0 : (260 / bars.length).clamp(3.0, 16.0);
    final total = bars.fold<double>(0, (s, b) => s + b.value);
    return Semantics(
      label: '$semanticLabel. ${bars.length} periods, total ${format(total)}.',
      excludeSemantics: true,
      child: SizedBox(
        height: height,
        child: BarChart(
          duration: context.reduceMotion ? Duration.zero : const Duration(milliseconds: 250),
          BarChartData(
            maxY: top,
            minY: bottom,
            alignment: BarChartAlignment.spaceBetween,
            borderData: FlBorderData(show: false),
            titlesData: const FlTitlesData(show: false),
            gridData: FlGridData(
              show: true,
              drawVerticalLine: false,
              horizontalInterval: math.max(top, -bottom),
              checkToShowHorizontalLine: (v) => v == 0,
              getDrawingHorizontalLine: (v) => FlLine(color: v == 0 ? c.lineStrong : c.border, strokeWidth: 1),
            ),
            barTouchData: BarTouchData(
              touchTooltipData: BarTouchTooltipData(
                getTooltipColor: (_) => c.isDark ? const Color(0xFF2A2A2A) : const Color(0xFF1C1C1C),
                tooltipBorderRadius: BorderRadius.circular(10),
                getTooltipItem: (group, _, rod, _) {
                  final b = bars[group.x];
                  return BarTooltipItem(
                    '${b.label}\n',
                    const TextStyle(color: Colors.white70, fontSize: 11.5, fontWeight: FontWeight.w600),
                    children: [
                      TextSpan(text: format(b.value), style: tnum(TextStyle(color: b.value >= 0 ? const Color(0xFF3DCB83) : const Color(0xFFF2716A), fontWeight: FontWeight.w800, fontSize: 13))),
                      if (b.detail != null) TextSpan(text: '\n${b.detail}', style: const TextStyle(color: Colors.white60, fontSize: 11)),
                    ],
                  );
                },
              ),
            ),
            barGroups: [
              for (var i = 0; i < bars.length; i++)
                BarChartGroupData(x: i, barRods: [
                  BarChartRodData(
                    toY: bars[i].value == 0 ? 0 : bars[i].value,
                    width: width,
                    color: bars[i].value >= 0 ? c.positive : c.negative,
                    borderRadius: BorderRadius.vertical(
                      top: Radius.circular(bars[i].value >= 0 ? 3 : 0),
                      bottom: Radius.circular(bars[i].value < 0 ? 3 : 0),
                    ),
                  ),
                ]),
            ],
          ),
        ),
      ),
    );
  }
}

/// A line (balance, equity curve, drawdown) with a soft area under it.
class LineSeries extends StatelessWidget {
  const LineSeries({super.key, required this.values, required this.semanticLabel, required this.format, this.labels, this.height = 180, this.color, this.inverted = false});
  final List<double> values;
  final List<String>? labels;
  final String semanticLabel;
  final String Function(double) format;
  final double height;
  final Color? color;

  /// Drawdown: the area hangs from the top.
  final bool inverted;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final lineColor = color ?? c.brandInk;
    final lo = values.reduce(math.min), hi = values.reduce(math.max);
    final pad = (hi - lo).abs() < 1e-9 ? (hi.abs() * 0.02 + 1) : (hi - lo) * 0.12;
    return Semantics(
      label: '$semanticLabel. From ${format(values.first)} to ${format(values.last)}; lowest ${format(lo)}, highest ${format(hi)}.',
      excludeSemantics: true,
      child: SizedBox(
        height: height,
        child: LineChart(
          duration: context.reduceMotion ? Duration.zero : const Duration(milliseconds: 250),
          LineChartData(
            minY: lo - pad,
            maxY: hi + pad,
            borderData: FlBorderData(show: false),
            titlesData: const FlTitlesData(show: false),
            gridData: FlGridData(show: true, drawVerticalLine: false, getDrawingHorizontalLine: (_) => FlLine(color: c.border, strokeWidth: 1)),
            lineTouchData: LineTouchData(
              touchTooltipData: LineTouchTooltipData(
                getTooltipColor: (_) => c.isDark ? const Color(0xFF2A2A2A) : const Color(0xFF1C1C1C),
                tooltipBorderRadius: BorderRadius.circular(10),
                getTooltipItems: (spots) => spots
                    .map((s) => LineTooltipItem(
                          '${labels != null && s.x.toInt() < labels!.length ? '${labels![s.x.toInt()]}\n' : ''}${format(s.y)}',
                          tnum(const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 12.5)),
                        ))
                    .toList(),
              ),
            ),
            lineBarsData: [
              LineChartBarData(
                spots: [for (var i = 0; i < values.length; i++) FlSpot(i.toDouble(), values[i])],
                isCurved: true,
                curveSmoothness: 0.2,
                preventCurveOverShooting: true,
                color: lineColor,
                barWidth: 2.4,
                dotData: const FlDotData(show: false),
                belowBarData: inverted
                    ? BarAreaData(show: false)
                    : BarAreaData(show: true, gradient: LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: [lineColor.withValues(alpha: 0.28), lineColor.withValues(alpha: 0.0)])),
                aboveBarData: inverted
                    ? BarAreaData(show: true, gradient: LinearGradient(begin: Alignment.bottomCenter, end: Alignment.topCenter, colors: [lineColor.withValues(alpha: 0.28), lineColor.withValues(alpha: 0.0)]))
                    : BarAreaData(show: false),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
