import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api/api_client.dart';

/// A GET resource, like the web's useApi(): the last value that loaded, and
/// whether the latest request failed (then `data` is stale, not current).
class Resource<T> {
  const Resource({this.data, this.error, this.loaded = false});

  final T? data;
  final ApiException? error;

  /// At least one request finished (successfully or not).
  final bool loaded;

  bool get loading => !loaded && data == null && error == null;
  bool get hasData => data != null;

  /// The latest request failed: [data] (if any) is the last value that loaded.
  bool get stale => error != null;

  Resource<T> withData(T value) => Resource<T>(data: value, loaded: true);
  Resource<T> withError(ApiException e) => Resource<T>(data: data, error: e, loaded: true);
}

/// While the last request failed, poll at least this often so it recovers quickly.
const Duration failingRefresh = Duration(seconds: 5);

/// Fetches a resource, optionally re-fetching every [interval] while the app
/// is in the foreground. Requests are sequenced: only the newest request's
/// answer (or failure) is applied, so a slow old response never overwrites a
/// newer one. [set] applies a value the server just returned (a mutation's
/// response) and drops anything still in flight.
class ResourceController<T> extends StateNotifier<Resource<T>> {
  ResourceController(this._fetch, {this.interval, bool active = true, bool autoload = true})
      : _active = active,
        super(Resource<T>()) {
    if (autoload) {
      // After the first frame's listeners attach.
      scheduleMicrotask(() {
        if (mounted) load();
      });
    }
    _schedule();
  }

  final Future<T> Function() _fetch;
  final Duration? interval;
  bool _active;
  Timer? _timer;
  int _seq = 0;

  Duration? get _effectiveInterval {
    final base = interval;
    if (base == null) return null;
    return state.stale && base > failingRefresh ? failingRefresh : base;
  }

  void _schedule() {
    _timer?.cancel();
    _timer = null;
    final every = _effectiveInterval;
    if (every == null || !_active) return;
    _timer = Timer.periodic(every, (_) {
      if (mounted && _active) load();
    });
  }

  /// Fetch now. Resolves with the freshest value, or null when it could not be loaded.
  Future<T?> load() {
    final mine = ++_seq;
    final wasStale = state.stale;
    final future = _fetch().then<T?>((value) {
      if (!mounted || mine != _seq) return null;
      state = state.withData(value);
      if (wasStale) _schedule();
      return value;
    }, onError: (Object e) {
      if (!mounted || mine != _seq) return null;
      final error = e is ApiException ? e : const ApiException(0, 'unexpected', 'Something went wrong.');
      state = state.withError(error);
      if (!wasStale) _schedule();
      return null;
    });
    return future;
  }

  /// Use a value the server just returned; older in-flight requests are dropped.
  void set(T value) {
    _seq++;
    final wasStale = state.stale;
    state = state.withData(value);
    if (wasStale) _schedule();
  }

  /// The app moved to the foreground (refresh now) or background (pause polling).
  void setActive(bool active) {
    if (active == _active) return;
    _active = active;
    if (active) load();
    _schedule();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}
