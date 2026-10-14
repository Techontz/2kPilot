import 'json.dart';
import 'trading.dart';

/// A risk profile. Its limits are kept as the raw decimal strings the API
/// sent (empty = the limit is off); see core/risk_form.dart for the fields.
class RiskProfile {
  const RiskProfile({required this.id, required this.name, this.accountsCount, required this.raw});
  final String id;
  final String name;
  final int? accountsCount;
  final Json raw;

  String? value(String key) => raw.dec(key);

  List<String> get allowedSessions => raw.strList('allowed_sessions');
  String? get tradingHoursStart => raw.strOrNull('trading_hours_start');
  String? get tradingHoursEnd => raw.strOrNull('trading_hours_end');

  factory RiskProfile.fromJson(Json j) => RiskProfile(
        id: j.str('id'),
        name: j.str('name'),
        accountsCount: j.intOrNull('accounts_count'),
        raw: j,
      );
}

class UsageRow {
  const UsageRow({required this.key, required this.label, this.used, this.limit, required this.unit});
  final String key;
  final String label;
  final double? used;
  final double? limit;
  final String unit;
}

class RiskUsage {
  const RiskUsage({required this.accountLabel, required this.environment, this.profileName, required this.usage});
  final String accountLabel;
  final AccountEnvironment environment;
  final String? profileName;
  final List<UsageRow> usage;

  factory RiskUsage.fromJson(Json j) {
    final a = j.obj('account') ?? const {};
    return RiskUsage(
      accountLabel: a.str('label'),
      environment: AccountEnvironment.parse(a.strOrNull('environment')),
      profileName: j.obj('profile')?.strOrNull('name'),
      usage: j.objList('usage').map((u) => UsageRow(key: u.str('key'), label: u.str('label'), used: u.numOrNull('used'), limit: u.numOrNull('limit'), unit: u.str('unit'))).toList(),
    );
  }
}

class AppNotification {
  const AppNotification({required this.id, required this.type, required this.severity, required this.title, required this.message, required this.createdAt, this.readAt, required this.data});
  final int id;
  final String type;

  /// info | success | warning | critical
  final String severity;
  final String title;
  final String message;
  final String createdAt;
  final String? readAt;
  final Json data;

  bool get unread => readAt == null;
  String? get tradeId => data.strOrNull('trade_id');

  factory AppNotification.fromJson(Json j) => AppNotification(
        id: j.integer('id'),
        type: j.str('type'),
        severity: j.str('severity', 'info'),
        title: j.str('title'),
        message: j.str('message'),
        createdAt: j.str('created_at'),
        readAt: j.strOrNull('read_at'),
        data: j.obj('data') ?? const {},
      );
}

class SystemStatus {
  const SystemStatus({
    required this.database,
    required this.queueConnection,
    required this.liveTradingEnabled,
    required this.brokerVaultConfigured,
    required this.derivAppIdConfigured,
    required this.mfaRequired,
    required this.trading,
    required this.engineStatus,
    this.engineVersion,
    this.engineService,
    this.engineSupervisor,
    this.engineSummary,
  });

  final String database;
  final String queueConnection;
  final bool liveTradingEnabled;
  final bool brokerVaultConfigured;
  final bool derivAppIdConfigured;
  final bool mfaRequired;
  final TradingStatus trading;
  final String engineStatus;
  final String? engineVersion;
  final EngineService? engineService;
  final EngineSupervisor? engineSupervisor;
  final EngineSummary? engineSummary;

  factory SystemStatus.fromJson(Json j) {
    final engine = j.obj('engine') ?? const {};
    return SystemStatus(
      database: j.str('database'),
      queueConnection: j.str('queue_connection'),
      liveTradingEnabled: j.boolean('live_trading_enabled'),
      brokerVaultConfigured: j.boolean('broker_vault_configured'),
      derivAppIdConfigured: j.boolean('deriv_app_id_configured'),
      mfaRequired: j.boolean('mfa_required'),
      trading: TradingStatus.fromJson(j.obj('trading') ?? const {}),
      engineStatus: engine.str('status'),
      engineVersion: engine.strOrNull('version'),
      engineService: j.obj('engine_service') == null ? null : EngineService.fromJson(j.obj('engine_service')!),
      engineSupervisor: j.obj('engine_supervisor') == null ? null : EngineSupervisor.fromJson(j.obj('engine_supervisor')!),
      engineSummary: j.obj('engine_summary') == null ? null : EngineSummary.fromJson(j.obj('engine_summary')!),
    );
  }
}

/// GET /api/auth/tokens — a signed-in device.
class DeviceToken {
  const DeviceToken({required this.id, required this.name, this.createdAt, this.lastUsedAt, this.expiresAt, required this.current});
  final String id;
  final String name;
  final String? createdAt;
  final String? lastUsedAt;
  final String? expiresAt;
  final bool current;

  factory DeviceToken.fromJson(Json j) => DeviceToken(
        id: j.str('id'),
        name: j.str('name', 'Device'),
        createdAt: j.strOrNull('created_at'),
        lastUsedAt: j.strOrNull('last_used_at'),
        expiresAt: j.strOrNull('expires_at'),
        current: j.boolean('current'),
      );
}
