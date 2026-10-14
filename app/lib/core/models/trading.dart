import 'json.dart';

/// PAPER / DEMO / LIVE / UNKNOWN (as the broker reported it).
enum AccountEnvironment {
  paper('PAPER'),
  demo('DEMO'),
  live('LIVE'),
  unknown('UNKNOWN');

  const AccountEnvironment(this.wire);
  final String wire;

  static AccountEnvironment parse(String? value) =>
      values.firstWhere((e) => e.wire == value, orElse: () => AccountEnvironment.unknown);
}

enum ConnectionStatus {
  connected('CONNECTED'),
  disconnected('DISCONNECTED'),
  reconnecting('RECONNECTING'),
  error('ERROR');

  const ConnectionStatus(this.wire);
  final String wire;

  static ConnectionStatus parse(String? value) =>
      values.firstWhere((e) => e.wire == value, orElse: () => ConnectionStatus.disconnected);

  String get label => switch (this) {
        connected => 'Connected',
        disconnected => 'Disconnected',
        reconnecting => 'Reconnecting',
        error => 'Connection error',
      };
}

class User {
  const User({
    required this.id,
    required this.name,
    required this.email,
    required this.role,
    required this.mfaEnabled,
    required this.mfaRequired,
    this.lastLoginAt,
  });

  final String id;
  final String name;
  final String email;
  final String role;
  final bool mfaEnabled;
  final bool mfaRequired;
  final String? lastLoginAt;

  bool get isAdmin => role == 'admin';

  factory User.fromJson(Json j) => User(
        id: j.str('id'),
        name: j.str('name'),
        email: j.str('email'),
        role: j.str('role', 'user'),
        mfaEnabled: j.boolean('mfa_enabled'),
        mfaRequired: j.boolean('mfa_required'),
        lastLoginAt: j.strOrNull('last_login_at'),
      );

  Json toJson() => {
        'id': id,
        'name': name,
        'email': email,
        'role': role,
        'mfa_enabled': mfaEnabled,
        'mfa_required': mfaRequired,
        'last_login_at': lastLoginAt,
      };
}

class EngineSummary {
  const EngineSummary({required this.code, required this.tone, required this.label, required this.message, required this.tradingActive});

  /// running | running_degraded | trading_disabled | supervisor_not_started | supervisor_stale | engine_error | engine_offline
  final String code;

  /// ok | info | warning | error
  final String tone;
  final String label;
  final String message;
  final bool tradingActive;

  factory EngineSummary.fromJson(Json j) => EngineSummary(
        code: j.str('code', 'running'),
        tone: j.str('tone', 'ok'),
        label: j.str('label'),
        message: j.str('message'),
        tradingActive: j.boolean('trading_active'),
      );
}

class EngineService {
  const EngineService({required this.status, required this.reachable, this.version, this.detail});

  /// online | error | unreachable
  final String status;
  final bool reachable;
  final String? version;
  final String? detail;

  factory EngineService.fromJson(Json j) => EngineService(
        status: j.str('status', 'unreachable'),
        reachable: j.boolean('reachable'),
        version: j.strOrNull('version'),
        detail: j.strOrNull('detail'),
      );
}

class EngineSupervisor {
  const EngineSupervisor({required this.state, this.heartbeatAt, required this.detail});

  /// running | degraded | stale | not_started | disabled | unknown
  final String state;
  final String? heartbeatAt;
  final String detail;

  factory EngineSupervisor.fromJson(Json j) => EngineSupervisor(
        state: j.str('state', 'unknown'),
        heartbeatAt: j.strOrNull('heartbeat_at'),
        detail: j.str('detail'),
      );
}

/// GET /api/trading/status — and the body every Start/Stop/mode call answers with.
class TradingStatus {
  const TradingStatus({
    required this.tradingMode,
    required this.killSwitchEngaged,
    this.killSwitchReason,
    required this.liveTradingLocked,
    this.liveAuthorizedAt,
    required this.platformHalted,
    this.platformHaltReason,
    required this.engineState,
    required this.engineDetail,
    this.engineHeartbeatAt,
    required this.newOrdersPermitted,
    this.liveRevokedReason,
    this.engineSummary,
    this.engineService,
    this.engineSupervisor,
  });

