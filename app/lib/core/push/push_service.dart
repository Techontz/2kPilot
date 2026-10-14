import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

enum PushPermission { granted, denied, notDetermined, unavailable }

/// Where a tapped notification should take the user.
class PushTap {
  const PushTap(this.data);
  final Map<String, String> data;

  String? get tradeId => data['trade_id'];

  /// /trades/{id} for a trade, the notifications list otherwise.
  String get route => tradeId != null && tradeId!.isNotEmpty ? '/trades/$tradeId' : '/settings/notifications';
}

/// Push notifications (Firebase Cloud Messaging). When Firebase is not
/// configured in this build, [NoopPushService] keeps the app working with
/// push disabled.
abstract class PushService {
  bool get available;

  /// Why push is unavailable (shown in Settings → Notifications).
  String? get unavailableReason;

  Future<PushPermission> permission();
  Future<PushPermission> requestPermission();

  /// The FCM registration token, or null.
  Future<String?> token();
  Stream<String> get tokenRefresh;

  /// A notification was tapped (also the one that launched the app).
  Stream<PushTap> get taps;

  /// A message arrived while the app was open (already shown as a local notification).
  Stream<Map<String, String>> get foregroundMessages;

  /// The tap that launched the app, if any (consumed once).
  PushTap? takeLaunchTap();
}

class NoopPushService implements PushService {
  NoopPushService([this.unavailableReason = notConfiguredReason]);

  static const notConfiguredReason =
      "Push notifications aren't set up in this build yet (Firebase isn't configured). Everything still appears in this list.";

  @override
  final String? unavailableReason;

  @override
  bool get available => false;

  @override
  Future<PushPermission> permission() async => PushPermission.unavailable;

  @override
  Future<PushPermission> requestPermission() async => PushPermission.unavailable;

  @override
  Future<String?> token() async => null;

  @override
  Stream<String> get tokenRefresh => const Stream.empty();

  @override
  Stream<PushTap> get taps => const Stream.empty();

  @override
  Stream<Map<String, String>> get foregroundMessages => const Stream.empty();

  @override
  PushTap? takeLaunchTap() => null;
}

/// Initialises Firebase defensively: missing google-services.json /
/// GoogleService-Info.plist (or any other failure) gives a [NoopPushService].
Future<PushService> createPushService({Future<void> Function()? initializeFirebase, Future<PushService> Function()? create}) async {
  try {
    await (initializeFirebase ?? () => Firebase.initializeApp().then((_) {}))().timeout(const Duration(seconds: 8));
  } catch (e) {
    if (kDebugMode) debugPrint('Push disabled: Firebase is not configured (${e.runtimeType}).');
    return NoopPushService();
  }
  try {
    return await (create ?? FirebasePushService.create)();
  } catch (e) {
    if (kDebugMode) debugPrint('Push disabled: ${e.runtimeType}');
    return NoopPushService('Push notifications could not start on this device.');
  }
}

const AndroidNotificationChannel tradingChannel = AndroidNotificationChannel(
  'trading',
  'Trading alerts',
  description: 'Trades opened and closed, risk decisions, broker connections and system alerts.',
  importance: Importance.high,
);

class FirebasePushService implements PushService {
  FirebasePushService._(this._messaging, this._local);

  final FirebaseMessaging _messaging;
  final FlutterLocalNotificationsPlugin _local;
  final _taps = StreamController<PushTap>.broadcast();
  final _foreground = StreamController<Map<String, String>>.broadcast();
  PushTap? _launchTap;
  int _nextId = 1;

  static Future<PushService> create() async {
    final service = FirebasePushService._(FirebaseMessaging.instance, FlutterLocalNotificationsPlugin());
    await service._init();
    return service;
  }

  Future<void> _init() async {
    await _local.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('@drawable/ic_notification'),
        iOS: DarwinInitializationSettings(requestAlertPermission: false, requestBadgePermission: false, requestSoundPermission: false),
      ),
      onDidReceiveNotificationResponse: (response) => _taps.add(PushTap(_decode(response.payload))),
    );
    await _local.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()?.createNotificationChannel(tradingChannel);
    // Foreground messages are shown by us (below), the same way on both platforms.
    await _messaging.setForegroundNotificationPresentationOptions(alert: false, badge: false, sound: false);

    FirebaseMessaging.onMessage.listen((message) {
      final data = message.data.map((k, v) => MapEntry(k, '$v'));
      final n = message.notification;
      if (n != null) {
        _local.show(
          id: _nextId++,
          title: n.title,
          body: n.body,
          payload: jsonEncode(data),
          notificationDetails: NotificationDetails(
            android: AndroidNotificationDetails(tradingChannel.id, tradingChannel.name,
                channelDescription: tradingChannel.description, importance: Importance.high, priority: Priority.high, icon: '@drawable/ic_notification'),
            iOS: const DarwinNotificationDetails(presentAlert: true, presentSound: true, presentBanner: true, presentList: true),
          ),
        );
      }
      _foreground.add(data);
    });
    FirebaseMessaging.onMessageOpenedApp.listen((m) => _taps.add(PushTap(m.data.map((k, v) => MapEntry(k, '$v')))));

    final initial = await _messaging.getInitialMessage();
    if (initial != null) {
      _launchTap = PushTap(initial.data.map((k, v) => MapEntry(k, '$v')));
    } else {
      final details = await _local.getNotificationAppLaunchDetails();
      if (details?.didNotificationLaunchApp ?? false) _launchTap = PushTap(_decode(details!.notificationResponse?.payload));
    }
  }

  static Map<String, String> _decode(String? payload) {
    if (payload == null || payload.isEmpty) return const {};
    try {
      final v = jsonDecode(payload);
      return v is Map ? v.map((k, val) => MapEntry('$k', '$val')) : const {};
    } catch (_) {
      return const {};
    }
  }

  @override
  bool get available => true;

  @override
  String? get unavailableReason => null;

  static PushPermission _map(AuthorizationStatus s) => switch (s) {
        AuthorizationStatus.authorized || AuthorizationStatus.provisional => PushPermission.granted,
        AuthorizationStatus.denied || AuthorizationStatus.deniedPermanently => PushPermission.denied,
        AuthorizationStatus.notDetermined => PushPermission.notDetermined,
      };

  @override
  Future<PushPermission> permission() async => _map((await _messaging.getNotificationSettings()).authorizationStatus);

  @override
  Future<PushPermission> requestPermission() async {
    final settings = await _messaging.requestPermission(alert: true, badge: true, sound: true);
    if (Platform.isAndroid) {
      await _local.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()?.requestNotificationsPermission();
    }
    return _map(settings.authorizationStatus);
  }

  @override
  Future<String?> token() async {
    if (Platform.isIOS) {
      // The APNs token arrives shortly after permission is granted.
      for (var i = 0; i < 10 && await _messaging.getAPNSToken() == null; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 500));
      }
    }
    return _messaging.getToken();
  }

  @override
  Stream<String> get tokenRefresh => _messaging.onTokenRefresh;

  @override
  Stream<PushTap> get taps => _taps.stream;

  @override
  Stream<Map<String, String>> get foregroundMessages => _foreground.stream;

  @override
  PushTap? takeLaunchTap() {
    final tap = _launchTap;
    _launchTap = null;
    return tap;
  }
}
