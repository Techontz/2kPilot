import 'dart:io' show HttpDate;
import 'dart:typed_data';

import 'package:dio/dio.dart';

import '../models/json.dart';

/// Every API failure, normalised: {status, code, message, fieldErrors}.
/// status 0 = the server could not be reached.
class ApiException implements Exception {
  const ApiException(this.status, this.code, this.message, {this.fieldErrors = const {}, this.problems = const [], this.retryAfter});

  final int status;
  final String code;
  final String message;
  final Map<String, List<String>> fieldErrors;

  /// Plain-English problems from the trading engine (e.g. an invalid rule set).
  final List<String> problems;

  /// Seconds from the Retry-After header (429 responses), if any.
  final int? retryAfter;

  static const networkMessage = 'Cannot reach the 2kPilot server. Check your connection and try again.';

  /// Real money and some account actions are website-only for the app.
  bool get isWebOnly => status == 403 && (code == 'live_requires_web' || code == 'web_only');

  /// The server requires two-factor authentication before anything else.
  bool get needsMfaEnrollment => status == 403 && code == 'mfa_enrollment_required';

  bool get isNetwork => status == 0;

  /// First validation message for a field, if any.
  String? field(String name) {
    final list = fieldErrors[name];
    return list == null || list.isEmpty ? null : list.first;
  }

  @override
  String toString() => 'ApiException($status, $code)';
}

/// Retry-After as seconds (it may also be an HTTP date); null when absent or unreadable.
int? parseRetryAfter(String? value, {DateTime? now}) {
  if (value == null || value.trim().isEmpty) return null;
  final seconds = num.tryParse(value.trim());
  if (seconds != null) return seconds < 0 ? 0 : seconds.ceil();
  try {
    final at = HttpDate.parse(value);
    final diff = at.difference(now ?? DateTime.now()).inMilliseconds;
    return diff <= 0 ? 0 : (diff / 1000).ceil();
  } catch (_) {
    return null;
  }
}

ApiException apiExceptionFrom(DioException e) {
  final response = e.response;
  if (response == null) {
    return const ApiException(0, 'network_error', ApiException.networkMessage);
  }
  final status = response.statusCode ?? 0;
  final data = response.data;
  final body = data is Map ? asJson(data) : const <String, dynamic>{};
  final errors = <String, List<String>>{};
  final rawErrors = body['errors'];
  if (rawErrors is Map) {
    rawErrors.forEach((k, v) {
      errors[k.toString()] = v is List ? v.map((e) => e.toString()).toList() : [v.toString()];
    });
  }
  final problems = body['problems'] is List ? (body['problems'] as List).map((e) => e.toString()).toList() : const <String>[];
  return ApiException(
    status,
    body.strOrNull('code') ?? (status == 422 ? 'validation_error' : 'http_error'),
    body.strOrNull('message') ?? 'Request failed ($status)',
    fieldErrors: errors,
    problems: problems,
    retryAfter: parseRetryAfter(response.headers.value('retry-after')),
  );
}

/// Typed transport to the Laravel API with a bearer token (no cookies, no CSRF).
///
/// Tokens are never logged: there is deliberately no logging interceptor.
class ApiClient {
  ApiClient({
    required String baseUrl,
    required String? Function() token,
    this.onUnauthorized,
    HttpClientAdapter? adapter,
    String userAgent = '2kPilot-Mobile',
  }) : _token = token,
       dio = Dio(
         BaseOptions(
           baseUrl: baseUrl,
           connectTimeout: const Duration(seconds: 15),
           receiveTimeout: const Duration(seconds: 75),
           sendTimeout: const Duration(seconds: 30),
           headers: {'Accept': 'application/json', 'User-Agent': userAgent},
           responseType: ResponseType.json,
         ),
       ) {
    if (adapter != null) dio.httpClientAdapter = adapter;
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          final t = _token();
          if (t != null && t.isNotEmpty) options.headers['Authorization'] = 'Bearer $t';
          handler.next(options);
        },
      ),
    );
  }

  final Dio dio;
  final String? Function() _token;

  /// Called once per 401 outside the sign-in endpoints: the token is no longer valid.
  void Function()? onUnauthorized;

  Future<Object?> request(String method, String path, {Object? body, Map<String, Object?>? query}) async {
    try {
      final response = await dio.request<Object?>(
        path,
        data: body,
        queryParameters: _clean(query),
        options: Options(method: method, contentType: body == null ? null : Headers.jsonContentType),
      );
      return response.data;
    } on DioException catch (e) {
      final error = apiExceptionFrom(e);
      if (error.status == 401 && !path.startsWith('/mobile/auth/')) onUnauthorized?.call();
      throw error;
    }
  }

  Future<Object?> get(String path, {Map<String, Object?>? query}) => request('GET', path, query: query);
  Future<Object?> post(String path, {Object? body}) => request('POST', path, body: body ?? const <String, dynamic>{});
  Future<Object?> put(String path, {Object? body}) => request('PUT', path, body: body ?? const <String, dynamic>{});
  Future<Object?> patch(String path, {Object? body}) => request('PATCH', path, body: body ?? const <String, dynamic>{});
  Future<Object?> delete(String path, {Object? body}) => request('DELETE', path, body: body);

  /// A file download (e.g. the history CSV) as bytes.
  Future<Uint8List> getBytes(String path) async {
    try {
      final response = await dio.get<List<int>>(path, options: Options(responseType: ResponseType.bytes, headers: {'Accept': 'text/csv, application/json'}));
      return Uint8List.fromList(response.data ?? const []);
    } on DioException catch (e) {
      final error = apiExceptionFrom(e);
      if (error.status == 401) onUnauthorized?.call();
      throw error;
    }
  }

  static Map<String, Object?>? _clean(Map<String, Object?>? query) {
    if (query == null) return null;
    final out = <String, Object?>{};
    query.forEach((k, v) {
      if (v != null && v != '') out[k] = v is bool ? (v ? 1 : 0) : v;
    });
    return out;
  }
}
