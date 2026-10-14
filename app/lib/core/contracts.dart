/// Plain-English contract labels and checks (Rise/Fall, Multipliers, Spot),
/// ported from the web's lib/contracts.ts.
library;

import 'format.dart';
import 'models/strategy.dart';
import 'models/trading.dart';

const Map<String, String> familyLabel = {'RISE_FALL': 'Rise/Fall', 'MULTIPLIER': 'Multiplier', 'SPOT': 'Spot'};

const Map<String, String> familyHelp = {
  'RISE_FALL':
      'You pick a direction and a duration. If the price ends higher (Rise) or lower (Fall) than it started, you win the payout; otherwise you lose the stake. The stake is the most you can lose.',
  'MULTIPLIER':
      'Profit and loss are the price move multiplied by the multiplier. It runs until it is closed (by a rule, a take profit or a stop loss). You can never lose more than the stake.',
  'SPOT': 'Paper only. A position in lots with a stop loss and a take profit, sized from your risk per trade.',
};

const Map<String, String> familyShort = {
  'RISE_FALL': 'Up or down over a fixed time',
  'MULTIPLIER': 'Profit/loss × a multiplier',
  'SPOT': 'Paper only, in lots',
};

const Map<String, (String, String)> _unitWords = {
  't': ('tick', 'ticks'),
  's': ('second', 'seconds'),
  'm': ('minute', 'minutes'),
  'h': ('hour', 'hours'),
  'd': ('day', 'days'),
};

const List<(String, String)> durationUnits = [('t', 'Ticks'), ('s', 'Seconds'), ('m', 'Minutes'), ('h', 'Hours'), ('d', 'Days')];

const Map<String, int> _seconds = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400};

String durationText(int? duration, String? unit) {
  if (duration == null || duration == 0 || unit == null || !_unitWords.containsKey(unit)) return emDash;
  final (one, many) = _unitWords[unit]!;
  return '$duration ${duration == 1 ? one : many}';
}

/// "15s" / "1d" / "5t" → (amount, unit).
(int, String)? parseDuration(String text) {
  final m = RegExp(r'^(\d+)([tsmhd])$').firstMatch(text.trim());
  if (m == null) return null;
  return (int.parse(m.group(1)!), m.group(2)!);
}

/// Is `duration unit` inside any of the broker's ranges? Ticks only compare with ticks.
bool durationAllowed(int duration, String unit, List<DurationRange> ranges) {
  return ranges.any((r) {
    final lo = parseDuration(r.min);
    final hi = parseDuration(r.max);
    if (lo == null || hi == null) return false;
    if (unit == 't' || lo.$2 == 't' || hi.$2 == 't') {
      return unit == 't' && lo.$2 == 't' && hi.$2 == 't' && lo.$1 <= duration && duration <= hi.$1;
    }
    final secs = duration * (_seconds[unit] ?? 1);
    return lo.$1 * _seconds[lo.$2]! <= secs && secs <= hi.$1 * _seconds[hi.$2]!;
  });
}

/// "Rise/Fall · 25 minutes · stake $1.00".
String contractSummary(ContractSpec? spec, {String? currency, Object? profileStake}) {
  if (spec == null) return emDash;
  final parts = <String>[familyLabel[spec.contractFamily] ?? spec.contractFamily];
  if (spec.contractFamily == 'RISE_FALL') parts.add(durationText(spec.duration, spec.durationUnit));
  if (spec.contractFamily == 'MULTIPLIER' && spec.multiplier != null) parts.add('×${spec.multiplier}');
  if (spec.contractFamily != 'SPOT') {
    if (spec.stake != null && spec.stake!.isNotEmpty) {
      parts.add('stake ${formatCurrency(spec.stake, currency)}');
    } else if (profileStake != null) {
      parts.add('stake ${formatCurrency(profileStake, currency)} (risk profile)');
    } else {
      parts.add('stake from risk profile');
    }
  } else {
    parts.add('sized by your risk per trade');
  }
  return parts.join(' · ');
}

