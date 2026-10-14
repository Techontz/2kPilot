/// DEBUG-ONLY fake backend (`--dart-define=DEMO_DATA=true`) used for
/// screenshots, golden tests and UI work without a server. It never touches
/// the network and is never enabled in release builds (AppConfig.demoData is
/// constant-false there).
library;

import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../state/providers.dart';
import '../auth/secure_store.dart';

const String demoScenario = String.fromEnvironment('DEMO_SCENARIO');

List<Override> demoOverrides({String scenario = demoScenario, DateTime? now, Duration latency = const Duration(milliseconds: 120), DemoBackend? backend, Map<String, String> store = const {}}) {
  backend ??= DemoBackend(scenario: scenario, now: now, latency: latency);
  return [
    httpAdapterProvider.overrideWithValue(backend),
    secureStoreProvider.overrideWithValue(MemorySecureStore({
      StoreKeys.token: 'demo-token',
      StoreKeys.user: jsonEncode(backend.user),
      StoreKeys.account: scenario == 'live' ? 'acc-live' : 'acc-demo',
      StoreKeys.pushAsked: '1',
      ...store,
    })),
  ];
}

class DemoBackend implements HttpClientAdapter {
  DemoBackend({this.scenario = '', DateTime? now, this.latency = const Duration(milliseconds: 120)}) : now = (now ?? DateTime.now()).toUtc() {
    _status = {
      ..._baseStatus,
      'trading_mode': scenario == 'live' ? 'LIVE' : 'DEMO',
      'kill_switch_engaged': scenario == 'stopped',
      'live_trading_locked': false,
    };
  }

  final String scenario;
  final DateTime now;
  final Duration latency;

  /// Every request seen (method + path), for tests.
  final List<String> requests = [];
  final List<Object?> bodies = [];
  late Map<String, Object?> _status;

  String _t(Duration ago) => now.subtract(ago).toIso8601String();
  String _in(Duration d) => now.add(d).toIso8601String();

  Map<String, Object?> get user => {
        'id': 'u-1',
        'name': 'Amani Mushi',
        'email': 'amani@example.com',
        'role': 'user',
        'mfa_enabled': true,
        'mfa_required': false,
        'last_login_at': _t(const Duration(hours: 2)),
      };

  static const _engineOk = {'code': 'running', 'tone': 'ok', 'label': 'Engine running', 'message': 'Automated trading is active.', 'trading_active': true};

  Map<String, Object?> get _baseStatus => {
        'trading_mode': 'DEMO',
        'kill_switch_engaged': false,
        'kill_switch_reason': null,
        'live_trading_locked': false,
        'live_authorized_at': scenario == 'live' ? _t(const Duration(days: 2)) : null,
        'platform_halted': false,
        'platform_halt_reason': null,
        'engine_state': 'running',
        'engine_detail': 'Heartbeat 4 s ago',
        'engine_heartbeat_at': _t(const Duration(seconds: 4)),
        'new_orders_permitted': true,
        'engine_summary': _engineOk,
        'engine_service': {'status': 'online', 'reachable': true, 'supervisor_enabled': true, 'version': '2.4.1', 'checked_at': _t(Duration.zero), 'detail': null},
        'engine_supervisor': {'state': 'running', 'heartbeat_at': _t(const Duration(seconds: 4)), 'detail': 'Heartbeat 4 s ago'},
      };

  Map<String, Object?> _account(String id, String label, String env, String connector, String broker, String balance, {String? profile = 'rp-1', bool trading = true}) => {
        'id': id,
        'label': label,
        'broker': broker,
        'connector_type': connector,
        'connection_id': 'conn-$id',
        'connection_status': 'CONNECTED',
        'connection_detail': null,
        'connection_enabled': true,
        'last_connected_at': _t(const Duration(hours: 5)),
        'broker_account_id': connector == 'paper' ? 'PAPER-001' : (env == 'LIVE' ? 'CR4471902' : 'VRTC9821443'),
        'name': label,
        'server': connector == 'paper' ? '' : 'Deriv',
        'environment': env,
        'currency': 'USD',
        'leverage': null,
        'balance': balance,
        'equity': balance,
        'margin': null,
        'free_margin': null,
        'trading_enabled': trading,
        'risk_profile': profile == null ? null : {'id': profile, 'name': profile == 'rp-1' ? 'Beginner' : 'Careful'},
        'active_strategies': ['Adaptive Trend & Momentum'],
        'capabilities': {'historical_candles': connector != 'paper', 'pending_orders': false},
        'synced_at': _t(const Duration(seconds: 40)),
        'created_at': _t(const Duration(days: 40)),
      };

  List<Map<String, Object?>> get accounts => [
        _account('acc-demo', 'Deriv demo', 'DEMO', 'deriv', 'Deriv', '10482.35'),
        _account('acc-paper', 'Paper practice', 'PAPER', 'paper', 'Paper (simulated)', '5000.00', trading: false),
        _account('acc-live', 'Deriv real', 'LIVE', 'deriv', 'Deriv', '250.00', profile: 'rp-2'),
      ];

