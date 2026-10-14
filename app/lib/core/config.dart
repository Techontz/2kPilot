import 'package:flutter/foundation.dart';

/// Build-time configuration (`--dart-define=KEY=value`).
class AppConfig {
  const AppConfig._();

  /// The Laravel backend (all routes live under /api).
  /// Dev examples: http://10.0.2.2:8421 (Android emulator), http://127.0.0.1:8421 (iOS simulator).
  static const String apiBaseUrl = String.fromEnvironment('API_BASE_URL', defaultValue: 'https://2kpilot.techon.co.tz');

  /// The 2kPilot website: real money, broker connections, the strategy builder, MFA set-up.
  static const String webBaseUrl = String.fromEnvironment('WEB_BASE_URL', defaultValue: 'https://www.2kpilot.online');

  /// Debug/profile only: serve canned data from an in-app fake backend (no network,
  /// no sign-in). Compiled out of release builds — `kReleaseMode` is a constant.
  static const bool demoData = !kReleaseMode && bool.fromEnvironment('DEMO_DATA');

  /// Debug only: open the app on this route (screenshots).
  static const String demoRoute = kReleaseMode ? '' : String.fromEnvironment('DEMO_ROUTE');

  static String get apiRoot => '${apiBaseUrl.replaceAll(RegExp(r'/+$'), '')}/api';
}
