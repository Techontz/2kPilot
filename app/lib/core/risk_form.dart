/// Risk profile form: fields, explanations and conversion to/from the API
/// (backend RiskProfileRequest). Ported from the web's features/risk/riskForm.ts
/// and lib/liveAuth.ts (limitSentences). An empty optional field = limit off.
library;

import 'format.dart';
import 'models/settings.dart';

enum LimitUnit { money, pct, count, lots, pips, ratio, minutes, seconds }

class LimitField {
  const LimitField(this.key, this.label, this.unit, this.help, {this.required = false});
  final String key;
  final String label;
  final LimitUnit unit;
  final String help;
  final bool required;

  bool get integer => unit == LimitUnit.count || unit == LimitUnit.minutes || unit == LimitUnit.seconds;
}

const List<LimitField> basicFields = [
  LimitField('stake_amount', 'Stake per trade', LimitUnit.money, 'What each trade risks. A Rise/Fall or Multiplier trade can never lose more than its stake.', required: true),
  LimitField('max_stake_amount', 'Largest stake on one trade', LimitUnit.money, 'A hard cap: no single trade may stake more than this, whatever a strategy asks for.'),
  LimitField('max_daily_loss_amount', 'Daily loss limit', LimitUnit.money, 'Stop trading for the day after losing this much (closed and open trades).'),
  LimitField('max_daily_loss_pct', 'Daily loss limit (% of balance)', LimitUnit.pct, 'The same, as a share of the balance. Whichever limit is reached first applies.'),
  LimitField('max_consecutive_losses', 'Stop after losses in a row', LimitUnit.count, 'Stop for the day after this many losing trades in a row.'),
  LimitField('daily_profit_target_amount', 'Daily profit target', LimitUnit.money, 'Stop for the day after making this much — keeps a good day good.'),
  LimitField('max_trades_per_day', 'Trades per day', LimitUnit.count, 'The most trades a day. Prevents over-trading.'),
  LimitField('max_open_positions', 'Trades open at once', LimitUnit.count, 'The most trades open at the same time on the account.'),
];

const List<(String, List<LimitField>)> advancedGroups = [
  (
    'Per trade (Spot)',
    [
      LimitField('risk_per_trade_pct', 'Risk per trade', LimitUnit.pct, 'Money lost if the stop loss is hit, as % of equity. Spot position size is calculated from this.', required: true),
      LimitField('max_position_lots', 'Largest position', LimitUnit.lots, 'Upper cap per position, whatever the sizing says.'),
      LimitField('min_stop_pips', 'Shortest stop loss', LimitUnit.pips, 'Stops closer than this are too easily hit by noise.'),
      LimitField('max_stop_pips', 'Longest stop loss', LimitUnit.pips, 'Very wide stops mean very small positions.'),
      LimitField('min_reward_risk', 'Minimum reward:risk', LimitUnit.ratio, 'e.g. 1.5 = the target must be at least 1.5 times the stop distance.'),
    ]
  ),
  (
    'Loss limits',
    [
      LimitField('max_weekly_loss_pct', 'Weekly loss limit', LimitUnit.pct, 'Stop for the week once losses reach this (week starts Monday 00:00 UTC).'),
      LimitField('max_drawdown_pct', 'Maximum drawdown', LimitUnit.pct, 'Hitting this switches trading off for the account until you review it.'),
      LimitField('cooldown_after_losses', 'Pause after losses in a row', LimitUnit.count, 'Start a pause after this many losses in a row…'),
      LimitField('cooldown_minutes', 'Pause length', LimitUnit.minutes, '…for this long. Set both or neither.'),
      LimitField('min_account_balance', 'Minimum account balance', LimitUnit.money, 'No new trades while the balance is below this. Empty = off.'),
    ]
  ),
  (
    'Exposure',
    [
      LimitField('max_positions_per_symbol', 'Positions per symbol', LimitUnit.count, 'Avoid stacking trades on one instrument.'),
      LimitField('max_symbol_exposure_lots', 'Size open on one symbol', LimitUnit.lots, 'Total lots open on one symbol.'),
      LimitField('max_total_exposure_lots', 'Size open on the account', LimitUnit.lots, 'Total lots open on the whole account.'),
      LimitField('max_total_risk_pct', 'Total open risk', LimitUnit.pct, 'Sum of the risk of all open trades, as % of equity.'),
    ]
  ),
  (
    'Market conditions',
    [
      LimitField('max_spread_pips', 'Spread protection', LimitUnit.pips, 'Skip trades when the spread is wider than this.'),
      LimitField('max_slippage_pips', 'Slippage protection', LimitUnit.pips, 'Largest price difference accepted when the order fills.'),
      LimitField('max_data_age_seconds', 'Oldest price allowed', LimitUnit.seconds, 'Never trade on a stale price.', required: true),
    ]
  ),
];

const List<String> sessions = ['ASIA', 'LONDON', 'OVERLAP', 'NEW_YORK'];

List<LimitField> get allLimitFields => [...basicFields, for (final g in advancedGroups) ...g.$2];

/// Defaults for a new profile: the Beginner limits.
const Map<String, String> newProfileValues = {
  'stake_amount': '1',
  'max_stake_amount': '5',
  'max_consecutive_losses': '3',
  'max_trades_per_day': '20',
  'max_open_positions': '3',
  'max_daily_loss_pct': '2',
  'risk_per_trade_pct': '0.5',
  'max_weekly_loss_pct': '4',
  'max_drawdown_pct': '10',
  'max_data_age_seconds': '120',
  'min_stop_pips': '8',
  'max_stop_pips': '150',
  'min_reward_risk': '1.5',
  'max_spread_pips': '2.5',
};