  Map<String, Object?> _accRef(String id) {
    final a = accounts.firstWhere((a) => a['id'] == id);
    return {'id': id, 'label': a['label'], 'environment': a['environment'], 'currency': 'USD'};
  }

  Map<String, Object?> _trade(String id, {required String symbol, required String type, required String family, required bool open, required Duration ago, String? pnl, String stake = '5.00', String? outcome, int? multiplier, String account = 'acc-demo', String strategy = 'Adaptive Trend & Momentum'}) {
    final side = type.startsWith('PUT') || type == 'MULTDOWN' ? 'SELL' : 'BUY';
    final entry = now.subtract(ago);
    final held = family == 'RISE_FALL' ? 300 : 1800 + (id.hashCode % 3000).abs();
    return {
      'id': id,
      'account': _accRef(account),
      'strategy': strategy,
      'strategy_version': 3,
      'source': 'STRATEGY',
      'symbol': symbol,
      'side': side,
      'status': open ? 'OPEN' : 'CLOSED',
      'volume': '1',
      'entry_price': symbol == 'frxEURUSD' ? '1.08412' : '48215.3310',
      'entry_time': entry.toIso8601String(),
      'stop_loss': null,
      'take_profit': null,
      'exit_price': open ? null : '48302.1180',
      'exit_time': open ? null : entry.add(Duration(seconds: held)).toIso8601String(),
      'exit_reason': open ? null : (family == 'RISE_FALL' ? 'EXPIRED' : 'TAKE_PROFIT'),
      'net_pnl': open ? null : pnl,
      'unrealized_pnl': open ? pnl : null,
      'commission': '0.00',
      'is_simulated': false,
      'contract_family': family,
      'contract_type': type,
      'broker_contract_id': '2489${id.hashCode.abs() % 100000}',
      'stake': stake,
      'payout': family == 'RISE_FALL' ? '9.75' : null,
      'multiplier': multiplier,
      'duration': family == 'RISE_FALL' ? 5 : null,
      'duration_unit': family == 'RISE_FALL' ? 'm' : null,
      'expires_at': family == 'RISE_FALL' ? entry.add(const Duration(minutes: 5)).toIso8601String() : null,
      'entry_spot': null,
      'exit_spot': null,
      'fees': family == 'MULTIPLIER' ? '0.12' : '0.00',
      'outcome': open ? 'OPEN' : outcome,
      'longcode': family == 'RISE_FALL'
          ? 'Win payout if Volatility 75 Index is strictly ${side == 'BUY' ? 'higher' : 'lower'} than entry spot at 5 minutes after contract start time.'
          : null,
      'duration_seconds': open ? null : held,
    };
  }

  List<Map<String, Object?>> get positions => [
        _trade('t-open-1', symbol: 'R_75', type: 'CALL', family: 'RISE_FALL', open: true, ago: const Duration(minutes: 2, seconds: 10), pnl: '3.80'),
        _trade('t-open-2', symbol: 'R_100', type: 'MULTDOWN', family: 'MULTIPLIER', open: true, ago: const Duration(minutes: 41), pnl: '-1.42', multiplier: 100, stake: '10.00'),
      ];

  List<Map<String, Object?>> get closed {
    final out = <Map<String, Object?>>[];
    final rnd = math.Random(7);
    for (var i = 0; i < 14; i++) {
      final won = rnd.nextDouble() > 0.42;
      final rf = i % 3 != 2;
      out.add(_trade(
        't-$i',
        symbol: i % 4 == 0 ? 'R_100' : 'R_75',
        type: rf ? (i.isEven ? 'CALL' : 'PUT') : (i.isEven ? 'MULTUP' : 'MULTDOWN'),
        family: rf ? 'RISE_FALL' : 'MULTIPLIER',
        open: false,
        ago: Duration(hours: 3 + i * 7),
        pnl: rf ? (won ? '4.75' : '-5.00') : (won ? '6.${10 + i}' : '-3.${20 + i}'),
        outcome: rf ? (won ? 'WON' : 'LOST') : 'SOLD',
        multiplier: rf ? null : 100,
      ));
    }
    return out;
  }

