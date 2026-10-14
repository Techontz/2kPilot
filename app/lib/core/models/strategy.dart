import 'json.dart';
import 'trading.dart';

/// How a BUY/SELL is traded (canonical form; fields that don't apply are null).
class ContractSpec {
  const ContractSpec({
    required this.contractFamily,
    this.duration,
    this.durationUnit,
    this.allowEquals = false,
    this.stake,
    this.multiplier,
    this.takeProfitAmount,
    this.stopLossAmount,
  });

  /// RISE_FALL | MULTIPLIER | SPOT
  final String contractFamily;
  final int? duration;

  /// t | s | m | h | d
  final String? durationUnit;
  final bool allowEquals;
  final String? stake;
  final int? multiplier;
  final String? takeProfitAmount;
  final String? stopLossAmount;

  factory ContractSpec.fromJson(Json j) => ContractSpec(
        contractFamily: j.str('contract_family', 'SPOT'),
        duration: j.intOrNull('duration'),
        durationUnit: j.strOrNull('duration_unit'),
        allowEquals: j.boolean('allow_equals'),
        stake: j.dec('stake'),
        multiplier: j.intOrNull('multiplier'),
        takeProfitAmount: j.dec('take_profit_amount'),
        stopLossAmount: j.dec('stop_loss_amount'),
      );

  static ContractSpec? maybe(Json? j) => j == null || j['contract_family'] == null ? null : ContractSpec.fromJson(j);

  Json toJson() => {
        'contract_family': contractFamily,
        'duration': duration,
        'duration_unit': durationUnit,
        'allow_equals': allowEquals,
        'stake': stake,
        'multiplier': multiplier,
        'take_profit_amount': takeProfitAmount,
        'stop_loss_amount': stopLossAmount,
      };

  ContractSpec copyWith({
    int? Function()? duration,
    String? Function()? durationUnit,
    bool? allowEquals,
    String? Function()? stake,
    int? Function()? multiplier,
    String? Function()? takeProfitAmount,
    String? Function()? stopLossAmount,
  }) =>
      ContractSpec(
        contractFamily: contractFamily,
        duration: duration != null ? duration() : this.duration,
        durationUnit: durationUnit != null ? durationUnit() : this.durationUnit,
        allowEquals: allowEquals ?? this.allowEquals,
        stake: stake != null ? stake() : this.stake,
        multiplier: multiplier != null ? multiplier() : this.multiplier,
        takeProfitAmount: takeProfitAmount != null ? takeProfitAmount() : this.takeProfitAmount,
        stopLossAmount: stopLossAmount != null ? stopLossAmount() : this.stopLossAmount,
      );
}

class DurationRange {
  const DurationRange(this.min, this.max);
  final String min;
  final String max;
}

/// GET /api/markets/contracts — what a symbol offers on an account.
class ContractOffer {
  const ContractOffer({
    required this.symbol,
    required this.marketOpen,
    required this.tradingSuspended,
    required this.riseFallAvailable,
    required this.riseFallAllowEquals,
    required this.durations,
    required this.multiplierAvailable,
    required this.multipliers,
    required this.spotAvailable,
    required this.defaultContract,
    required this.notes,
  });

  final String symbol;
  final bool? marketOpen;
  final bool tradingSuspended;
  final bool riseFallAvailable;
  final bool riseFallAllowEquals;
  final List<DurationRange> durations;
  final bool multiplierAvailable;
  final List<int> multipliers;
  final bool spotAvailable;
  final ContractSpec defaultContract;
  final List<String> notes;