/// "2.000" → "2", "0.500" → "0.5", null → "".
String trimDecimal(Object? value) {
  if (value == null) return '';
  final text = value.toString();
  if (!RegExp(r'^-?\d+(\.\d+)?$').hasMatch(text)) return text;
  return text.contains('.') ? text.replaceFirst(RegExp(r'0+$'), '').replaceFirst(RegExp(r'\.$'), '') : text;
}

class ProfileForm {
  ProfileForm({required this.name, required this.values, required this.sessions, required this.hoursStart, required this.hoursEnd});
  String name;
  final Map<String, String> values;
  final List<String> sessions;
  String hoursStart;
  String hoursEnd;

  factory ProfileForm.from(RiskProfile? profile) {
    if (profile == null) {
      return ProfileForm(name: '', values: {...newProfileValues}, sessions: ['LONDON', 'OVERLAP', 'NEW_YORK'], hoursStart: '', hoursEnd: '');
    }
    return ProfileForm(
      name: profile.name,
      values: {for (final f in allLimitFields) f.key: trimDecimal(profile.raw[f.key])},
      sessions: [...profile.allowedSessions],
      hoursStart: _hhmm(profile.tradingHoursStart),
      hoursEnd: _hhmm(profile.tradingHoursEnd),
    );
  }

  static String _hhmm(String? v) => v == null ? '' : (v.length >= 5 ? v.substring(0, 5) : v);

  Map<String, Object?> toBody() {
    final body = <String, Object?>{
      'name': name.trim(),
      'allowed_sessions': sessions,
      'trading_hours_start': hoursStart.isEmpty ? null : hoursStart,
      'trading_hours_end': hoursEnd.isEmpty ? null : hoursEnd,
    };
    for (final f in allLimitFields) {
      final v = (values[f.key] ?? '').trim().replaceFirst(',', '.');
      body[f.key] = v.isEmpty ? null : v;
    }
    return body;
  }
}

/// Fields with a validation error that live in the Advanced section.
List<String> advancedErrorKeys(Map<String, List<String>> errors) {
  final advanced = {for (final g in advancedGroups) ...g.$2.map((f) => f.key), 'allowed_sessions', 'trading_hours_start', 'trading_hours_end'};
  return errors.keys.where((k) => advanced.contains(k.split('.').first)).toList();
}

String unitLabel(LimitUnit unit, [String? currency]) => switch (unit) {
      LimitUnit.money => currency ?? 'account currency',
      LimitUnit.pct => '%',
      LimitUnit.count => '',
      LimitUnit.lots => 'lots',
      LimitUnit.pips => 'pips',
      LimitUnit.ratio => '× risk',
      LimitUnit.minutes => 'minutes',
      LimitUnit.seconds => 'seconds',
    };

class LimitSentence {
  const LimitSentence(this.key, this.text, {this.off = false});
  final String key;
  final String text;

  /// This optional limit is switched off.
  final bool off;
}

/// A risk profile's contract limits, in plain words.
List<LimitSentence> limitSentences(RiskProfile p, [String? currency]) {
  String money(double v) => formatCurrency(v, currency);
  double? num(String key) => toNumber(p.raw[key]);
  String fmt(double v) => v == v.roundToDouble() ? v.toStringAsFixed(0) : '$v';
  const noLimit = 'No limit set';
  final out = <LimitSentence>[];
  final stake = num('stake_amount');
  out.add(stake != null ? LimitSentence('stake', 'Each trade risks ${money(stake)} (stake per trade)') : const LimitSentence('stake', 'Stake per trade: $noLimit', off: true));
  final maxStake = num('max_stake_amount');
  out.add(maxStake != null ? LimitSentence('max_stake', 'Never more than ${money(maxStake)} on one trade') : const LimitSentence('max_stake', 'Largest stake on one trade: $noLimit', off: true));
  final streak = num('max_consecutive_losses');
  out.add(streak != null
      ? LimitSentence('streak', 'Stops for the day after ${fmt(streak)} ${streak == 1 ? 'loss' : 'losses'} in a row')
      : const LimitSentence('streak', 'Losses in a row: $noLimit', off: true));
  final lossAmount = num('max_daily_loss_amount');
  final lossPct = num('max_daily_loss_pct');
  if (lossAmount != null) out.add(LimitSentence('daily_loss_amount', 'Stops for the day after losing ${money(lossAmount)}'));
  if (lossPct != null) out.add(LimitSentence('daily_loss_pct', 'Stops for the day after losing ${fmt(lossPct)}% of the balance'));
  if (lossAmount == null && lossPct == null) out.add(const LimitSentence('daily_loss', 'Daily loss limit: $noLimit', off: true));
  final target = num('daily_profit_target_amount');
  out.add(target != null ? LimitSentence('profit_target', 'Stops for the day after making ${money(target)}') : const LimitSentence('profit_target', 'Daily profit target: $noLimit', off: true));
  final trades = num('max_trades_per_day');
  out.add(trades != null
      ? LimitSentence('trades_per_day', 'At most ${fmt(trades)} ${trades == 1 ? 'trade' : 'trades'} a day')
      : const LimitSentence('trades_per_day', 'Trades per day: $noLimit', off: true));
  final open = num('max_open_positions');
  out.add(open != null ? LimitSentence('open_positions', 'At most ${fmt(open)} open at once') : const LimitSentence('open_positions', 'Trades open at once: $noLimit', off: true));
  return out;
}