  Map<String, Object?> get overview {
    final live = scenario == 'live';
    final accId = live ? 'acc-live' : 'acc-demo';
    final a = accounts.firstWhere((x) => x['id'] == accId);
    final rnd = math.Random(3);
    var balance = live ? 220.0 : 10150.0;
    final daily = <Map<String, Object?>>[];
    final history = <Map<String, Object?>>[];
    for (var d = 29; d >= 0; d--) {
      final trades = rnd.nextInt(6);
      final pnl = trades == 0 ? 0.0 : ((rnd.nextDouble() - 0.38) * (live ? 6 : 38));
      balance += pnl;
      final day = now.subtract(Duration(days: d));
      daily.add({'date': day.toIso8601String().substring(0, 10), 'net_pnl': double.parse(pnl.toStringAsFixed(2)), 'trades': trades});
      history.add({'t': day.toIso8601String(), 'balance': double.parse(balance.toStringAsFixed(2)), 'equity': double.parse(balance.toStringAsFixed(2))});
    }
    return {
      'account': {...a, 'risk_profile': (a['risk_profile'] as Map?)?['name'], 'risk_profile_id': (a['risk_profile'] as Map?)?['id']},
      'broker': {'name': 'Deriv', 'connector_type': 'deriv', 'connection_status': 'CONNECTED', 'connection_detail': null, 'last_connected_at': _t(const Duration(hours: 5))},
      'active_strategies': [
        {
          'assignment_id': 'as-1',
          'strategy_id': 's-adaptive',
          'strategy': 'Adaptive Trend & Momentum',
          'version': 3,
          'symbol': 'R_75',
          'contract': {'contract_family': 'RISE_FALL', 'duration': 5, 'duration_unit': 'm', 'allow_equals': false, 'stake': null, 'multiplier': null, 'take_profit_amount': null, 'stop_loss_amount': null},
          'contract_summary': 'Rise/Fall · 5 minutes · stake \$5.00 (risk profile)',
          'status_reason': null,
          'last_bar_evaluated': _t(const Duration(minutes: 1)),
          'last_signal_at': _t(const Duration(minutes: 2)),
        },
        {
          'assignment_id': 'as-2',
          'strategy_id': 's-ema',
          'strategy': 'EMA crossover',
          'version': 1,
          'symbol': 'R_100',
          'contract': {'contract_family': 'MULTIPLIER', 'duration': null, 'duration_unit': null, 'allow_equals': false, 'stake': '10.00', 'multiplier': 100, 'take_profit_amount': null, 'stop_loss_amount': null},
          'contract_summary': 'Multiplier · ×100 · stake \$10.00',
          'status_reason': null,
          'last_bar_evaluated': _t(const Duration(minutes: 3)),
          'last_signal_at': _t(const Duration(minutes: 41)),
        },
      ],
      'blockers': _status['kill_switch_engaged'] == true ? [{'code': 'trading_stopped', 'message': 'Trading is stopped. Press Start to let your active strategies trade.'}] : <Object>[],
      'daily_pnl': daily,
      'balance_history': history,
      'setup': {'has_broker': true, 'has_account': true, 'has_strategy': true, 'has_backtest': true, 'has_active_strategy': true, 'trading_started': true, 'mfa_enabled': true},
      'figures': {
        'balance': double.parse(a['balance'] as String),
        'equity': double.parse(a['balance'] as String),
        'today_pnl': live ? 3.75 : 27.40,
        'total_pnl': live ? -12.10 : 482.35,
        'open_pnl': 2.38,
        'open_positions': 2,
        'drawdown_pct': 1.2,
        'max_drawdown_pct': 4.8,
        'risk_used_pct': null,
        'max_total_risk_pct': null,
        'daily_loss_pct': null,
        'max_daily_loss_pct': 2,
        'active_strategies': 2,
      },
      'robot': _status,
      'positions': positions.map((p) => {...p, 'account': _accRef(accId)}).toList(),
    };
  }

  Map<String, Object?> _contract(String family, {int? multiplier, String? stake}) => {
        'contract_family': family,
        'duration': family == 'RISE_FALL' ? 5 : null,
        'duration_unit': family == 'RISE_FALL' ? 'm' : null,
        'allow_equals': false,
        'stake': stake,
        'multiplier': multiplier,
        'take_profit_amount': null,
        'stop_loss_amount': null,
      };

  Map<String, Object?> get _validation => {
        'qualifies_for_demo_forward_testing': true,
        'checks': [
          {'name': 'Enough trades', 'passed': true, 'detail': '214 trades (minimum 100)'},
          {'name': 'Out-of-sample profit factor', 'passed': true, 'detail': '1.18 (minimum 1.05)'},
          {'name': 'Drawdown', 'passed': true, 'detail': '6.2% (maximum 15%)'},
        ],
        'reasons': <String>[],
        'note': 'Qualifying only means it may be forward-tested on a demo account — it is not a claim of profit.',
      };

