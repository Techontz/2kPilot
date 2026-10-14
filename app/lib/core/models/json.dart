/// Tolerant readers for the Laravel API's JSON.
///
/// Money, prices and volumes arrive as DECIMAL strings (sometimes numbers on
/// older endpoints); they are kept as strings and only parsed for display.
library;

typedef Json = Map<String, dynamic>;

Json asJson(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return value.map((k, v) => MapEntry(k.toString(), v));
  return <String, dynamic>{};
}

List<Json> asJsonList(Object? value) {
  if (value is! List) return const [];
  return value.whereType<Map<dynamic, dynamic>>().map(asJson).toList(growable: false);
}

extension JsonRead on Json {
  String str(String key, [String fallback = '']) {
    final v = this[key];
    return v == null ? fallback : v.toString();
  }

  String? strOrNull(String key) {
    final v = this[key];
    if (v == null) return null;
    final s = v.toString();
    return s;
  }

  /// A decimal kept as text ("12.50"); numbers are converted to text.
  String? dec(String key) {
    final v = this[key];
    if (v == null || v == '') return null;
    return v.toString();
  }

  bool boolean(String key, [bool fallback = false]) {
    final v = this[key];
    if (v is bool) return v;
    if (v is num) return v != 0;
    if (v is String) return v == 'true' || v == '1';
    return fallback;
  }

  bool? boolOrNull(String key) {
    final v = this[key];
    if (v == null) return null;
    return boolean(key);
  }

  int integer(String key, [int fallback = 0]) => intOrNull(key) ?? fallback;

  int? intOrNull(String key) {
    final v = this[key];
    if (v is int) return v;
    if (v is num) return v.round();
    if (v is String) return int.tryParse(v) ?? double.tryParse(v)?.round();
    return null;
  }

  double? numOrNull(String key) {
    final v = this[key];
    if (v is num) return v.toDouble();
    if (v is String) return double.tryParse(v);
    return null;
  }

  double number(String key, [double fallback = 0]) => numOrNull(key) ?? fallback;

  Json? obj(String key) {
    final v = this[key];
    return v is Map ? asJson(v) : null;
  }

  List<Json> objList(String key) => asJsonList(this[key]);

  List<String> strList(String key) {
    final v = this[key];
    if (v is! List) return const [];
    return v.where((e) => e != null).map((e) => e.toString()).toList(growable: false);
  }

  List<String>? strListOrNull(String key) => this[key] is List ? strList(key) : null;
}

/// A Laravel paginator page.
class Paginated<T> {
  const Paginated({required this.data, required this.currentPage, required this.lastPage, required this.total});

  final List<T> data;
  final int currentPage;
  final int lastPage;
  final int total;

  static Paginated<T> fromJson<T>(Object? raw, T Function(Json) item) {
    final j = asJson(raw);
    final data = j.objList('data').map(item).toList(growable: false);
    return Paginated<T>(
      data: data,
      currentPage: j.integer('current_page', 1),
      lastPage: j.integer('last_page', 1),
      total: j.integer('total', data.length),
    );
  }
}
