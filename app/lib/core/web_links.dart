import 'package:url_launcher/url_launcher.dart';

import 'config.dart';

/// Pages of the 2kPilot website for the things the app deliberately leaves
/// to the web: real money, connecting a broker, the strategy builder, MFA.
class WebLinks {
  const WebLinks._();

  static Uri page(String path) => Uri.parse('${AppConfig.webBaseUrl.replaceAll(RegExp(r'/+$'), '')}$path');

  static final Uri home = page('/');
  static final Uri signup = page('/signup');
  static final Uri realMoney = page('/settings?tab=accounts');
  static final Uri security = page('/settings?tab=security');
  static final Uri brokers = page('/settings?tab=brokers');
  static final Uri addBroker = page('/settings/brokers/new');
  static final Uri strategies = page('/strategies');
  static final Uri newStrategy = page('/strategies/new');
  static final Uri historyExport = page('/history?tab=closed');
  static Uri editStrategy(String id) => page('/strategies/$id/edit');

  /// Opens the page in the browser. Returns false when nothing could open it.
  static Future<bool> open(Uri uri) async {
    try {
      return await launchUrl(uri, mode: LaunchMode.externalApplication);
    } catch (_) {
      return false;
    }
  }
}