  List<Map<String, Object?>> get strategies {
    Map<String, Object?> strat(String id, String key, String name, String desc, {bool builtIn = false, String source = 'copy', String? difficulty, List<Map<String, Object?>> assignments = const [], Map<String, Object?>? backtest, String? rulesText, Map<String, Object?>? params}) => {
          'id': id,
          'key': key,
          'name': name,
          'description': desc,
          'summary': null,
          'details': {
            'how_it_works': 'It follows the trend on closed candles and only enters when momentum agrees, so it sits out choppy markets.',
            'struggles': 'Sudden reversals and very quiet markets, where trends never get going.',
            'difficulty': difficulty ?? 'beginner',
            'suggested_symbols': ['R_75', 'R_100'],
            'suggested_timeframe': 'M5',
            'suggested_contract': _contract('RISE_FALL'),
          },
          'source': source,
          'built_in': builtIn,
          'editable': true,
          'code_version': '3',
          'parameter_schema': {
            'properties': {
              'fast_period': {'title': 'Fast average', 'description': 'Candles in the fast moving average.'},
              'slow_period': {'title': 'Slow average', 'description': 'Candles in the slow moving average.'},
            },
          },
          'latest_version': {'id': 'v-$id', 'version': 3, 'code_version': '3', 'parameters': params ?? {'timeframe': 'M5'}, 'rules_text': rulesText, 'notes': '', 'created_at': _t(const Duration(days: 8))},
          'rules_text': rulesText,
          'versions': <Object>[],
          'assignments': assignments,
          'performance': {
            'demo': {'trades': builtIn ? 0 : 86, 'wins': 49, 'win_rate': 57.0, 'net_pnl': 412.6, 'net_pnl_30d': 96.4, 'last_trade_at': _t(const Duration(minutes: 42))},
            'live': null,
          },
          'backtest': backtest,
          'backtests_by_symbol': backtest == null ? null : [backtest, {...backtest, 'id': 'bt-2', 'symbol': 'R_100', 'net_pnl': 88.2, 'win_rate': 54.1, 'trades': 176}],
          'contract_families': key == 'rules' ? null : ['RISE_FALL', 'MULTIPLIER', 'SPOT'],
          'symbols': null,
          'entries_disabled': null,
          'live_trades': 0,
          'live_net_pnl': 0,
          'last_backtest': null,
        };
    final headline = {
      'id': 'bt-1',
      'name': 'Adaptive Trend & Momentum · R_75 M5',
      'symbol': 'R_75',
      'timeframe': 'M5',
      'net_pnl': 214.5,
      'return_pct': 21.45,
      'win_rate': 56.5,
      'trades': 214,
      'max_drawdown': 62.3,
      'max_drawdown_pct': 6.2,
      'contract_family': 'RISE_FALL',
      'run_at': _t(const Duration(days: 1)),
      'data_source': 'broker',
      'profit_factor': 1.18,
      'expectancy': 1.0,
      'by_regime': [
        {'key': 'TREND_UP', 'trades': 88, 'wins': 55, 'win_rate': 62.5, 'net_pnl': 160.2, 'profit_factor': 1.4, 'expectancy': 1.82, 'longest_losing_streak': 3},
        {'key': 'SIDEWAYS', 'trades': 61, 'wins': 29, 'win_rate': 47.5, 'net_pnl': -38.4, 'profit_factor': 0.88, 'expectancy': -0.63, 'longest_losing_streak': 5},
      ],
      'validation': _validation,
    };
    return [
      strat('s-adaptive', 'adaptive_trend', 'Adaptive Trend & Momentum', 'Trades with the trend when momentum confirms it; stands aside in sideways markets.',
          source: 'code',
          builtIn: false,
          backtest: headline,
          params: {'timeframe': 'M5', 'fast_period': 9, 'slow_period': 21, 'risk_per_trade_pct': 1, 'max_open_positions': 2},
          assignments: [
            {
              'id': 'as-1',
              'strategy_id': 's-adaptive',
              'strategy_version_id': 'v-s-adaptive',
              'version': 3,
              'account': {'id': 'acc-demo', 'label': 'Deriv demo', 'environment': 'DEMO', 'connector_type': 'deriv'},
              'symbol': 'R_75',
              'contract': _contract('RISE_FALL'),
              'status': 'ENABLED',
              'status_reason': null,
              'last_bar_evaluated': _t(const Duration(minutes: 1)),
              'last_signal_at': _t(const Duration(minutes: 2)),
            },
          ]),
      strat('s-ema', 'rules', 'EMA crossover', 'Buy when the fast average crosses above the slow one.',
          rulesText: 'Buy when EMA(9) crosses above EMA(21). Sell when EMA(9) crosses below EMA(21). Stop: 2 × ATR(14). Target: 1.5 × the risk.',
          assignments: [
            {
              'id': 'as-2',
              'strategy_id': 's-ema',
              'strategy_version_id': 'v-s-ema',
              'version': 1,
              'account': {'id': 'acc-demo', 'label': 'Deriv demo', 'environment': 'DEMO', 'connector_type': 'deriv'},
              'symbol': 'R_100',
              'contract': _contract('MULTIPLIER', multiplier: 100, stake: '10.00'),
              'status': 'ENABLED',
              'status_reason': null,
              'last_bar_evaluated': _t(const Duration(minutes: 3)),
              'last_signal_at': _t(const Duration(minutes: 41)),
            },
          ]),
      strat('tpl-rsi', 'rules', 'RSI reversal', 'Buys oversold dips and sells overbought spikes.', builtIn: true, source: 'template', difficulty: 'beginner', rulesText: 'Buy when RSI(14) crosses above 30. Sell when RSI(14) crosses below 70.'),
      strat('tpl-boll', 'rules', 'Bollinger bounce', 'Fades moves to the outer bands back toward the middle.', builtIn: true, source: 'template', difficulty: 'intermediate', rulesText: 'Buy when the close is below the lower Bollinger band. Sell when the close is above the upper band.'),
      strat('tpl-break', 'rules', 'Range breakout', 'Joins strong moves out of a quiet range.', builtIn: true, source: 'template', difficulty: 'advanced', rulesText: 'Buy when the close breaks the highest high of 20 candles. Sell when it breaks the lowest low.'),
      strat('tpl-ema', 'rules', 'EMA crossover', 'Two moving averages; trade when they cross.', builtIn: true, source: 'template', difficulty: 'beginner', rulesText: 'Buy when EMA(9) crosses above EMA(21). Sell when EMA(9) crosses below EMA(21).'),
    ];
  }