  factory ContractOffer.fromJson(Json j) {
    final f = j.obj('families') ?? const {};
    final rf = asJson(f['RISE_FALL']);
    final mu = asJson(f['MULTIPLIER']);
    final sp = asJson(f['SPOT']);
    return ContractOffer(
      symbol: j.str('symbol'),
      marketOpen: j.boolOrNull('market_open'),
      tradingSuspended: j.boolean('trading_suspended'),
      riseFallAvailable: rf.boolean('available'),
      riseFallAllowEquals: rf.boolean('allow_equals'),
      durations: rf.objList('durations').map((d) => DurationRange(d.str('min'), d.str('max'))).toList(),
      multiplierAvailable: mu.boolean('available'),
      multipliers: (mu['multipliers'] is List ? (mu['multipliers'] as List) : const []).map((e) => e is num ? e.toInt() : int.tryParse('$e') ?? 0).where((e) => e > 0).toList(),
      spotAvailable: sp.boolean('available'),
      defaultContract: ContractSpec.fromJson(j.obj('default_contract') ?? const {'contract_family': 'SPOT'}),
      notes: j.strList('notes'),
    );
  }
}

class Instrument {
  const Instrument({required this.name, required this.canonical, required this.description, required this.category, required this.tradeAllowed});
  final String name;
  final String canonical;
  final String description;
  final String category;
  final bool tradeAllowed;

  factory Instrument.fromJson(Json j) => Instrument(
        name: j.str('name'),
        canonical: j.str('canonical'),
        description: j.str('description'),
        category: j.str('category'),
        tradeAllowed: j.boolean('trade_allowed', true),
      );
}

class StrategyVersion {
  const StrategyVersion({required this.id, required this.version, required this.parameters, this.rulesText});
  final String id;
  final int version;
  final Json parameters;
  final String? rulesText;

  factory StrategyVersion.fromJson(Json j) => StrategyVersion(
        id: j.str('id'),
        version: j.integer('version', 1),
        parameters: j.obj('parameters') ?? const {},
        rulesText: j.strOrNull('rules_text'),
      );
}

class AssignmentAccount {
  const AssignmentAccount({required this.id, required this.label, required this.environment});
  final String id;
  final String label;
  final AccountEnvironment environment;
}

class Assignment {
  const Assignment({
    required this.id,
    required this.strategyId,
    this.version,
    this.account,
    required this.symbol,
    this.contract,
    required this.status,
    this.statusReason,
    this.lastBarEvaluated,
    this.lastSignalAt,
  });

  final String id;
  final String strategyId;
  final int? version;
  final AssignmentAccount? account;
  final String symbol;
  final ContractSpec? contract;

  /// ENABLED | PAUSED
  final String status;
  final String? statusReason;
  final String? lastBarEvaluated;
  final String? lastSignalAt;

  bool get enabled => status == 'ENABLED';

  factory Assignment.fromJson(Json j) {
    final a = j.obj('account');
    return Assignment(
      id: j.str('id'),
      strategyId: j.str('strategy_id'),
      version: j.intOrNull('version'),
      account: a == null ? null : AssignmentAccount(id: a.str('id'), label: a.str('label'), environment: AccountEnvironment.parse(a.strOrNull('environment'))),
      symbol: j.str('symbol'),
      contract: ContractSpec.maybe(j.obj('contract')),
      status: j.str('status', 'PAUSED'),
      statusReason: j.strOrNull('status_reason'),
      lastBarEvaluated: j.strOrNull('last_bar_evaluated'),
      lastSignalAt: j.strOrNull('last_signal_at'),
    );
  }
}

/// Result of POST /api/strategies/{id}/activate.
class ActivationResult {
  const ActivationResult({required this.assignment, required this.blockers, required this.willTrade, this.contractVerified, this.contractDetail});
  final Assignment assignment;
  final List<Blocker> blockers;
  final bool willTrade;
  final bool? contractVerified;
  final String? contractDetail;

  factory ActivationResult.fromJson(Json j) {
    final check = j.obj('contract_check');
    return ActivationResult(
      assignment: Assignment.fromJson(j),
      blockers: j.objList('blockers').map(Blocker.fromJson).toList(),
      willTrade: j.boolean('will_trade'),
      contractVerified: check?.boolOrNull('verified'),
      contractDetail: check?.strOrNull('detail'),
    );
  }
}

