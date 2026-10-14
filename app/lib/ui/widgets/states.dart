import 'package:flutter/material.dart';

import '../../core/api/api_client.dart';
import '../../core/web_links.dart';
import '../theme.dart';

/// Rounded surface card (borderless on dark like the web, hairline on light).
class AppCard extends StatelessWidget {
  const AppCard({super.key, required this.child, this.padding = const EdgeInsets.all(16), this.onTap, this.color, this.border, this.radius = 16});
  final Widget child;
  final EdgeInsetsGeometry padding;
  final VoidCallback? onTap;
  final Color? color;
  final BoxBorder? border;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final shape = BorderRadius.circular(radius);
    return Material(
      color: color ?? c.card,
      borderRadius: shape,
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        borderRadius: shape,
        child: Container(
          padding: padding,
          decoration: BoxDecoration(borderRadius: shape, border: border ?? (c.isDark ? null : Border.all(color: c.border))),
          child: child,
        ),
      ),
    );
  }
}

class SectionHeader extends StatelessWidget {
  const SectionHeader(this.title, {super.key, this.subtitle, this.trailing, this.padding = const EdgeInsets.fromLTRB(4, 8, 4, 12)});
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: padding,
      child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Semantics(header: true, child: Text(title, style: context.text.titleLarge)),
            if (subtitle != null) Padding(padding: const EdgeInsets.only(top: 3), child: Text(subtitle!, style: context.text.bodySmall)),
          ]),
        ),
        ?trailing,
      ]),
    );
  }
}

enum NoticeTone { info, success, warning, danger, live }

class Notice extends StatelessWidget {
  const Notice({super.key, this.title, this.message, this.tone = NoticeTone.info, this.child, this.action});
  final String? title;
  final String? message;
  final NoticeTone tone;
  final Widget? child;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final (Color color, IconData icon) = switch (tone) {
      NoticeTone.info => (c.info, Icons.info_outline_rounded),
      NoticeTone.success => (c.positive, Icons.check_circle_outline_rounded),
      NoticeTone.warning => (c.warning, Icons.warning_amber_rounded),
      NoticeTone.danger => (c.negative, Icons.error_outline_rounded),
      NoticeTone.live => (c.live, Icons.report_rounded),
    };
    return Semantics(
      container: true,
      liveRegion: tone == NoticeTone.danger,
      child: Container(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        decoration: BoxDecoration(
          color: c.soft(color, tone == NoticeTone.info ? 0.08 : 0.1),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: c.soft(color, 0.3)),
        ),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Padding(padding: const EdgeInsets.only(top: 1), child: Icon(icon, size: 20, color: color)),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (title != null) Text(title!, style: TextStyle(fontWeight: FontWeight.w800, color: tone == NoticeTone.info ? c.fg : color, fontSize: 14.5)),
              if (message != null) Padding(padding: EdgeInsets.only(top: title == null ? 0 : 3), child: Text(message!, style: context.text.bodySmall?.copyWith(color: c.muted, fontSize: 13.5))),
              if (child != null) Padding(padding: EdgeInsets.only(top: title == null && message == null ? 0 : 6), child: child!),
              if (action != null) Padding(padding: const EdgeInsets.only(top: 8), child: action!),
            ]),
          ),
        ]),
      ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.icon, required this.title, this.message, this.action, this.compact = false});
  final IconData icon;
  final String title;
  final String? message;
  final Widget? action;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Padding(
      padding: EdgeInsets.symmetric(vertical: compact ? 18 : 32, horizontal: 16),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Container(
          width: compact ? 48 : 60,
          height: compact ? 48 : 60,
          decoration: BoxDecoration(color: c.hover, shape: BoxShape.circle),
          child: Icon(icon, color: c.muted, size: compact ? 22 : 28),
        ),
        const SizedBox(height: 14),
        Text(title, textAlign: TextAlign.center, style: context.text.titleMedium),
        if (message != null) ...[
          const SizedBox(height: 6),
          Text(message!, textAlign: TextAlign.center, style: context.text.bodySmall?.copyWith(fontSize: 13.5)),
        ],
        if (action != null) ...[const SizedBox(height: 16), action!],
      ]),
    );
  }
}

