import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:intl/intl.dart';
import 'package:package_info_plus/package_info_plus.dart';

import 'app.dart';
import 'core/config.dart';
import 'core/demo/demo_backend.dart';
import 'core/push/push_service.dart';
import 'state/providers.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  LicenseRegistry.addLicense(() async* {
    final ofl = await rootBundle.loadString('assets/fonts/OFL.txt');
    yield LicenseEntryWithLineBreaks(const ['Figtree'], ofl);
  });
  await initializeDateFormatting();
  final tag = Intl.canonicalizedLocale(PlatformDispatcher.instance.locale.toLanguageTag());
  Intl.defaultLocale = Intl.verifiedLocale(tag, (l) => DateFormat.localeExists(l) && NumberFormat.localeExists(l), onFailure: (_) => 'en_US');

  var version = '1.0.0';
  try {
    final info = await PackageInfo.fromPlatform();
    version = '${info.version}+${info.buildNumber}';
  } catch (_) {}

  final overrides = <Override>[appVersionProvider.overrideWithValue(version)];
  if (AppConfig.demoData) {
    // Debug-only fake backend for screenshots: no network, no real account.
    overrides.addAll(demoOverrides());
  } else {
    final push = await createPushService();
    overrides.add(pushServiceProvider.overrideWithValue(push));
  }

  runApp(ProviderScope(overrides: overrides, child: const TwoKPilotApp()));
}
