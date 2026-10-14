import 'package:flutter_test/flutter_test.dart';
import 'package:intl/intl.dart';
import 'package:twokpilot/core/contracts.dart';
import 'package:twokpilot/core/format.dart';
import 'package:twokpilot/core/history_filters.dart';
import 'package:twokpilot/core/models/models.dart';
import 'package:twokpilot/core/risk_form.dart';
import 'package:twokpilot/core/status.dart';

import 'helpers.dart';

TradingStatus ts({String mode = 'DEMO', bool kill = true, bool locked = true, bool halted = false, String? haltReason, String? killReason, String engine = 'offline', Map<String, Object?>? summary}) {
  final j = tradingStatus(mode: mode, kill: kill, locked: locked, halted: halted, engine: engine, summary: summary);
  return TradingStatus.fromJson({...j, 'platform_halt_reason': haltReason, 'kill_switch_reason': killReason, 'engine_detail': ''});
}

Map<String, Object?> summary({String code = 'running', String tone = 'ok', String label = 'Engine running', String message = 'Automated trading is active.', bool active = true}) =>
    {'code': code, 'tone': tone, 'label': label, 'message': message, 'trading_active': active};

void main() {
  setUpAll(() => Intl.defaultLocale = 'en_US');

  group('money and P/L formatting (ported from format.test.ts)', () {
    test('never invents numbers for missing values', () {
      expect(formatMoney(null), '—');
      expect(formatPnl(null), '—');
      expect(formatPct(''), '—');
      expect(formatPrice('not-a-number'), '—');
    });

    test('signs P/L with a true minus', () {
      expect(formatPnl('12.5'), '+12.50');
      expect(formatPnl(-3.2), '−3.20');
      expect(formatPnl(0), '0.00');
    });

    test('uses symbol precision for prices', () {
      expect(formatPrice('1.085', 'EURUSD'), '1.08500');
      expect(formatPrice('151.7', 'USDJPY'), '151.700');
      expect(formatPrice('48215.33', 'R_75'), '48215.3300');
    });

    test('classifies P/L tone and humanizes keys', () {
      expect(pnlTone('1'), PnlTone.positive);
      expect(pnlTone(-1), PnlTone.negative);
      expect(pnlTone(null), PnlTone.neutral);
      expect(humanize('NEW_YORK'), 'New york');
      expect(formatPct(12.345, digits: 1, signed: true), '+12.3%');
    });

    test('formats money in the account currency (decimal strings in)', () {
      expect(formatCurrency('1234.5', 'USD'), r'$1,234.50');
      expect(formatCurrency(-3, 'USD'), r'-$3.00');
      expect(formatCurrency(null, 'USD'), '—');
      expect(formatCurrency(10, 'XXQ'), matches(RegExp(r'XXQ.*10\.00')));
      expect(formatCurrency(10, 'usd-ish'), '10.00 usd-ish');
    });

    test('signs currency with + and a true minus, never −\$0.00', () {
      expect(formatSignedCurrency(12.5, 'USD'), r'+$12.50');
      expect(formatSignedCurrency('-3.2', 'USD'), r'−$3.20');
      expect(formatSignedCurrency(0, 'USD'), r'$0.00');
      expect(formatSignedCurrency(-0.001, 'USD'), r'$0.00');
      expect(formatSignedCurrency(5, 'EUR'), '+€5.00');
    });

    test('formats durations and countdowns', () {
      expect(formatDuration(45), '45s');
      expect(formatDuration(310), '5m 10s');
      expect(formatDuration(7500), '2h 5m');
      expect(formatDuration(null), '—');
      final now = DateTime.parse('2026-10-10T12:00:00Z');
      expect(formatCountdown('2026-10-10T12:04:59Z', now: now), '4:59');
      expect(formatCountdown('2026-10-10T13:02:03Z', now: now), '1:02:03');
      expect(formatCountdown('2026-10-10T11:00:00Z', now: now), '0:00');
      expect(formatCountdown(null, now: now), isNull);
    });
  });

  group('deriveRobotStatus (ported from status.test.ts)', () {
    test('reports the kill switch first, with its reason', () {
      final r = deriveRobotStatus(ts(killReason: 'news'));
      expect([r.label, r.tone, r.detail, r.running], ['Trading stopped', Tone.warning, 'news', false]);
    });

    test('reports a platform halt above everything else', () {
      final r = deriveRobotStatus(ts(kill: false, engine: 'running', halted: true, haltReason: 'maintenance'));
      expect([r.label, r.tone, r.detail, r.running], ['Halted by admin', Tone.negative, 'maintenance', false]);
    });

    test('reports LIVE + hard lock as blocked even when the kill switch is released', () {
      final r = deriveRobotStatus(ts(kill: false, mode: 'LIVE'));
      expect(r.label, 'Blocked');
      expect(r.running, isFalse);
    });

    test("without a server summary, a missing heartbeat is not called 'Engine offline'", () {
      final r = deriveRobotStatus(ts(kill: false));
      expect([r.label, r.tone, r.running], ['Supervisor not running', Tone.warning, false]);
    });

    test('reports running and degraded engines', () {
      final running = deriveRobotStatus(ts(kill: false, engine: 'running'));
      expect([running.label, running.running], ['Running', true]);
      expect(deriveRobotStatus(ts(kill: false, engine: 'degraded')).tone, Tone.warning);
    });
  });

  group('engineHealthView (ported from status.test.ts)', () {
    test('API healthy but supervisor disabled: online, trading disabled, calm', () {
      final s = ts(kill: false, summary: summary(code: 'trading_disabled', tone: 'info', label: 'Engine online — automated trading disabled', message: 'The engine is healthy, but automated trading is switched off on this server.', active: false));
      final v = engineHealthView(s);
      expect([v.label, v.tone, v.active, v.banner], ['Engine online — automated trading disabled', Tone.info, false, true]);
      final r = deriveRobotStatus(s);
      expect(r.label, 'Engine online — automated trading disabled');
      expect(r.running, isFalse);
      expect(r.label.toLowerCase(), isNot(contains('offline')));
    });

    test('active supervisor: running, no banner', () {
      final s = ts(kill: false, engine: 'running', summary: summary());
      final v = engineHealthView(s);
      expect([v.active, v.banner, v.tone], [true, false, Tone.positive]);
      expect(deriveRobotStatus(s).label, 'Running');
    });

    test('stale heartbeat: a warning, not offline', () {
      final s = ts(kill: false, summary: summary(code: 'supervisor_stale', tone: 'warning', label: 'Trading supervisor not responding', message: 'No heartbeat since 10:00 UTC.', active: false));
      final v = engineHealthView(s);
      expect([v.tone, v.active, v.banner], [Tone.warning, false, true]);
      final r = deriveRobotStatus(s);
      expect([r.label, r.tone, r.running], ['Trading supervisor not responding', Tone.warning, false]);
    });

    test("unreachable API: the only case called 'Engine offline'", () {
      final s = ts(kill: false, summary: summary(code: 'engine_offline', tone: 'error', label: 'Engine offline', message: 'The trading engine cannot be reached.', active: false));
      expect(engineHealthView(s).tone, Tone.negative);
      final r = deriveRobotStatus(s);
      expect([r.label, r.tone, r.running], ['Engine offline', Tone.negative, false]);
    });

    test('kill switches and the platform halt still take precedence', () {
      final disabled = summary(code: 'trading_disabled', tone: 'info', label: 'Engine online — automated trading disabled', active: false);
      expect(deriveRobotStatus(ts(summary: disabled)).label, 'Trading stopped');
      expect(deriveRobotStatus(ts(halted: true, summary: disabled)).label, 'Halted by admin');
    });

    test('Start shows only when the status is known and trading is stopped', () {
      expect(showsStart(ts(kill: true), false), isTrue);
      expect(showsStart(ts(kill: false), false), isFalse);
      expect(showsStart(ts(kill: true), true), isFalse, reason: 'unknown status → Stop (always safe)');
      expect(showsStart(null, false), isFalse);
    });
  });

  group('history filters (ported from filters.test.ts)', () {
    final now = DateTime.parse('2026-10-10T15:30:00Z');

    test('leaves empty filters out of the query', () {
      expect(historyQuery(HistoryFilters.empty), isEmpty);
      expect(historyQuery(HistoryFilters.empty, {'page': 2, 'per_page': 50}), {'page': 2, 'per_page': 50});
    });

    test('maps every filter to the API parameter', () {
      final q = historyQuery(const HistoryFilters(from: '2026-10-01', to: '2026-10-10', accountId: 'acc-1', strategyId: 'str-9', outcome: OutcomeFilter.loss));
      expect(q, {'account_id': 'acc-1', 'strategy_id': 'str-9', 'from': '2026-10-01', 'to': '2026-10-10', 'outcome': 'loss'});
    });

    test('ignores malformed dates', () {
      expect(historyQuery(const HistoryFilters(from: '10/01/2026', to: 'yesterday')), isEmpty);
    });

    test('builds the CSV export path with the current filters', () {
      expect(exportPath(HistoryFilters.empty), '/history/export?format=csv');
      final path = exportPath(const HistoryFilters(from: '2026-10-01', accountId: 'a b', outcome: OutcomeFilter.win));
      final uri = Uri.parse(path);
      expect(uri.queryParameters, {'format': 'csv', 'account_id': 'a b', 'from': '2026-10-01', 'outcome': 'win'});
    });

    test('computes preset ranges in UTC days', () {
      expect(presetRange(RangePreset.today, now: now), (from: '2026-10-10', to: '2026-10-10'));
      expect(presetRange(RangePreset.d7, now: now), (from: '2026-10-04', to: '2026-10-10'));
      expect(presetRange(RangePreset.d30, now: now), (from: '2026-09-11', to: '2026-10-10'));
      expect(presetRange(RangePreset.all, now: now), (from: '', to: ''));
    });

    test('recognises presets and custom ranges', () {
      expect(detectPreset(const HistoryFilters(from: '2026-10-04', to: '2026-10-10'), now: now), RangePreset.d7);
      expect(detectPreset(HistoryFilters.empty, now: now), RangePreset.all);
      expect(detectPreset(const HistoryFilters(from: '2026-01-01', to: '2026-02-01'), now: now), RangePreset.custom);
    });

    test('flags an inverted range', () {
      expect(rangeProblem(const HistoryFilters(from: '2026-10-10', to: '2026-10-01')), contains('after'));
      expect(rangeProblem(const HistoryFilters(from: '2026-10-01', to: '2026-10-10')), isNull);
    });

    test('counts the extra filters for the badge', () {
      expect(const HistoryFilters(accountId: 'a', outcome: OutcomeFilter.win).extraCount, 2);
    });
  });

  group('contracts', () {
    test('plain-English summaries and directions', () {
      const spec = ContractSpec(contractFamily: 'RISE_FALL', duration: 25, durationUnit: 'm', stake: '1');
      expect(contractSummary(spec, currency: 'USD'), r'Rise/Fall · 25 minutes · stake $1.00');
      expect(directionLabel(side: 'BUY', contractType: 'PUT'), 'Fall');
      expect(directionLabel(side: 'SELL', contractFamily: 'MULTIPLIER'), 'Down');
      expect(humanDuration('900s'), '15 minutes');
    });

    test('checks durations against the broker ranges', () {
      const ranges = [DurationRange('1t', '10t'), DurationRange('15s', '1d')];
      expect(durationAllowed(5, 't', ranges), isTrue);
      expect(durationAllowed(10, 's', ranges), isFalse);
      expect(durationAllowed(5, 'm', ranges), isTrue);
    });
  });

  group('risk profile form', () {
    test('trims decimals and sends empty limits as null', () {
      expect(trimDecimal('2.000'), '2');
      expect(trimDecimal('0.500'), '0.5');
      final form = ProfileForm.from(null)..name = ' Mine ';
      form.values['max_stake_amount'] = '';
      form.values['stake_amount'] = '2,5';
      final body = form.toBody();
      expect(body['name'], 'Mine');
      expect(body['max_stake_amount'], isNull);
      expect(body['stake_amount'], '2.5');
    });
  });
}