/// "Rise" / "Fall" / "Up" / "Down" / "Buy" / "Sell".
String directionLabel({required String side, String? contractFamily, String? contractType}) {
  final type = contractType ?? '';
  if (contractFamily == 'RISE_FALL' || type.startsWith('CALL') || type.startsWith('PUT')) {
    return type.startsWith('PUT') || (type.isEmpty && side == 'SELL') ? 'Fall' : 'Rise';
  }
  if (contractFamily == 'MULTIPLIER' || type.startsWith('MULT')) {
    return type == 'MULTDOWN' || (type.isEmpty && side == 'SELL') ? 'Down' : 'Up';
  }
  return side == 'BUY' ? 'Buy' : 'Sell';
}

bool directionIsUp({required String side, String? contractType}) {
  final type = contractType ?? '';
  if (type.startsWith('PUT') || type == 'MULTDOWN') return false;
  if (type.startsWith('CALL') || type == 'MULTUP') return true;
  return side == 'BUY';
}

String tradeDirection(Trade t) => directionLabel(side: t.side, contractFamily: t.contractFamily, contractType: t.contractType);
bool tradeIsUp(Trade t) => directionIsUp(side: t.side, contractType: t.contractType);

/// "Rise/Fall", "Multiplier ×100" or "Spot".
String tradeContractLabel(Trade t) {
  final family = t.contractFamily ?? 'SPOT';
  if (family == 'MULTIPLIER' && t.multiplier != null) return 'Multiplier ×${t.multiplier}';
  return familyLabel[family] ?? family;
}

bool isContractTrade(Trade t) => t.contractFamily != null && t.contractFamily != 'SPOT';

/// Stake (contracts) or volume (Spot lots) as text.
String sizeText(Trade t, [String? currency]) {
  if (t.stake != null && isContractTrade(t)) return formatCurrency(t.stake, currency);
  final n = toNumber(t.volume);
  if (n == null) return emDash;
  final text = n == n.roundToDouble() ? n.toStringAsFixed(0) : n.toStringAsFixed(2).replaceFirst(RegExp(r'0$'), '');
  return '$text lots';
}

/// Fill defaults for a family so the spec is valid for the API.
ContractSpec specForFamily(String family, [ContractSpec? from]) {
  return ContractSpec(
    contractFamily: family,
    duration: family == 'RISE_FALL' ? (from?.duration ?? 5) : null,
    durationUnit: family == 'RISE_FALL' ? (from?.durationUnit ?? 'm') : null,
    allowEquals: family == 'RISE_FALL' ? (from?.allowEquals ?? false) : false,
    stake: family == 'SPOT' ? null : from?.stake,
    multiplier: family == 'MULTIPLIER' ? from?.multiplier : null,
    takeProfitAmount: family == 'MULTIPLIER' ? from?.takeProfitAmount : null,
    stopLossAmount: family == 'MULTIPLIER' ? from?.stopLossAmount : null,
  );
}

/// Families a symbol offers (no offer known = everything the account type can do).
List<String> availableFamilies(ContractOffer? offer, bool isDeriv) {
  if (offer == null) return isDeriv ? const ['RISE_FALL', 'MULTIPLIER'] : const ['RISE_FALL', 'MULTIPLIER', 'SPOT'];
  return [
    if (offer.riseFallAvailable) 'RISE_FALL',
    if (offer.multiplierAvailable) 'MULTIPLIER',
    if (offer.spotAvailable && !isDeriv) 'SPOT',
  ];
}

