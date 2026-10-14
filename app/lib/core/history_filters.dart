/// History filters → API query (GET /api/history) and the CSV export
/// (GET /api/history/export?format=csv&…). Ported from the web's
/// features/history/filters.ts. Pure, so they are unit-tested.
library;

enum OutcomeFilter {
  all('', 'All results'),
  win('win', 'Profit'),
  loss('loss', 'Loss'),
  even('even', 'Break-even');

  const OutcomeFilter(this.wire, this.label);
  final String wire;
  final String label;
}

enum RangePreset {
  today('Today'),
  d7('Last 7 days'),
  d30('Last 30 days'),
  d90('Last 90 days'),
  all('All time'),
  custom('Custom dates');

  const RangePreset(this.label);
  final String label;
}

class HistoryFilters {
  const HistoryFilters({this.from = '', this.to = '', this.accountId = '', this.strategyId = '', this.outcome = OutcomeFilter.all});

  /// YYYY-MM-DD (inclusive), "" = no bound.
  final String from;
  final String to;
  final String accountId;
  final String strategyId;
  final OutcomeFilter outcome;

  static const empty = HistoryFilters();

  HistoryFilters copyWith({String? from, String? to, String? accountId, String? strategyId, OutcomeFilter? outcome}) => HistoryFilters(
        from: from ?? this.from,
        to: to ?? this.to,
        accountId: accountId ?? this.accountId,
        strategyId: strategyId ?? this.strategyId,
        outcome: outcome ?? this.outcome,
      );

  /// Filters beyond the period, for the "Filters (n)" badge.
  int get extraCount => [accountId, strategyId, outcome.wire].where((v) => v.isNotEmpty).length;

  @override
  bool operator ==(Object other) =>
      other is HistoryFilters && other.from == from && other.to == to && other.accountId == accountId && other.strategyId == strategyId && other.outcome == outcome;

  @override
  int get hashCode => Object.hash(from, to, accountId, strategyId, outcome);
}

final RegExp _date = RegExp(r'^\d{4}-\d{2}-\d{2}$');

/// Query parameters for /history and /history/export (empty filters are left out).
Map<String, Object> historyQuery(HistoryFilters f, [Map<String, Object> extra = const {}]) {
  final q = <String, Object>{};
  if (f.accountId.isNotEmpty) q['account_id'] = f.accountId;
  if (f.strategyId.isNotEmpty) q['strategy_id'] = f.strategyId;
  if (_date.hasMatch(f.from)) q['from'] = f.from;
  if (_date.hasMatch(f.to)) q['to'] = f.to;
  if (f.outcome.wire.isNotEmpty) q['outcome'] = f.outcome.wire;
  return {...q, ...extra};
}

/// The export path with the current filters (relative to the API base).
String exportPath(HistoryFilters f) {
  final params = <String, String>{'format': 'csv'};
  historyQuery(f).forEach((k, v) => params[k] = '$v');
  return '/history/export?${Uri(queryParameters: params).query}';
}

String _ymd(DateTime d) => d.toUtc().toIso8601String().substring(0, 10);

/// Date range for a preset, in UTC days (the API filters on exit time).
({String from, String to}) presetRange(RangePreset preset, {DateTime? now}) {
  final n = (now ?? DateTime.now()).toUtc();
  final today = _ymd(n);
  String daysAgo(int days) => _ymd(n.subtract(Duration(days: days)));
  return switch (preset) {
    RangePreset.today => (from: today, to: today),
    RangePreset.d7 => (from: daysAgo(6), to: today),
    RangePreset.d30 => (from: daysAgo(29), to: today),
    RangePreset.d90 => (from: daysAgo(89), to: today),
    _ => (from: '', to: ''),
  };
}

/// Which preset (if any) a range corresponds to.
RangePreset detectPreset(HistoryFilters f, {DateTime? now}) {
  for (final p in [RangePreset.today, RangePreset.d7, RangePreset.d30, RangePreset.d90, RangePreset.all]) {
    final r = presetRange(p, now: now);
    if (r.from == f.from && r.to == f.to) return p;
  }
  return RangePreset.custom;
}

/// "from" after "to" is a mistake worth saying out loud.
String? rangeProblem(HistoryFilters f) {
  if (_date.hasMatch(f.from) && _date.hasMatch(f.to) && f.from.compareTo(f.to) > 0) return 'The start date is after the end date.';
  return null;
}