/// A failed load, in plain words, with Retry — and a website button for
/// web-only actions and accounts that must set up two-factor first.
class ErrorView extends StatelessWidget {
  const ErrorView({super.key, required this.error, this.onRetry});
  final ApiException? error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final e = error;
    if (e != null && e.needsMfaEnrollment) {
      return Notice(
        tone: NoticeTone.warning,
        title: 'Set up two-factor authentication first',
        message: '${e.message} Do this on the 2kPilot website, then come back.',
        action: FilledButton.icon(onPressed: () => WebLinks.open(WebLinks.security), icon: const Icon(Icons.open_in_new_rounded, size: 18), label: const Text('Open the website')),
      );
    }
    if (e != null && e.isWebOnly) {
      return Notice(
        tone: NoticeTone.info,
        title: 'Do this on the 2kPilot website',
        message: e.message,
        action: OutlinedButton.icon(onPressed: () => WebLinks.open(WebLinks.home), icon: const Icon(Icons.open_in_new_rounded, size: 18), label: const Text('Open the website')),
      );
    }
    return Notice(
      tone: NoticeTone.danger,
      title: e?.isNetwork == true ? "You're offline" : "Couldn't load this",
      message: e?.message ?? 'Something went wrong.',
      action: onRetry == null ? null : OutlinedButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh_rounded, size: 18), label: const Text('Try again')),
    );
  }
}

class Skeleton extends StatelessWidget {
  const Skeleton({super.key, this.width, required this.height, this.radius = 10});
  final double? width;
  final double height;
  final double radius;

  @override
  Widget build(BuildContext context) =>
      Container(width: width, height: height, decoration: BoxDecoration(color: context.c.hover.withValues(alpha: context.c.isDark ? 0.7 : 1), borderRadius: BorderRadius.circular(radius)));
}

class ListSkeleton extends StatelessWidget {
  const ListSkeleton({super.key, this.rows = 4, this.height = 76});
  final int rows;
  final double height;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Loading',
      child: Column(children: [
        for (var i = 0; i < rows; i++) Padding(padding: const EdgeInsets.only(bottom: 10), child: Skeleton(height: height, radius: 16)),
      ]),
    );
  }
}

/// Label → value rows (trade details, system status).
class KeyValueList extends StatelessWidget {
  const KeyValueList(this.items, {super.key});
  final List<(String, Widget)> items;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Column(children: [
      for (var i = 0; i < items.length; i++)
        Container(
          padding: const EdgeInsets.symmetric(vertical: 11),
          decoration: BoxDecoration(border: i == items.length - 1 ? null : Border(bottom: BorderSide(color: c.border))),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(flex: 4, child: Text(items[i].$1, style: context.text.bodySmall?.copyWith(fontSize: 13.5))),
            const SizedBox(width: 12),
            Expanded(flex: 6, child: Align(alignment: Alignment.centerRight, child: DefaultTextStyle.merge(textAlign: TextAlign.right, style: tnum(TextStyle(color: c.fg, fontWeight: FontWeight.w600, fontSize: 14)), child: items[i].$2))),
          ]),
        ),
    ]);
  }
}

class KV extends StatelessWidget {
  const KV(this.text, {super.key});
  final String text;
  @override
  Widget build(BuildContext context) => Text(text, textAlign: TextAlign.right);
}

/// A small icon in a soft circle (KPI headers, list leading icons).
class IconBubble extends StatelessWidget {
  const IconBubble(this.icon, {super.key, this.color, this.size = 30});
  final IconData icon;
  final Color? color;
  final double size;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(color: color == null ? c.hover : c.soft(color!, 0.15), shape: BoxShape.circle),
      child: Icon(icon, size: size * 0.52, color: color ?? c.fg),
    );
  }
}