/// The starting contract: the strategy's suggestion when offered, else the broker's default.
ContractSpec initialContract(ContractSpec? suggested, ContractOffer? offer, bool isDeriv) {
  final families = availableFamilies(offer, isDeriv);
  final wanted = suggested?.contractFamily;
  if (wanted != null && families.contains(wanted)) {
    final spec = specForFamily(wanted, suggested);
    if (wanted == 'RISE_FALL' && offer != null && spec.duration != null && spec.durationUnit != null && !durationAllowed(spec.duration!, spec.durationUnit!, offer.durations)) {
      return specForFamily(wanted, offer.defaultContract.contractFamily == 'RISE_FALL' ? offer.defaultContract : const ContractSpec(contractFamily: 'RISE_FALL', duration: 5, durationUnit: 'm'));
    }
    if (wanted == 'MULTIPLIER' && offer != null && (spec.multiplier == null || !offer.multipliers.contains(spec.multiplier))) {
      return specForFamily(wanted, spec.copyWith(multiplier: () => offer.multipliers.isEmpty ? null : offer.multipliers.first));
    }
    return spec;
  }
  if (offer != null && families.contains(offer.defaultContract.contractFamily)) {
    return specForFamily(offer.defaultContract.contractFamily, offer.defaultContract);
  }
  return specForFamily(families.isEmpty ? 'SPOT' : families.first);
}

/// "900s" → "15 minutes", "1t" → "1 tick".
String humanDuration(String text) {
  final parsed = parseDuration(text);
  if (parsed == null) return text;
  var (n, unit) = parsed;
  if (unit == 's' && n % 60 == 0) (n, unit) = (n ~/ 60, 'm');
  if (unit == 'm' && n % 60 == 0) (n, unit) = (n ~/ 60, 'h');
  if (unit == 'h' && n % 24 == 0) (n, unit) = (n ~/ 24, 'd');
  return durationText(n, unit);
}

String rangesText(List<DurationRange> ranges) => ranges.map((r) => '${humanDuration(r.min)} – ${humanDuration(r.max)}').join(', ');

/// Client-side contract checks (the broker check on the server stays the authority).
Map<String, String> contractProblems(ContractSpec spec, ContractOffer? offer, {required bool isDeriv, double? maxStake}) {
  final out = <String, String>{};
  final families = availableFamilies(offer, isDeriv);
  if (!families.contains(spec.contractFamily)) out['contract_family'] = '${familyLabel[spec.contractFamily]} is not offered here.';
  if (spec.contractFamily == 'RISE_FALL') {
    if (spec.duration == null || spec.duration! < 1) {
      out['duration'] = 'Enter a whole number of at least 1.';
    } else if (offer != null && spec.durationUnit != null && !durationAllowed(spec.duration!, spec.durationUnit!, offer.durations)) {
      final ranges = rangesText(offer.durations);
      out['duration'] = 'Not offered on this symbol (allowed: ${ranges.isEmpty ? 'none' : ranges}).';
    }
    if (spec.allowEquals && offer != null && !offer.riseFallAllowEquals) out['allow_equals'] = '“Win on equal prices” is not offered here.';
  }
  if (spec.contractFamily == 'MULTIPLIER') {
    if (spec.multiplier == null) {
      out['multiplier'] = 'Choose a multiplier.';
    } else if (offer != null && !offer.multipliers.contains(spec.multiplier)) {
      out['multiplier'] = '×${spec.multiplier} is not offered here.';
    }
    final sl = toNumber(spec.stopLossAmount);
    final stake = toNumber(spec.stake);
    if (sl != null && stake != null && sl > stake) out['stop_loss_amount'] = "The stop loss can't be more than the stake (the most a contract can lose).";
    for (final entry in {'take_profit_amount': spec.takeProfitAmount, 'stop_loss_amount': spec.stopLossAmount}.entries) {
      final v = entry.value;
      if (v != null && v.isNotEmpty && !((toNumber(v) ?? 0) > 0)) out[entry.key] = 'Enter an amount above 0, or leave it empty.';
    }
  }
  if (spec.contractFamily != 'SPOT' && spec.stake != null && spec.stake!.isNotEmpty) {
    final stake = toNumber(spec.stake) ?? 0;
    if (!(stake > 0)) {
      out['stake'] = 'Enter a stake above 0, or leave it empty to use your risk profile.';
    } else if (maxStake != null && maxStake > 0 && stake > maxStake) {
      out['stake'] = 'Your risk profile allows at most ${formatNumber(maxStake)} per trade.';
    }
  }
  return out;
}
