/// Strategy helpers ported from the web's features/strategies/insights.ts and
/// strategyUtils.ts: where a strategy may run, its parameters, the latest
/// decision's market regime and the honest backtest verdict. Pure functions.
library;

import 'contracts.dart';
import 'models/strategy.dart';
import 'models/trading.dart';
import 'status.dart';

const List<String> timeframes = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'];

StrategyVersion? latestVersion(Strategy s) {
  if (s.latestVersion != null) return s.latestVersion;
  if (s.versions.isEmpty) return null;
  final sorted = [...s.versions]..sort((a, b) => b.version.compareTo(a.version));
  return sorted.first;
}

/// The candles the strategy decides on: the rule set's timeframe, else the suggestion, else M5.
String strategyTimeframe(Strategy s) {
  final params = latestVersion(s)?.parameters ?? const {};
  final fromRules = params['timeframe'] ?? params['entry_timeframe'];
  if (fromRules is String && timeframes.contains(fromRules)) return fromRules;
  return s.details.suggestedTimeframe ?? 'M5';
}

bool isRuleBased(Strategy s) => s.key == 'rules';

/// The user's own strategies (plus templates they activated directly).
bool isMine(Strategy s) => !s.builtIn || s.assignments.isNotEmpty;

/// A name not used by any of [taken] ("EMA crossover", "EMA crossover (2)", …).
String uniqueName(String base, List<String> taken) {
  final names = taken.map((n) => n.toLowerCase()).toSet();
  String cut(String s, int n) => s.length > n ? s.substring(0, n) : s;
  if (!names.contains(base.toLowerCase())) return cut(base, 120);
  for (var i = 2; i < 1000; i++) {
    final candidate = '${cut(base, 110)} ($i)';
    if (!names.contains(candidate.toLowerCase())) return candidate;
  }
  return '${cut(base, 100)} (${DateTime.now().millisecondsSinceEpoch})';
}

/// Plain-English rules for any strategy.
String rulesText(Strategy s) => s.rulesText ?? latestVersion(s)?.rulesText ?? s.summary ?? s.description;

/// One rule per line ("Buy when …. Sell when …. Stop: …").
List<String> ruleLines(String text) =>
    text.split(RegExp(r'(?<=\.)\s+(?=[A-Z])')).map((s) => s.trim()).where((s) => s.isNotEmpty).toList();

List<String>? allowedFamilies(Strategy s) => s.contractFamilies ?? s.details.supportedContractFamilies;
List<String>? allowedSymbols(Strategy s) => s.symbols ?? s.details.supportedSymbols;

/// What a broker offers, narrowed to what the strategy supports.
List<String> familiesFor(Strategy s, List<String> offered) {
  final allowed = allowedFamilies(s);
  return allowed == null ? offered : offered.where(allowed.contains).toList();
}

const _allFamilies = ['RISE_FALL', 'MULTIPLIER', 'SPOT'];

/// "Multiplier (Deriv) · Spot (Paper) · not Rise/Fall", or "Every contract type".
String contractSupportText(List<String>? families) {
  if (families == null) return 'Every contract type';
  const where = {'MULTIPLIER': ' (Deriv)', 'SPOT': ' (Paper)', 'RISE_FALL': ''};
  final yes = _allFamilies.where(families.contains).map((f) => '${familyLabel[f]}${where[f]}');
  final no = _allFamilies.where((f) => !families.contains(f)).map((f) => 'not ${familyLabel[f]}');
  return [...yes, ...no].join(' · ');
}

const Map<String, String> regimeLabel = {
  'TREND_UP': 'Uptrend',
  'TREND_DOWN': 'Downtrend',
  'SIDEWAYS': 'Sideways',
  'HIGH_VOLATILITY': 'High volatility',
  'UNCERTAIN': 'Unclear',
};

const Map<String, Tone> regimeTone = {
  'TREND_UP': Tone.positive,
  'TREND_DOWN': Tone.negative,
  'SIDEWAYS': Tone.neutral,
  'HIGH_VOLATILITY': Tone.warning,
  'UNCERTAIN': Tone.neutral,
};

