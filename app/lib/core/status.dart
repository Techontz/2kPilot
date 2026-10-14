/// "Is the robot running?" — ported from the web's lib/status.ts so the app
/// and the dashboard always say the same thing.
library;

import 'models/trading.dart';

enum Tone { positive, negative, warning, neutral, live, info }

class RobotStatus {
  const RobotStatus({required this.label, required this.tone, required this.detail, required this.running});
  final String label;
  final Tone tone;
  final String detail;
  final bool running;

  static const unknown = RobotStatus(
    label: 'Status unknown — reconnecting',
    tone: Tone.neutral,
    detail: "Can't reach the server for the latest status. Stop still works.",
    running: false,
  );
}

class EngineHealthView {
  const EngineHealthView({required this.code, required this.label, required this.message, required this.tone, required this.active, required this.banner});

  /// An EngineSummary code, or "unknown".
  final String code;
  final String label;
  final String message;
  final Tone tone;

  /// Automated trading can actually run (supervisor active).
  final bool active;

  /// Worth a banner (anything but a healthy, running engine).
  final bool banner;
}

const Map<String, Tone> _summaryTone = {'ok': Tone.positive, 'info': Tone.info, 'warning': Tone.warning, 'error': Tone.negative};

/// What to say about the trading engine. "Engine offline" is said only when
/// the engine's API cannot be reached; older servers without
/// `engine_summary` fall back to the heartbeat state.
EngineHealthView engineHealthView(TradingStatus status) {
  final s = status.engineSummary;
  if (s != null) {
    return EngineHealthView(
      code: s.code,
      label: s.label,
      message: s.message,
      tone: _summaryTone[s.tone] ?? Tone.warning,
      active: s.tradingActive,
      banner: !s.tradingActive || s.code != 'running',
    );
  }
  if (status.engineState == 'offline') {
    return EngineHealthView(
      code: 'unknown',
      label: 'Supervisor not running',
      message: status.engineDetail.isNotEmpty ? status.engineDetail : 'The trading supervisor is not reporting, so nothing will trade.',
      tone: Tone.warning,
      active: false,
      banner: true,
    );
  }
  if (status.engineState == 'degraded') {
    return EngineHealthView(code: 'running_degraded', label: 'Running · attention', message: status.engineDetail, tone: Tone.warning, active: true, banner: true);
  }
  return EngineHealthView(code: 'running', label: 'Engine running', message: status.engineDetail, tone: Tone.positive, active: true, banner: false);
}

/// The single answer to "Is the robot running?". A platform halt overrides
/// everything; then the user's own kill switch.
RobotStatus deriveRobotStatus(TradingStatus status) {
  if (status.platformHalted) {
    return RobotStatus(
      label: 'Halted by admin',
      tone: Tone.negative,
      detail: status.platformHaltReason ?? 'Trading is halted platform-wide by an administrator.',
      running: false,
    );
  }
  if (status.killSwitchEngaged) {
    return RobotStatus(
      label: 'Trading stopped',
      tone: Tone.warning,
      detail: status.killSwitchReason ?? 'Your trading is stopped. No new orders can be placed on your accounts.',
      running: false,
    );
  }
  if (status.tradingMode == 'LIVE' && status.liveTradingLocked) {
    return const RobotStatus(
      label: 'Blocked',
      tone: Tone.negative,
      detail: 'LIVE mode is selected but the server hard lock is on. Nothing can trade.',
      running: false,
    );
  }
  final engine = engineHealthView(status);
  if (!engine.active) {
    return RobotStatus(label: engine.label, tone: engine.tone, detail: engine.message, running: false);
  }
  if (engine.tone == Tone.warning) {
    return RobotStatus(label: engine.label, tone: Tone.warning, detail: engine.message, running: true);
  }
  return const RobotStatus(label: 'Running', tone: Tone.positive, detail: 'Strategies may open trades. Every order passes the risk engine.', running: true);
}

class ModeInfo {
  const ModeInfo(this.label, this.explanation);
  final String label;
  final String explanation;
}

const Map<String, ModeInfo> modeInfo = {
  'DEMO': ModeInfo('Demo', 'Orders may only go to demo accounts funded with virtual money.'),
  'LIVE': ModeInfo('LIVE', 'Orders use REAL MONEY on live accounts.'),
};

/// Start shows only when the status is known and trading is stopped;
/// otherwise Stop (always safe).
bool showsStart(TradingStatus? status, bool unknown) => status != null && !unknown && status.killSwitchEngaged;