  /// DEMO | LIVE
  final String tradingMode;
  final bool killSwitchEngaged;
  final String? killSwitchReason;
  final bool liveTradingLocked;
  final String? liveAuthorizedAt;
  final bool platformHalted;
  final String? platformHaltReason;

  /// offline | running | degraded
  final String engineState;
  final String engineDetail;
  final String? engineHeartbeatAt;
  final bool newOrdersPermitted;
  final String? liveRevokedReason;
  final EngineSummary? engineSummary;
  final EngineService? engineService;
  final EngineSupervisor? engineSupervisor;

  bool get isLive => tradingMode == 'LIVE';

  factory TradingStatus.fromJson(Json j) => TradingStatus(
        tradingMode: j.str('trading_mode', 'DEMO'),
        killSwitchEngaged: j.boolean('kill_switch_engaged', true),
        killSwitchReason: j.strOrNull('kill_switch_reason'),
        liveTradingLocked: j.boolean('live_trading_locked', true),
        liveAuthorizedAt: j.strOrNull('live_authorized_at'),
        platformHalted: j.boolean('platform_halted'),
        platformHaltReason: j.strOrNull('platform_halt_reason'),
        engineState: j.str('engine_state', 'offline'),
        engineDetail: j.str('engine_detail'),
        engineHeartbeatAt: j.strOrNull('engine_heartbeat_at'),
        newOrdersPermitted: j.boolean('new_orders_permitted'),
        liveRevokedReason: j.strOrNull('live_revoked_reason'),
        engineSummary: j.obj('engine_summary') == null ? null : EngineSummary.fromJson(j.obj('engine_summary')!),
        engineService: j.obj('engine_service') == null ? null : EngineService.fromJson(j.obj('engine_service')!),
        engineSupervisor: j.obj('engine_supervisor') == null ? null : EngineSupervisor.fromJson(j.obj('engine_supervisor')!),
      );

  TradingStatus copyWith({EngineSummary? engineSummary}) => TradingStatus(
        tradingMode: tradingMode,
        killSwitchEngaged: killSwitchEngaged,
        killSwitchReason: killSwitchReason,
        liveTradingLocked: liveTradingLocked,
        liveAuthorizedAt: liveAuthorizedAt,
        platformHalted: platformHalted,
        platformHaltReason: platformHaltReason,
        engineState: engineState,
        engineDetail: engineDetail,
        engineHeartbeatAt: engineHeartbeatAt,
        newOrdersPermitted: newOrdersPermitted,
        liveRevokedReason: liveRevokedReason,
        engineSummary: engineSummary ?? this.engineSummary,
        engineService: engineService,
        engineSupervisor: engineSupervisor,
      );
}

class RiskProfileRef {
  const RiskProfileRef(this.id, this.name);
  final String id;
  final String name;
}

class Account {
  const Account({
    required this.id,
    required this.label,
    required this.broker,
    required this.connectorType,
    required this.connectionId,
    required this.connectionStatus,
    this.connectionDetail,
    required this.connectionEnabled,
    this.lastConnectedAt,
    required this.brokerAccountId,
    required this.server,
    required this.environment,
    required this.currency,
    this.balance,
    this.equity,
    required this.tradingEnabled,
    this.riskProfile,
    required this.activeStrategies,
    this.historicalCandles,
    this.pendingOrders,
    this.syncedAt,
  });

  final String id;
  final String label;
  final String broker;

  /// paper | deriv
  final String connectorType;
  final String connectionId;
  final ConnectionStatus connectionStatus;
  final String? connectionDetail;
  final bool connectionEnabled;
  final String? lastConnectedAt;
  final String brokerAccountId;
  final String server;
  final AccountEnvironment environment;
  final String currency;
  final String? balance;
  final String? equity;
  final bool tradingEnabled;
  final RiskProfileRef? riskProfile;
  final List<String> activeStrategies;
  final bool? historicalCandles;
  final bool? pendingOrders;
  final String? syncedAt;