  Map<String, Object?> get backtest {
    final rnd = math.Random(11);
    var eq = 1000.0, peak = 1000.0;
    final curve = <Map<String, Object?>>[];
    final dd = <Map<String, Object?>>[];
    for (var i = 0; i < 120; i++) {
      eq += (rnd.nextDouble() - 0.44) * 12;
      peak = math.max(peak, eq);
      final t = now.subtract(Duration(hours: (120 - i) * 6)).toIso8601String();
      curve.add({'t': t, 'equity': double.parse(eq.toStringAsFixed(2))});
      dd.add({'t': t, 'dd': double.parse((-(peak - eq) / peak * 100).toStringAsFixed(2))});
    }
    return {
      'id': 'bt-1',
      'name': 'Adaptive Trend & Momentum · R_75 M5',
      'kind': 'SINGLE',
      'status': 'COMPLETED',
      'strategy_key': 'adaptive_trend',
      'symbol': 'R_75',
      'timeframe': 'M5',
      'data_source': 'broker',
      'start': _t(const Duration(days: 30)),
      'end': _t(Duration.zero),
      'initial_capital': '1000.00',
      'progress': 100,
      'metrics': {
        'starting_balance': 1000,
        'ending_balance': 1214.5,
        'net_pnl': 214.5,
        'return_pct': 21.45,
        'trades': 214,
        'wins': 121,
        'losses': 93,
        'win_rate': 56.5,
        'expectancy': 1.0,
        'profit_factor': 1.18,
        'max_drawdown': 62.3,
        'max_drawdown_pct': 6.2,
        'max_consecutive_wins': 7,
        'max_consecutive_losses': 5,
        'longest_losing_streak': 5,
        'total_costs': 0,
        'avg_holding_hours': 0.083,
        'equity_curve': curve,
        'drawdown_curve': dd,
        'monthly': [
          {'month': '2026-08', 'net_pnl': 64.2, 'trades': 70, 'return_pct': 6.4},
          {'month': '2026-09', 'net_pnl': -12.6, 'trades': 68, 'return_pct': -1.2},
          {'month': '2026-10', 'net_pnl': 162.9, 'trades': 76, 'return_pct': 15.1},
        ],
        'by_symbol': <Object>[],
        'by_session': <Object>[],
        'by_side': <Object>[],
        'by_strategy': <Object>[],
        'by_regime': (strategies.first['backtest'] as Map)['by_regime'],
        'outcomes': {'WON': 121, 'LOST': 93},
        'payout_ratio': 0.95,
        'payout_ratio_is_estimate': true,
        'notes': <String>[],
      },
      'report': {
        'warnings': ['Payouts are an ESTIMATE (0.95). Real Rise/Fall payouts vary with every quote.'],
        'validation': _validation,
      },
      'config': {'contract': _contract('RISE_FALL', stake: '5.00')},
      'error': null,
      'created_at': _t(const Duration(days: 1)),
      'finished_at': _t(const Duration(days: 1)),
    };
  }

  Map<String, Object?> get notifications => {
        'data': [
          {'id': 9, 'type': 'trade.closed', 'severity': 'success', 'title': 'Trade won: R_75 Rise', 'message': 'Rise/Fall on Deriv demo finished with +\$4.75.', 'account_id': 'acc-demo', 'data': {'trade_id': 't-0'}, 'created_at': _t(const Duration(minutes: 7)), 'read_at': null},
          {'id': 8, 'type': 'risk.limit', 'severity': 'warning', 'title': 'Daily loss limit close', 'message': 'Deriv demo has used 75% of its daily loss limit.', 'account_id': 'acc-demo', 'data': <String, Object>{}, 'created_at': _t(const Duration(hours: 1)), 'read_at': null},
          {'id': 7, 'type': 'broker.reconnected', 'severity': 'info', 'title': 'Deriv reconnected', 'message': 'The connection to Deriv is back after 12 seconds.', 'account_id': null, 'data': <String, Object>{}, 'created_at': _t(const Duration(hours: 5)), 'read_at': null},
          {'id': 6, 'type': 'trade.closed', 'severity': 'info', 'title': 'Trade lost: R_75 Fall', 'message': 'Rise/Fall on Deriv demo finished with −\$5.00.', 'account_id': 'acc-demo', 'data': {'trade_id': 't-1'}, 'created_at': _t(const Duration(hours: 9)), 'read_at': _t(const Duration(hours: 8))},
        ],
        'current_page': 1,
        'last_page': 1,
        'per_page': 100,
        'total': 4,
      };