/// The market regime recorded in an evaluation, if any.
({String regime, String reason})? regimeOf(Evaluation? e) {
  if (e == null) return null;
  final check = e.checks.where((c) => c.rule == 'Market regime').firstOrNull;
  final re = RegExp(r'^(TREND_UP|TREND_DOWN|SIDEWAYS|HIGH_VOLATILITY|UNCERTAIN)\s*—\s*(.*)$');
  final fromCheck = check == null ? null : re.firstMatch(check.detail);
  if (fromCheck != null) return (regime: fromCheck.group(1)!, reason: fromCheck.group(2) ?? '');
  final fromSummary = RegExp(r'regime (TREND_UP|TREND_DOWN|SIDEWAYS|HIGH_VOLATILITY|UNCERTAIN)\s*—\s*(.*)$').firstMatch(e.summary);
  return fromSummary == null ? null : (regime: fromSummary.group(1)!, reason: fromSummary.group(2) ?? '');
}

/// BUY / SELL / NO_TRADE for the latest completed evaluation.
String? decisionOf(Evaluation? e) {
  if (e == null) return null;
  if (e.outcome != 'SIGNAL') return 'NO_TRADE';
  return e.summary.startsWith('SELL') ? 'SELL' : 'BUY';
}

const _riskKeys = ['risk_per_trade_pct', 'max_daily_loss_pct', 'max_open_positions'];
const Map<String, String> riskCapLabel = {
  'risk_per_trade_pct': 'Risk per trade (max, % of balance)',
  'max_daily_loss_pct': 'Daily loss limit (max, %)',
  'max_open_positions': 'Open positions (max)',
};

/// The strategy's own risk caps (they only tighten your risk profile).
List<({String key, String label, String value})> riskCaps(Map<String, dynamic>? params) {
  if (params == null) return const [];
  return [
    for (final k in _riskKeys)
      if (params[k] != null) (key: k, label: riskCapLabel[k]!, value: k == 'max_open_positions' ? '${params[k]}' : '${params[k]}%'),
  ];
}

/// The latest version's parameters with the engine's descriptions.
List<({String key, String label, String value, String? description})> parameterRows(Strategy s) {
  if (s.key == 'rules') return const [];
  final params = latestVersion(s)?.parameters ?? const {};
  return [
    for (final e in params.entries)
      if (!_riskKeys.contains(e.key))
        (
          key: e.key,
          label: s.schema[e.key]?.title ?? (e.key.replaceAll('_', ' ').isEmpty ? e.key : e.key.replaceAll('_', ' ')[0].toUpperCase() + e.key.replaceAll('_', ' ').substring(1)),
          value: e.value is bool ? (e.value as bool ? 'yes' : 'no') : '${e.value is Map || e.value is List ? e.value.toString() : e.value}',
          description: s.schema[e.key]?.description,
        ),
  ];
}

/// Does every tested market qualify for demo forward testing?
({ValidationGate? gate, bool qualifies}) validationVerdict(Strategy s) {
  final tested = s.backtestsBySymbol ?? (s.backtest == null ? const <BacktestHeadline>[] : [s.backtest!]);
  final gate = tested.map((b) => b.validation).whereType<ValidationGate>().firstOrNull;
  final qualifies = tested.isNotEmpty && tested.every((b) => b.validation == null || b.validation!.qualifies) && gate != null;
  return (gate: gate, qualifies: qualifies);
}

String sourceLabel(String? source) => switch (source) {
      'template' => 'Template',
      'builder' => 'Built by you',
      'ai' => 'From description',
      'import' => 'Imported',
      'copy' => 'Your copy',
      'code' => 'Built-in',
      _ => 'Strategy',
    };

/// Backtest status pill text.
String backtestStatusLabel(Backtest b) => switch (b.status) {
      'COMPLETED' => 'Finished',
      'FAILED' => 'Failed',
      'RUNNING' => 'Running ${b.progress}%',
      _ => 'Waiting to start',
    };

/// A dataset with the right market + candles covering the period (reuse instead of downloading again).
Dataset? findDataset(List<Dataset> datasets, String symbol, String timeframe, String source, DateTime start, DateTime end) {
  const day = Duration(days: 1);
  for (final d in datasets) {
    if (d.symbol != symbol || d.timeframe != timeframe || d.source != source) continue;
    final first = d.firstBar == null ? null : DateTime.tryParse(d.firstBar!);
    final last = d.lastBar == null ? null : DateTime.tryParse(d.lastBar!);
    if (first == null || last == null) continue;
    if (!first.isAfter(start.add(day)) && !last.isBefore(end.subtract(day * 2))) return d;
  }
  return null;
}

/// Accounts whose broker can provide past prices for a test.
bool canDownloadHistory(Account a) => a.connectorType != 'paper' && a.historicalCandles != false && a.connectionStatus == ConnectionStatus.connected;