  bool get isDeriv => connectorType == 'deriv';
  bool get isLive => environment == AccountEnvironment.live;

  factory Account.fromJson(Json j) {
    final rp = j.obj('risk_profile');
    final caps = j.obj('capabilities') ?? const <String, dynamic>{};
    return Account(
      id: j.str('id'),
      label: j.str('label'),
      broker: j.str('broker'),
      connectorType: j.str('connector_type', 'paper'),
      connectionId: j.str('connection_id'),
      connectionStatus: ConnectionStatus.parse(j.strOrNull('connection_status')),
      connectionDetail: j.strOrNull('connection_detail'),
      connectionEnabled: j.boolean('connection_enabled', true),
      lastConnectedAt: j.strOrNull('last_connected_at'),
      brokerAccountId: j.str('broker_account_id'),
      server: j.str('server'),
      environment: AccountEnvironment.parse(j.strOrNull('environment')),
      currency: j.str('currency', 'USD'),
      balance: j.dec('balance'),
      equity: j.dec('equity'),
      tradingEnabled: j.boolean('trading_enabled'),
      riskProfile: rp == null ? null : RiskProfileRef(rp.str('id'), rp.str('name')),
      activeStrategies: j.strList('active_strategies'),
      historicalCandles: caps.boolOrNull('historical_candles'),
      pendingOrders: caps.boolOrNull('pending_orders'),
      syncedAt: j.strOrNull('synced_at'),
    );
  }
}

class TradeAccount {
  const TradeAccount({required this.id, required this.label, required this.environment, required this.currency});
  final String id;
  final String label;
  final AccountEnvironment environment;
  final String currency;

  factory TradeAccount.fromJson(Json j) => TradeAccount(
        id: j.str('id'),
        label: j.str('label'),
        environment: AccountEnvironment.parse(j.strOrNull('environment')),
        currency: j.str('currency', 'USD'),
      );
}

class Trade {
  const Trade({
    required this.id,
    this.account,
    this.strategy,
    this.strategyVersion,
    required this.source,
    required this.symbol,
    required this.side,
    required this.status,
    required this.volume,
    required this.entryPrice,
    this.entryTime,
    this.exitPrice,
    this.exitTime,
    this.exitReason,
    this.netPnl,
    this.unrealizedPnl,
    this.commission,
    this.isSimulated = false,
    this.contractFamily,
    this.contractType,
    this.brokerContractId,
    this.stake,
    this.payout,
    this.multiplier,
    this.duration,
    this.durationUnit,
    this.expiresAt,
    this.entrySpot,
    this.exitSpot,
    this.fees,
    this.outcome,
    this.longcode,
    this.durationSeconds,
  });

  final String id;
  final TradeAccount? account;
  final String? strategy;
  final int? strategyVersion;

  /// STRATEGY | MANUAL | EXTERNAL
  final String source;
  final String symbol;

  /// BUY | SELL
  final String side;

  /// OPEN | CLOSED
  final String status;
  final String volume;
  final String entryPrice;
  final String? entryTime;
  final String? exitPrice;
  final String? exitTime;
  final String? exitReason;
  final String? netPnl;
  final String? unrealizedPnl;
  final String? commission;
  final bool isSimulated;

  /// RISE_FALL | MULTIPLIER | SPOT
  final String? contractFamily;
  final String? contractType;
  final String? brokerContractId;
  final String? stake;
  final String? payout;
  final int? multiplier;
  final int? duration;
  final String? durationUnit;
  final String? expiresAt;
  final String? entrySpot;
  final String? exitSpot;
  final String? fees;

  /// OPEN | WON | LOST | SOLD | CANCELLED
  final String? outcome;
  final String? longcode;
  final int? durationSeconds;

  bool get isOpen => status == 'OPEN';