class ValidationCheck {
  const ValidationCheck(this.name, this.passed, this.detail);
  final String name;
  final bool passed;
  final String detail;
}

/// The "qualifies for demo forward testing" gate of a split / walk-forward test.
class ValidationGate {
  const ValidationGate({required this.qualifies, required this.checks, required this.reasons, required this.note});
  final bool qualifies;
  final List<ValidationCheck> checks;
  final List<String> reasons;
  final String note;

  static ValidationGate? maybe(Json? j) => j == null
      ? null
      : ValidationGate(
          qualifies: j.boolean('qualifies_for_demo_forward_testing'),
          checks: j.objList('checks').map((c) => ValidationCheck(c.str('name'), c.boolean('passed'), c.str('detail'))).toList(),
          reasons: j.strList('reasons'),
          note: j.str('note'),
        );
}

class GroupStat {
  const GroupStat({required this.key, required this.trades, this.winRate, this.netPnl, this.profitFactor, this.expectancy, this.avgRr, this.maxDrawdown, this.longestLosingStreak});
  final String key;
  final int trades;
  final double? winRate;
  final double? netPnl;
  final double? profitFactor;
  final double? expectancy;
  final double? avgRr;
  final double? maxDrawdown;
  final int? longestLosingStreak;

  factory GroupStat.fromJson(Json j) => GroupStat(
        key: j.str('key'),
        trades: j.integer('trades'),
        winRate: j.numOrNull('win_rate'),
        netPnl: j.numOrNull('net_pnl'),
        profitFactor: j.numOrNull('profit_factor'),
        expectancy: j.numOrNull('expectancy'),
        avgRr: j.numOrNull('avg_rr'),
        maxDrawdown: j.numOrNull('max_drawdown'),
        longestLosingStreak: j.intOrNull('longest_losing_streak'),
      );
}

class BacktestHeadline {
  const BacktestHeadline({
    required this.id,
    required this.name,
    required this.symbol,
    required this.timeframe,
    this.netPnl,
    this.winRate,
    this.trades,
    this.maxDrawdownPct,
    this.profitFactor,
    this.expectancy,
    this.dataSource,
    this.runAt,
    required this.byRegime,
    this.validation,
  });

  final String id;
  final String name;
  final String symbol;
  final String timeframe;
  final double? netPnl;
  final double? winRate;
  final int? trades;
  final double? maxDrawdownPct;
  final double? profitFactor;
  final double? expectancy;
  final String? dataSource;
  final String? runAt;
  final List<GroupStat> byRegime;
  final ValidationGate? validation;

  factory BacktestHeadline.fromJson(Json j) => BacktestHeadline(
        id: j.str('id'),
        name: j.str('name'),
        symbol: j.str('symbol'),
        timeframe: j.str('timeframe'),
        netPnl: j.numOrNull('net_pnl'),
        winRate: j.numOrNull('win_rate'),
        trades: j.intOrNull('trades'),
        maxDrawdownPct: j.numOrNull('max_drawdown_pct'),
        profitFactor: j.numOrNull('profit_factor'),
        expectancy: j.numOrNull('expectancy'),
        dataSource: j.strOrNull('data_source'),
        runAt: j.strOrNull('run_at'),
        byRegime: j.objList('by_regime').map(GroupStat.fromJson).toList(),
        validation: ValidationGate.maybe(j.obj('validation')),
      );
}

class StrategyDetails {
  const StrategyDetails({
    this.howItWorks,
    this.struggles,
    this.difficulty,
    this.disclaimer,
    required this.suggestedSymbols,
    this.suggestedTimeframe,
    this.suggestedContract,
    this.suggestedContractNote,
    this.suggestedContractPaper,
    this.supportedContractFamilies,
    this.supportedSymbols,
  });

