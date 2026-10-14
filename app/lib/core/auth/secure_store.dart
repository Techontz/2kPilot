import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Small key/value storage. The token lives ONLY here — Keychain on iOS,
/// encrypted storage on Android — never in plain preferences.
abstract class SecureStore {
  Future<String?> read(String key);
  Future<void> write(String key, String? value);
}

class DeviceSecureStore implements SecureStore {
  DeviceSecureStore()
      : _storage = const FlutterSecureStorage(
          // The token never leaves this device (no iCloud Keychain sync, no backups).
          iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock_this_device),
        );

  final FlutterSecureStorage _storage;

  @override
  Future<String?> read(String key) async {
    try {
      return await _storage.read(key: key);
    } catch (_) {
      return null; // unreadable after a restore to another device: treat as signed out
    }
  }

  @override
  Future<void> write(String key, String? value) async {
    if (value == null) {
      await _storage.delete(key: key);
    } else {
      await _storage.write(key: key, value: value);
    }
  }
}

/// In-memory storage for tests and the debug demo mode.
class MemorySecureStore implements SecureStore {
  MemorySecureStore([Map<String, String>? initial]) : values = {...?initial};
  final Map<String, String> values;

  @override
  Future<String?> read(String key) async => values[key];

  @override
  Future<void> write(String key, String? value) async {
    if (value == null) {
      values.remove(key);
    } else {
      values[key] = value;
    }
  }
}

class StoreKeys {
  static const token = 'auth.token';
  static const user = 'auth.user';
  static const account = 'app.account';
  static const theme = 'app.theme';
  static const pushAsked = 'push.asked';
  static const pushEnabled = 'push.enabled';
  static const pushToken = 'push.token';
}
