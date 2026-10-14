import 'dart:async';

import 'package:flutter/widgets.dart';

/// Rebuilds every [interval] while [enabled] (countdowns).
class NowBuilder extends StatefulWidget {
  const NowBuilder({super.key, required this.builder, this.enabled = true, this.interval = const Duration(seconds: 1)});
  final Widget Function(BuildContext context, DateTime now) builder;
  final bool enabled;
  final Duration interval;

  @override
  State<NowBuilder> createState() => _NowBuilderState();
}

class _NowBuilderState extends State<NowBuilder> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _sync();
  }

  @override
  void didUpdateWidget(covariant NowBuilder old) {
    super.didUpdateWidget(old);
    if (old.enabled != widget.enabled || old.interval != widget.interval) _sync();
  }

  void _sync() {
    _timer?.cancel();
    _timer = widget.enabled ? Timer.periodic(widget.interval, (_) => setState(() {})) : null;
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.builder(context, DateTime.now());
}