  Map<String, Object?> _profile(String id, String name, String stake, String maxStake, int? streak, String? dailyPct) => {
        'id': id,
        'name': name,
        'risk_per_trade_pct': '0.500',
        'max_position_lots': null,
        'max_open_positions': 3,
        'max_positions_per_symbol': null,
        'max_symbol_exposure_lots': null,
        'max_total_exposure_lots': null,
        'max_total_risk_pct': null,
        'max_daily_loss_pct': dailyPct,
        'max_weekly_loss_pct': '4.000',
        'max_drawdown_pct': '10.000',
        'max_trades_per_day': 20,
        'max_spread_pips': '2.500',
        'max_slippage_pips': null,
        'min_stop_pips': '8.000',
        'max_stop_pips': '150.000',
        'min_reward_risk': '1.500',
        'allowed_sessions': ['LONDON', 'OVERLAP', 'NEW_YORK'],
        'trading_hours_start': null,
        'trading_hours_end': null,
        'cooldown_after_losses': null,
        'cooldown_minutes': null,
        'max_data_age_seconds': 120,
        'stake_amount': stake,
        'max_stake_amount': maxStake,
        'max_daily_loss_amount': '50.00',
        'max_consecutive_losses': streak,
        'daily_profit_target_amount': null,
        'min_account_balance': null,
        'accounts_count': id == 'rp-1' ? 2 : 1,
      };