  factory Trade.fromJson(Json j) => Trade(
        id: j.str('id'),
        account: j.obj('account') == null ? null : TradeAccount.fromJson(j.obj('account')!),
        strategy: j.strOrNull('strategy'),
        strategyVersion: j.intOrNull('strategy_version'),
        source: j.str('source', 'STRATEGY'),
        symbol: j.str('symbol'),
        side: j.str('side', 'BUY'),
        status: j.str('status', 'CLOSED'),
        volume: j.str('volume', '0'),
        entryPrice: j.str('entry_price', '0'),
        entryTime: j.strOrNull('entry_time'),
        exitPrice: j.dec('exit_price'),
        exitTime: j.strOrNull('exit_time'),
        exitReason: j.strOrNull('exit_reason'),
        netPnl: j.dec('net_pnl'),
        unrealizedPnl: j.dec('unrealized_pnl'),
        commission: j.dec('commission'),
        isSimulated: j.boolean('is_simulated'),
        contractFamily: j.strOrNull('contract_family'),
        contractType: j.strOrNull('contract_type'),
        brokerContractId: j.strOrNull('broker_contract_id'),
        stake: j.dec('stake'),
        payout: j.dec('payout'),
        multiplier: j.intOrNull('multiplier'),
        duration: j.intOrNull('duration'),
        durationUnit: j.strOrNull('duration_unit'),
        expiresAt: j.strOrNull('expires_at'),
        entrySpot: j.dec('entry_spot'),
        exitSpot: j.dec('exit_spot'),
        fees: j.dec('fees'),
        outcome: j.strOrNull('outcome'),
        longcode: j.strOrNull('longcode'),
        durationSeconds: j.intOrNull('duration_seconds'),
      );
}

class Blocker {
  const Blocker(this.code, this.message);
  final String code;
  final String message;

  factory Blocker.fromJson(Json j) => Blocker(j.str('code'), j.str('message'));
}

class SetupChecklist {
  const SetupChecklist({
    required this.hasBroker,
    required this.hasAccount,
    required this.hasStrategy,
    required this.hasBacktest,
    required this.hasActiveStrategy,
    required this.tradingStarted,
    required this.mfaEnabled,
  });

  final bool hasBroker;
  final bool hasAccount;
  final bool hasStrategy;
  final bool hasBacktest;
  final bool hasActiveStrategy;
  final bool tradingStarted;
  final bool mfaEnabled;

  bool get complete => hasAccount && hasStrategy && hasActiveStrategy && tradingStarted;

  factory SetupChecklist.fromJson(Json j) => SetupChecklist(
        hasBroker: j.boolean('has_broker'),
        hasAccount: j.boolean('has_account'),
        hasStrategy: j.boolean('has_strategy'),
        hasBacktest: j.boolean('has_backtest'),
        hasActiveStrategy: j.boolean('has_active_strategy'),
        tradingStarted: j.boolean('trading_started'),
        mfaEnabled: j.boolean('mfa_enabled'),
      );
}

class ActiveStrategy {
  const ActiveStrategy({
    required this.assignmentId,
    required this.strategyId,
    this.strategy,
    required this.symbol,
    required this.contractSummary,
    this.lastBarEvaluated,
    this.lastSignalAt,
  });

  final String assignmentId;
  final String strategyId;
  final String? strategy;
  final String symbol;
  final String contractSummary;
  final String? lastBarEvaluated;
  final String? lastSignalAt;

  factory ActiveStrategy.fromJson(Json j) => ActiveStrategy(
        assignmentId: j.str('assignment_id'),
        strategyId: j.str('strategy_id'),
        strategy: j.strOrNull('strategy'),
        symbol: j.str('symbol'),
        contractSummary: j.str('contract_summary'),
        lastBarEvaluated: j.strOrNull('last_bar_evaluated'),
        lastSignalAt: j.strOrNull('last_signal_at'),
      );
}

class OverviewAccount {
  const OverviewAccount({
    required this.id,
    required this.label,
    required this.broker,
    required this.environment,
    required this.currency,
    required this.connectionStatus,
    this.connectionDetail,
    required this.tradingEnabled,
    this.syncedAt,
    this.balance,
    this.brokerAccountId,
  });