  final String? howItWorks;
  final String? struggles;
  final String? difficulty;
  final String? disclaimer;
  final List<String> suggestedSymbols;
  final String? suggestedTimeframe;
  final ContractSpec? suggestedContract;
  final String? suggestedContractNote;
  final ContractSpec? suggestedContractPaper;
  final List<String>? supportedContractFamilies;
  final List<String>? supportedSymbols;

  factory StrategyDetails.fromJson(Json j) => StrategyDetails(
        howItWorks: j.strOrNull('how_it_works'),
        struggles: j.strOrNull('struggles'),
        difficulty: j.strOrNull('difficulty'),
        disclaimer: j.strOrNull('disclaimer'),
        suggestedSymbols: j.strList('suggested_symbols'),
        suggestedTimeframe: j.strOrNull('suggested_timeframe'),
        suggestedContract: ContractSpec.maybe(j.obj('suggested_contract')),
        suggestedContractNote: j.strOrNull('suggested_contract_note'),
        suggestedContractPaper: ContractSpec.maybe(j.obj('suggested_contract_paper')),
        supportedContractFamilies: j.strListOrNull('supported_contract_families'),
        supportedSymbols: j.strListOrNull('supported_symbols'),
      );

  static const empty = StrategyDetails(suggestedSymbols: []);
}

class PerformanceStats {
  const PerformanceStats({required this.trades, this.winRate, required this.netPnl, required this.netPnl30d, this.lastTradeAt});
  final int trades;
  final double? winRate;
  final double netPnl;
  final double netPnl30d;
  final String? lastTradeAt;

  static PerformanceStats? maybe(Json? j) => j == null
      ? null
      : PerformanceStats(
          trades: j.integer('trades'),
          winRate: j.numOrNull('win_rate'),
          netPnl: j.number('net_pnl'),
          netPnl30d: j.number('net_pnl_30d'),
          lastTradeAt: j.strOrNull('last_trade_at'),
        );
}

class SchemaProperty {
  const SchemaProperty({this.title, this.description});
  final String? title;
  final String? description;
}

class EntriesDisabled {
  const EntriesDisabled({this.reason, required this.inherited});
  final String? reason;
  final bool inherited;
}

class Strategy {
  const Strategy({
    required this.id,
    required this.key,
    required this.name,
    required this.description,
    this.summary,
    required this.details,
    this.source,
    required this.builtIn,
    this.editable,
    required this.schema,
    this.latestVersion,
    this.rulesText,
    required this.versions,
    required this.assignments,
    this.demo,
    this.backtest,
    this.backtestsBySymbol,
    this.contractFamilies,
    this.symbols,
    this.entriesDisabled,
  });

  final String id;
  final String key;
  final String name;
  final String description;
  final String? summary;
  final StrategyDetails details;
  final String? source;
  final bool builtIn;
  final bool? editable;
  final Map<String, SchemaProperty> schema;
  final StrategyVersion? latestVersion;
  final String? rulesText;
  final List<StrategyVersion> versions;
  final List<Assignment> assignments;
  final PerformanceStats? demo;
  final BacktestHeadline? backtest;
  final List<BacktestHeadline>? backtestsBySymbol;
  final List<String>? contractFamilies;
  final List<String>? symbols;
  final EntriesDisabled? entriesDisabled;