  Object? route(String method, String path, Map<String, dynamic> query, Object? body) {
    final b = body is Map ? body : const {};
    switch ((method, path)) {
      case ('GET', '/auth/me'):
        return {'user': user};
      case ('GET', '/trading/status'):
        return _status;
      case ('POST', '/trading/stop'):
        _status = {..._status, 'kill_switch_engaged': true, 'kill_switch_reason': b['reason']};
        return _status;
      case ('POST', '/trading/resume'):
        if (_status['trading_mode'] == 'LIVE' && b['live'] != true) return _Fail(422, 'live_confirmation_required', 'Confirm LIVE trading.');
        _status = {..._status, 'kill_switch_engaged': false, 'kill_switch_reason': null};
        return _status;
      case ('PUT', '/trading/mode'):
        if (b['mode'] == 'LIVE') return _Fail(403, 'live_requires_web', 'Real-money trading is authorised on the 2kPilot website.');
        _status = {..._status, 'trading_mode': 'DEMO', 'kill_switch_engaged': true};
        return _status;
      case ('POST', '/trading/close-positions'):
        return {'closed': 2, 'failed': <Object>[], 'status': {..._status, 'kill_switch_engaged': true}};
      case ('GET', '/accounts'):
        return accounts;
      case ('GET', '/notifications/unread-count'):
        return {'count': 3};
      case ('GET', '/overview'):
        return overview;
      case ('GET', '/positions'):
        return positions;
      case ('GET', '/history'):
        return {'data': closed, 'current_page': 1, 'last_page': 1, 'per_page': 50, 'total': closed.length};
      case ('GET', '/journal'):
        return {
          'data': [
            {'id': 5, 'occurred_at': _t(const Duration(minutes: 2)), 'event_type': 'ORDER_FILLED', 'message': 'Bought R_75 Rise for \$5.00 (Adaptive Trend & Momentum).'},
            {'id': 4, 'occurred_at': _t(const Duration(minutes: 2)), 'event_type': 'SIGNAL', 'message': 'Signal BUY on R_75: trend up, momentum confirms.'},
            {'id': 3, 'occurred_at': _t(const Duration(minutes: 20)), 'event_type': 'RISK_REJECTED', 'message': 'Skipped R_100 SELL: 3 trades already open (limit 3).'},
            {'id': 2, 'occurred_at': _t(const Duration(minutes: 41)), 'event_type': 'POSITION_CLOSED', 'message': 'R_75 Fall finished: lost \$5.00.'},
          ],
          'current_page': 1,
          'last_page': 1,
          'per_page': 100,
          'total': 4,
        };
      case ('GET', '/orders'):
        return {
          'data': [
            {'id': 'o-1', 'purpose': 'ENTRY', 'symbol': 'R_75', 'side': 'BUY', 'status': 'FILLED', 'fill_price': '48215.3310', 'broker_message': 'Contract bought', 'created_at': _t(const Duration(minutes: 2)), 'account': _accRef('acc-demo')},
            {'id': 'o-2', 'purpose': 'ENTRY', 'symbol': 'R_100', 'side': 'SELL', 'status': 'FILLED', 'fill_price': '1243.88', 'broker_message': null, 'created_at': _t(const Duration(minutes: 41)), 'account': _accRef('acc-demo')},
          ],
          'current_page': 1,
          'last_page': 1,
          'per_page': 100,
          'total': 2,
        };
      case ('GET', '/strategies'):
        return strategies;
      case ('GET', '/backtests'):
        final done = backtest;
        return [
          {...done, 'id': 'bt-3', 'name': 'EMA crossover · R_100 M15', 'status': 'RUNNING', 'progress': 64, 'metrics': null},
          done,
          {...done, 'id': 'bt-2', 'name': 'RSI reversal · R_75 M5', 'data_source': 'synthetic', 'metrics': {...(done['metrics'] as Map), 'net_pnl': -38.2, 'trades': 92, 'win_rate': 47.8}},
        ];
      case ('GET', '/risk/profiles'):
        return [_profile('rp-1', 'Beginner', '5.00', '10.00', 3, '2.000'), _profile('rp-2', 'Careful', '1.00', '2.00', 2, null)];
      case ('GET', '/system/status'):
        return {
          'app': '2kPilot',
          'environment': 'production',
          'database': 'ok',
          'trading': _status,
          'engine': {'status': 'ok', 'version': '2.4.1'},
          'live_trading_enabled': true,
          'broker_vault_configured': true,
          'deriv_app_id_configured': true,
          'mfa_required': false,
          'queue_connection': 'redis',
          'engine_service': _status['engine_service'],
          'engine_supervisor': _status['engine_supervisor'],
          'engine_summary': _engineOk,
        };
      case ('GET', '/auth/tokens'):
        return [
          {'id': 12, 'name': '2kPilot app · iPhone', 'created_at': _t(const Duration(days: 3)), 'last_used_at': _t(Duration.zero), 'expires_at': _in(const Duration(days: 27)), 'current': true},
          {'id': 9, 'name': '2kPilot app · Android', 'created_at': _t(const Duration(days: 20)), 'last_used_at': _t(const Duration(days: 4)), 'expires_at': _in(const Duration(days: 10)), 'current': false},
        ];
      case ('GET', '/markets/instruments'):
        return {
          'instruments': [
            {'name': 'R_75', 'canonical': 'R_75', 'description': 'Volatility 75 Index', 'category': 'synthetic', 'digits': 4, 'trade_allowed': true, 'market_open': true},
            {'name': 'R_100', 'canonical': 'R_100', 'description': 'Volatility 100 Index', 'category': 'synthetic', 'digits': 2, 'trade_allowed': true, 'market_open': true},
            {'name': 'frxEURUSD', 'canonical': 'EURUSD', 'description': 'EUR/USD', 'category': 'forex', 'digits': 5, 'trade_allowed': true, 'market_open': true},
          ],
          'connection_status': 'CONNECTED',
          'simulated': false,
        };
      case ('GET', '/markets/contracts'):
        return {
          'account': _accRef('acc-demo'),
          'provider': 'Deriv',
          'symbol': query['symbol'],
          'simulated': false,
          'market_open': true,
          'trading_suspended': false,
          'families': {
            'RISE_FALL': {'available': true, 'contract_types': ['CALL', 'PUT'], 'allow_equals': true, 'durations': [{'expiry_type': 'tick', 'min': '1t', 'max': '10t'}, {'expiry_type': 'intraday', 'min': '15s', 'max': '1d'}]},
            'MULTIPLIER': {'available': true, 'contract_types': ['MULTUP', 'MULTDOWN'], 'multipliers': [50, 100, 200, 300]},
            'SPOT': {'available': false},
          },
          'default_contract': _contract('RISE_FALL'),
          'notes': <String>[],
        };
    }
    if (method == 'GET' && path.startsWith('/trades/')) {
      final id = path.substring('/trades/'.length);
      final t = [...positions, ...closed].firstWhere((t) => t['id'] == id, orElse: () => closed.first);
      return {
        'trade': t,
        'signal': {
          'id': 'sig-1',
          'side': t['side'],
          'bar_time': t['entry_time'],
          'reasons': ['Trend up on M5', 'Momentum confirms'],
          'status': 'EXECUTED',
          'rejection_reason': null,
          'risk_checks': [
            {'rule': 'Stake within limit', 'passed': true, 'detail': '\$5.00 ≤ \$10.00'},
            {'rule': 'Daily loss limit', 'passed': true, 'detail': '\$12.40 of \$50.00 used'},
            {'rule': 'Open trades', 'passed': true, 'detail': '1 of 3'},
          ],
        },
        'evaluation': {
          'id': 1,
          'bar_time': t['entry_time'],
          'outcome': 'SIGNAL',
          'summary': 'BUY: trend up and momentum confirms.',
          'checks': [
            {'name': 'Market regime', 'passed': true, 'detail': 'TREND_UP — EMA(9) above EMA(21), ADX 28'},
            {'name': 'Momentum', 'passed': true, 'detail': 'RSI 61 (above 55)'},
          ],
        },
        'orders': [
          {'id': 'o-1', 'purpose': 'ENTRY', 'symbol': t['symbol'], 'side': t['side'], 'status': 'FILLED', 'fill_price': t['entry_price'], 'broker_message': 'Contract bought', 'created_at': t['entry_time']},
        ],
        'events': [
          {'id': 1, 'occurred_at': t['entry_time'], 'event_type': 'SIGNAL', 'message': 'Signal on ${t['symbol']}.'},
          {'id': 2, 'occurred_at': t['entry_time'], 'event_type': 'ORDER_FILLED', 'message': 'Order filled by the broker.'},
        ],
      };
    }
    if (method == 'GET' && RegExp(r'^/backtests/[^/]+$').hasMatch(path)) return backtest;
    if (method == 'GET' && path.endsWith('/trades') && path.startsWith('/backtests/')) {
      return [
        for (var i = 0; i < 8; i++)
          {
            'id': i,
            'side': i.isEven ? 'BUY' : 'SELL',
            'entry_time': _t(Duration(hours: 4 * i + 1)),
            'entry_price': '48215.3310',
            'exit_price': '48290.1100',
            'exit_reason': 'EXPIRED',
            'volume': '1',
            'net_pnl': i % 3 == 0 ? '-5.00' : '4.75',
            'contract_type': i.isEven ? 'CALL' : 'PUT',
            'stake': '5.00',
            'outcome': i % 3 == 0 ? 'LOST' : 'WON',
          },
      ];
    }
    if (method == 'GET' && path.startsWith('/assignments/')) {
      return {
        'evaluations': {
          'data': [
            {'id': 3, 'bar_time': _t(const Duration(minutes: 1)), 'outcome': 'NO_SETUP', 'summary': 'No trade: momentum too weak (RSI 51).', 'checks': [{'name': 'Market regime', 'passed': true, 'detail': 'TREND_UP — EMA(9) above EMA(21), ADX 26'}]},
            {'id': 2, 'bar_time': _t(const Duration(minutes: 6)), 'outcome': 'SIGNAL', 'summary': 'BUY: trend up and momentum confirms.', 'checks': <Object>[]},
          ],
          'current_page': 1,
          'last_page': 1,
          'per_page': 50,
          'total': 2,
        },
        'signals': [
          {'id': 's1', 'side': 'BUY', 'bar_time': _t(const Duration(minutes: 6)), 'reasons': ['Trend up'], 'status': 'EXECUTED', 'rejection_reason': null, 'risk_checks': <Object>[]},
        ],
      };
    }
    if (method == 'GET' && path.startsWith('/risk/usage/')) {
      return {
        'account': _accRef('acc-demo'),
        'profile': {'name': 'Beginner'},
        'usage': [
          {'key': 'daily_loss', 'label': 'Daily loss', 'used': 12.4, 'limit': 50, 'unit': 'USD'},
          {'key': 'trades', 'label': 'Trades today', 'used': 9, 'limit': 20, 'unit': ''},
          {'key': 'streak', 'label': 'Losses in a row', 'used': 1, 'limit': 3, 'unit': ''},
          {'key': 'open', 'label': 'Open trades', 'used': 2, 'limit': 3, 'unit': ''},
        ],
      };
    }
    if (method == 'GET' && path == '/notifications') return notifications;
    if (method == 'GET' && path == '/history/export') return 'entry_time,exit_time,account\n';
    if (method == 'POST' && path.endsWith('/copy')) return strategies.first;
    if (method != 'GET') return {'ok': true};
    return _Fail(404, 'not_found', 'Not available in demo mode.');
  }

  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async {
    if (latency > Duration.zero) await Future<void>.delayed(latency);
    var path = options.uri.path;
    final root = Uri.parse(options.baseUrl).path;
    if (root.isNotEmpty && path.startsWith(root)) path = path.substring(root.length);
    requests.add('${options.method} $path');
    bodies.add(options.data);
    final result = route(options.method, path, options.uri.queryParameters, options.data);
    if (result is _Fail) {
      return ResponseBody.fromString(jsonEncode({'message': result.message, 'code': result.code}), result.status, headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      });
    }
    return ResponseBody.fromString(jsonEncode(result), 200, headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
    });
  }

  @override
  void close({bool force = false}) {}
}

class _Fail {
  const _Fail(this.status, this.code, this.message);
  final int status;
  final String code;
  final String message;
}