  final String id;
  final String label;
  final String broker;
  final AccountEnvironment environment;
  final String currency;
  final ConnectionStatus connectionStatus;
  final String? connectionDetail;
  final bool tradingEnabled;
  final String? syncedAt;
  final String? balance;
  final String? brokerAccountId;

  factory OverviewAccount.fromJson(Json j) => OverviewAccount(
        id: j.str('id'),
        label: j.str('label'),
        broker: j.str('broker'),
        environment: AccountEnvironment.parse(j.strOrNull('environment')),
        currency: j.str('currency', 'USD'),
        connectionStatus: ConnectionStatus.parse(j.strOrNull('connection_status')),
        connectionDetail: j.strOrNull('connection_detail'),
        tradingEnabled: j.boolean('trading_enabled'),
        syncedAt: j.strOrNull('synced_at'),
        balance: j.dec('balance'),
        brokerAccountId: j.strOrNull('broker_account_id'),
      );
}

class DailyPnl {
  const DailyPnl(this.date, this.netPnl, this.trades);
  final String date;
  final double netPnl;
  final int trades;
}

class BalancePoint {
  const BalancePoint(this.t, this.balance, this.equity);
  final String t;
  final double balance;
  final double equity;
}

class OverviewFigures {
  const OverviewFigures({this.balance, required this.todayPnl, required this.totalPnl, required this.openPnl, required this.openPositions, required this.activeStrategies});
  final double? balance;
  final double todayPnl;
  final double totalPnl;
  final double openPnl;
  final int openPositions;
  final int activeStrategies;

  factory OverviewFigures.fromJson(Json j) => OverviewFigures(
        balance: j.numOrNull('balance'),
        todayPnl: j.number('today_pnl'),
        totalPnl: j.number('total_pnl'),
        openPnl: j.number('open_pnl'),
        openPositions: j.integer('open_positions'),
        activeStrategies: j.integer('active_strategies'),
      );
}

/// GET /api/overview?account_id= — everything Home shows.
class Overview {
  const Overview({
    this.account,
    this.brokerName,
    this.brokerStatus,
    this.brokerDetail,
    required this.activeStrategies,
    required this.blockers,
    required this.dailyPnl,
    required this.balanceHistory,
    this.setup,
    this.figures,
    required this.robot,
    required this.positions,
  });

  final OverviewAccount? account;
  final String? brokerName;
  final ConnectionStatus? brokerStatus;
  final String? brokerDetail;
  final List<ActiveStrategy> activeStrategies;
  final List<Blocker> blockers;
  final List<DailyPnl> dailyPnl;
  final List<BalancePoint> balanceHistory;
  final SetupChecklist? setup;
  final OverviewFigures? figures;
  final TradingStatus robot;
  final List<Trade> positions;

  factory Overview.fromJson(Json j) {
    final broker = j.obj('broker');
    return Overview(
      account: j.obj('account') == null ? null : OverviewAccount.fromJson(j.obj('account')!),
      brokerName: broker?.strOrNull('name'),
      brokerStatus: broker == null ? null : ConnectionStatus.parse(broker.strOrNull('connection_status')),
      brokerDetail: broker?.strOrNull('connection_detail'),
      activeStrategies: j.objList('active_strategies').map(ActiveStrategy.fromJson).toList(),
      blockers: j.objList('blockers').map(Blocker.fromJson).toList(),
      dailyPnl: j.objList('daily_pnl').map((d) => DailyPnl(d.str('date'), d.number('net_pnl'), d.integer('trades'))).toList(),
      balanceHistory: j.objList('balance_history').map((p) => BalancePoint(p.str('t'), p.number('balance'), p.number('equity'))).toList(),
      setup: j.obj('setup') == null ? null : SetupChecklist.fromJson(j.obj('setup')!),
      figures: j.obj('figures') == null ? null : OverviewFigures.fromJson(j.obj('figures')!),
      robot: TradingStatus.fromJson(j.obj('robot') ?? const {}),
      positions: j.objList('positions').map(Trade.fromJson).toList(),
    );
  }
}