  factory Strategy.fromJson(Json j) {
    final props = j.obj('parameter_schema')?.obj('properties') ?? const <String, dynamic>{};
    final perf = j.obj('performance');
    final ed = j.obj('entries_disabled');
    return Strategy(
      id: j.str('id'),
      key: j.str('key'),
      name: j.str('name'),
      description: j.str('description'),
      summary: j.strOrNull('summary'),
      details: j.obj('details') == null ? StrategyDetails.empty : StrategyDetails.fromJson(j.obj('details')!),
      source: j.strOrNull('source'),
      builtIn: j.boolean('built_in'),
      editable: j.boolOrNull('editable'),
      schema: props.map((k, v) {
        final p = asJson(v);
        return MapEntry(k, SchemaProperty(title: p.strOrNull('title'), description: p.strOrNull('description')));
      }),
      latestVersion: j.obj('latest_version') == null ? null : StrategyVersion.fromJson(j.obj('latest_version')!),
      rulesText: j.strOrNull('rules_text'),
      versions: j.objList('versions').map(StrategyVersion.fromJson).toList(),
      assignments: j.objList('assignments').map(Assignment.fromJson).toList(),
      demo: PerformanceStats.maybe(perf?.obj('demo')),
      backtest: j.obj('backtest') == null ? null : BacktestHeadline.fromJson(j.obj('backtest')!),
      backtestsBySymbol: j['backtests_by_symbol'] is List ? j.objList('backtests_by_symbol').map(BacktestHeadline.fromJson).toList() : null,
      contractFamilies: j.strListOrNull('contract_families'),
      symbols: j.strListOrNull('symbols'),
      entriesDisabled: ed == null ? null : EntriesDisabled(reason: ed.strOrNull('reason'), inherited: ed.boolean('inherited')),
    );
  }
}

class EquityPoint {
  const EquityPoint(this.t, this.value);
  final String t;
  final double value;
}

class MonthStat {
  const MonthStat(this.month, this.netPnl, this.trades);
  final String month;
  final double netPnl;
  final int trades;
}

class Metrics {
  const Metrics({
    this.netPnl,
    this.returnPct,
    required this.trades,
    required this.wins,
    required this.losses,
    this.winRate,
    this.profitFactor,
    this.maxDrawdown,
    this.maxDrawdownPct,
    required this.maxConsecutiveLosses,
    this.longestLosingStreak,
    this.expectancy,
    this.totalCosts,
    this.avgHoldingHours,
    required this.equityCurve,
    required this.drawdownCurve,
    required this.monthly,
    required this.bySymbol,
    required this.byRegime,
    this.outcomes,
    required this.notes,
    this.payoutRatio,
    this.contract,
  });

  final double? netPnl;
  final double? returnPct;
  final int trades;
  final int wins;
  final int losses;
  final double? winRate;
  final double? profitFactor;
  final double? maxDrawdown;
  final double? maxDrawdownPct;
  final int maxConsecutiveLosses;
  final int? longestLosingStreak;
  final double? expectancy;
  final double? totalCosts;
  final double? avgHoldingHours;
  final List<EquityPoint> equityCurve;
  final List<EquityPoint> drawdownCurve;
  final List<MonthStat> monthly;
  final List<GroupStat> bySymbol;
  final List<GroupStat> byRegime;
  final Map<String, int>? outcomes;
  final List<String> notes;
  final double? payoutRatio;
  final ContractSpec? contract;

  static Metrics? maybe(Json? j) {
    if (j == null) return null;
    final outcomes = j.obj('outcomes');
    return Metrics(
      netPnl: j.numOrNull('net_pnl'),
      returnPct: j.numOrNull('return_pct'),
      trades: j.integer('trades'),
      wins: j.integer('wins'),
      losses: j.integer('losses'),
      winRate: j.numOrNull('win_rate'),
      profitFactor: j.numOrNull('profit_factor'),
      maxDrawdown: j.numOrNull('max_drawdown'),
      maxDrawdownPct: j.numOrNull('max_drawdown_pct'),
      maxConsecutiveLosses: j.integer('max_consecutive_losses'),
      longestLosingStreak: j.intOrNull('longest_losing_streak'),
      expectancy: j.numOrNull('expectancy'),
      totalCosts: j.numOrNull('total_costs'),
      avgHoldingHours: j.numOrNull('avg_holding_hours'),
      equityCurve: j.objList('equity_curve').map((p) => EquityPoint(p.str('t'), p.number('equity'))).toList(),
      drawdownCurve: j.objList('drawdown_curve').map((p) => EquityPoint(p.str('t'), p.number('dd'))).toList(),
      monthly: j.objList('monthly').map((m) => MonthStat(m.str('month'), m.number('net_pnl'), m.integer('trades'))).toList(),
      bySymbol: j.objList('by_symbol').map(GroupStat.fromJson).toList(),
      byRegime: j.objList('by_regime').map(GroupStat.fromJson).toList(),
      outcomes: outcomes?.map((k, v) => MapEntry(k, v is num ? v.toInt() : int.tryParse('$v') ?? 0)),
      notes: j.strList('notes'),
      payoutRatio: j.numOrNull('payout_ratio'),
      contract: ContractSpec.maybe(j.obj('contract')),
    );
  }
}

