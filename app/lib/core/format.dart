/// Display formatting, ported from the web app's lib/format.ts.
///
/// Money arrives as decimal strings and is only parsed here, for display.
/// Signed amounts use a true minus sign (U+2212) like the web.
library;

import 'package:intl/intl.dart';

const String emDash = '—';
const String minus = '−';

double? toNumber(Object? value) {
  if (value == null) return null;
  if (value is num) return value.isFinite ? value.toDouble() : null;
  final s = value.toString().trim();
  if (s.isEmpty) return null;
  final n = double.tryParse(s);
  return n != null && n.isFinite ? n : null;
}

String _grouped(double n, {int digits = 2}) {
  final f = NumberFormat.decimalPatternDigits(decimalDigits: digits);
  return f.format(n);
}

/// 12,345.67 (no symbol), with " USD" appended when a currency is given.
String formatMoney(Object? value, [String? currency]) {
  final n = toNumber(value);
  if (n == null) return emDash;
  final text = _grouped(n);
  return currency != null && currency.isNotEmpty ? '$text $currency' : text;
}

/// Signed plain money: "+12.50", "−3.20".
String formatPnl(Object? value, [String? currency]) {
  final n = toNumber(value);
  if (n == null) return emDash;
  final abs = _grouped(n.abs());
  final sign = n > 0 ? '+' : n < 0 ? minus : '';
  return '$sign$abs${currency != null && currency.isNotEmpty ? ' $currency' : ''}';
}

final RegExp _iso4217 = RegExp(r'^[A-Z]{3}$');

NumberFormat? _currencyFormatter(String? currency) {
  if (currency == null || !_iso4217.hasMatch(currency)) return null;
  try {
    return NumberFormat.simpleCurrency(name: currency, decimalDigits: 2);
  } catch (_) {
    return null;
  }
}

/// "$1,234.56" in the account currency (falls back to "1,234.56 XYZ").
String formatCurrency(Object? value, [String? currency]) {
  final n = toNumber(value);
  if (n == null) return emDash;
  final f = _currencyFormatter(currency);
  if (f == null) return formatMoney(n, currency);
  final text = f.format(n.abs());
  return n < 0 ? '-$text' : text;
}

/// Signed money in the account currency: "+$12.50", "−$3.20", "$0.00".
String formatSignedCurrency(Object? value, [String? currency]) {
  final n = toNumber(value);
  if (n == null) return emDash;
  final f = _currencyFormatter(currency);
  final abs = f != null ? f.format(n.abs()) : formatMoney(n.abs(), currency);
  final rounded = (n * 100).round();
  final sign = rounded > 0 ? '+' : rounded < 0 ? minus : '';
  return '$sign$abs';
}

String formatPct(Object? value, {int digits = 2, bool signed = false}) {
  final n = toNumber(value);
  if (n == null) return emDash;
  final sign = signed && n > 0 ? '+' : n < 0 ? minus : '';
  return '$sign${n.abs().toStringAsFixed(digits)}%';
}

String formatNumber(Object? value, {int digits = 2}) {
  final n = toNumber(value);
  if (n == null) return emDash;
  return _grouped(n, digits: digits);
}

/// Price with the symbol's precision (JPY pairs 3, most FX 5, other markets 4).
String formatPrice(Object? value, [String? symbol]) {
  final n = toNumber(value);
  if (n == null) return emDash;
  int digits;
  if (symbol != null && symbol.isNotEmpty) {
    final forex = RegExp(r'^[A-Z]{6}$').hasMatch(symbol);
    digits = forex ? (symbol.contains('JPY') ? 3 : 5) : 4;
  } else {
    final parts = value.toString().split('.');
    final decimals = parts.length > 1 ? parts[1].length : 0;
    digits = decimals == 0 ? 2 : (decimals > 5 ? 5 : decimals);
  }
  return n.toStringAsFixed(digits);
}

enum PnlTone { positive, negative, neutral }

PnlTone pnlTone(Object? value) {
  final n = toNumber(value);
  if (n == null || n == 0) return PnlTone.neutral;
  return n > 0 ? PnlTone.positive : PnlTone.negative;
}

DateTime? parseTime(String? iso) {
  if (iso == null || iso.isEmpty) return null;
  return DateTime.tryParse(iso)?.toLocal();
}

/// "Oct 11, 2026 3:20 PM"
String formatDateTime(String? iso) {
  final d = parseTime(iso);
  if (d == null) return emDash;
  return DateFormat.yMMMd().add_jm().format(d);
}

/// "Oct 11, 3:20 PM"
String formatTime(String? iso) {
  final d = parseTime(iso);
  if (d == null) return emDash;
  return DateFormat.MMMd().add_jm().format(d);
}

/// "Oct 11, 2026"
String formatDate(String? iso) {
  final d = parseTime(iso);
  if (d == null) return emDash;
  return DateFormat.yMMMd().format(d);
}

/// "just now", "5 min ago", "3 h ago", else the date and time.
String formatRelative(String? iso, {DateTime? now}) {
  final d = parseTime(iso);
  if (d == null) return emDash;
  final seconds = ((now ?? DateTime.now()).difference(d).inMilliseconds / 1000).round();
  if (seconds < 60) return 'just now';
  final minutes = (seconds / 60).round();
  if (minutes < 60) return '$minutes min ago';
  final hours = (minutes / 60).round();
  if (hours < 24) return '$hours h ago';
  return formatDateTime(iso);
}

/// Compact duration: 45 → "45s", 310 → "5m 10s", 7500 → "2h 5m", 280000 → "3d 5h".
String formatDuration(num? seconds) {
  if (seconds == null || !seconds.isFinite) return emDash;
  final s = seconds.round() < 0 ? 0 : seconds.round();
  if (s < 60) return '${s}s';
  final m = s ~/ 60;
  if (m < 60) return s % 60 != 0 ? '${m}m ${s % 60}s' : '${m}m';
  final h = m ~/ 60;
  if (h < 24) return m % 60 != 0 ? '${h}h ${m % 60}m' : '${h}h';
  final d = h ~/ 24;
  return h % 24 != 0 ? '${d}d ${h % 24}h' : '${d}d';
}

/// Time left until [iso]: "4:59", "1:02:03"; "0:00" once passed; null without a time.
String? formatCountdown(String? iso, {DateTime? now}) {
  if (iso == null) return null;
  final end = DateTime.tryParse(iso);
  if (end == null) return null;
  final diff = end.difference(now ?? DateTime.now()).inMilliseconds;
  final left = diff <= 0 ? 0 : diff ~/ 1000;
  final h = left ~/ 3600;
  final m = (left % 3600) ~/ 60;
  final s = left % 60;
  final mm = h > 0 ? m.toString().padLeft(2, '0') : '$m';
  return '${h > 0 ? '$h:' : ''}$mm:${s.toString().padLeft(2, '0')}';
}

/// "RISK_REJECTED" → "Risk rejected"
String humanize(String text) {
  final lower = text.replaceAll('_', ' ').toLowerCase();
  if (lower.isEmpty) return lower;
  return lower[0].toUpperCase() + lower.substring(1);
}