class RiskCheck {
  const RiskCheck(this.rule, this.passed, this.detail);
  final String rule;
  final bool passed;
  final String detail;

  factory RiskCheck.fromJson(Json j) => RiskCheck(j.str('rule', j.str('name')), j.boolean('passed'), j.str('detail'));
}

class Evaluation {
  const Evaluation({required this.id, required this.barTime, required this.outcome, required this.summary, required this.checks});
  final int id;
  final String barTime;

  /// SIGNAL | NO_SETUP | INSUFFICIENT_DATA
  final String outcome;
  final String summary;
  final List<RiskCheck> checks;

  factory Evaluation.fromJson(Json j) => Evaluation(
        id: j.integer('id'),
        barTime: j.str('bar_time'),
        outcome: j.str('outcome', 'NO_SETUP'),
        summary: j.str('summary'),
        checks: j.objList('checks').map(RiskCheck.fromJson).toList(),
      );
}

class Signal {
  const Signal({required this.id, required this.side, required this.barTime, required this.reasons, required this.status, this.rejectionReason, required this.riskChecks});
  final String id;
  final String side;
  final String barTime;
  final List<String> reasons;
  final String status;
  final String? rejectionReason;
  final List<RiskCheck> riskChecks;

  factory Signal.fromJson(Json j) => Signal(
        id: j.str('id'),
        side: j.str('side', 'BUY'),
        barTime: j.str('bar_time'),
        reasons: j.strList('reasons'),
        status: j.str('status'),
        rejectionReason: j.strOrNull('rejection_reason'),
        riskChecks: j.objList('risk_checks').map(RiskCheck.fromJson).toList(),
      );
}

class Order {
  const Order({required this.id, required this.purpose, required this.symbol, required this.side, required this.status, this.fillPrice, this.brokerMessage, required this.createdAt, this.environment});
  final String id;
  final String purpose;
  final String symbol;
  final String side;
  final String status;
  final String? fillPrice;
  final String? brokerMessage;
  final String createdAt;
  final AccountEnvironment? environment;

  factory Order.fromJson(Json j) => Order(
        id: j.str('id'),
        purpose: j.str('purpose', 'ENTRY'),
        symbol: j.str('symbol'),
        side: j.str('side', 'BUY'),
        status: j.str('status'),
        fillPrice: j.dec('fill_price'),
        brokerMessage: j.strOrNull('broker_message'),
        createdAt: j.str('created_at'),
        environment: j.obj('account') == null ? null : AccountEnvironment.parse(j.obj('account')!.strOrNull('environment')),
      );
}

class JournalEvent {
  const JournalEvent({required this.id, required this.occurredAt, required this.eventType, required this.message});
  final int id;
  final String occurredAt;
  final String eventType;
  final String message;

  factory JournalEvent.fromJson(Json j) => JournalEvent(
        id: j.integer('id'),
        occurredAt: j.str('occurred_at'),
        eventType: j.str('event_type'),
        message: j.str('message'),
      );
}

/// GET /api/trades/{id} — one trade, start to finish.
class TradeChain {
  const TradeChain({required this.trade, this.signal, this.evaluation, required this.orders, required this.events});
  final Trade trade;
  final Signal? signal;
  final Evaluation? evaluation;
  final List<Order> orders;
  final List<JournalEvent> events;

  factory TradeChain.fromJson(Json j) => TradeChain(
        trade: Trade.fromJson(j.obj('trade') ?? const {}),
        signal: j.obj('signal') == null ? null : Signal.fromJson(j.obj('signal')!),
        evaluation: j.obj('evaluation') == null ? null : Evaluation.fromJson(j.obj('evaluation')!),
        orders: j.objList('orders').map(Order.fromJson).toList(),
        events: j.objList('events').map(JournalEvent.fromJson).toList(),
      );
}