class Backtest {
  const Backtest({
    required this.id,
    required this.name,
    required this.kind,
    required this.status,
    required this.symbol,
    required this.timeframe,
    required this.dataSource,
    required this.start,
    required this.end,
    required this.initialCapital,
    required this.progress,
    this.metrics,
    required this.warnings,
    this.validation,
    this.contract,
    this.error,
    required this.createdAt,
  });

  final String id;
  final String name;
  final String kind;

  /// QUEUED | RUNNING | COMPLETED | FAILED
  final String status;
  final String symbol;
  final String timeframe;
  final String dataSource;
  final String start;
  final String end;
  final String initialCapital;
  final int progress;
  final Metrics? metrics;
  final List<String> warnings;
  final ValidationGate? validation;
  final ContractSpec? contract;
  final String? error;
  final String createdAt;

  bool get running => status == 'RUNNING' || status == 'QUEUED';

  factory Backtest.fromJson(Json j) {
    final report = j.obj('report');
    return Backtest(
      id: j.str('id'),
      name: j.str('name'),
      kind: j.str('kind'),
      status: j.str('status', 'QUEUED'),
      symbol: j.str('symbol'),
      timeframe: j.str('timeframe'),
      dataSource: j.str('data_source'),
      start: j.str('start'),
      end: j.str('end'),
      initialCapital: j.str('initial_capital', '0'),
      progress: j.integer('progress'),
      metrics: Metrics.maybe(j.obj('metrics')),
      warnings: report?.strList('warnings') ?? const [],
      validation: ValidationGate.maybe(report?.obj('validation')),
      contract: ContractSpec.maybe(j.obj('config')?.obj('contract')),
      error: j.strOrNull('error'),
      createdAt: j.str('created_at'),
    );
  }
}

class BacktestTrade {
  const BacktestTrade({required this.id, required this.side, required this.entryTime, required this.entryPrice, required this.exitPrice, required this.exitReason, required this.volume, required this.netPnl, this.contractType, this.stake, this.outcome});
  final int id;
  final String side;
  final String entryTime;
  final String entryPrice;
  final String exitPrice;
  final String exitReason;
  final String volume;
  final String netPnl;
  final String? contractType;
  final String? stake;
  final String? outcome;

  factory BacktestTrade.fromJson(Json j) => BacktestTrade(
        id: j.integer('id'),
        side: j.str('side', 'BUY'),
        entryTime: j.str('entry_time'),
        entryPrice: j.str('entry_price'),
        exitPrice: j.str('exit_price'),
        exitReason: j.str('exit_reason'),
        volume: j.str('volume', '0'),
        netPnl: j.str('net_pnl', '0'),
        contractType: j.strOrNull('contract_type'),
        stake: j.dec('stake'),
        outcome: j.strOrNull('outcome'),
      );
}

class Dataset {
  const Dataset({required this.id, required this.symbol, required this.timeframe, required this.source, this.firstBar, this.lastBar});
  final String id;
  final String symbol;
  final String timeframe;
  final String source;
  final String? firstBar;
  final String? lastBar;

  factory Dataset.fromJson(Json j) => Dataset(
        id: j.str('id'),
        symbol: j.str('symbol'),
        timeframe: j.str('timeframe'),
        source: j.str('source'),
        firstBar: j.strOrNull('first_bar'),
        lastBar: j.strOrNull('last_bar'),
      );
}
