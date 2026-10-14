import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/format.dart';
import '../../core/models/models.dart';
import '../../state/providers.dart';
import '../../state/push_registrar.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/badges.dart';
import '../../ui/widgets/dialogs.dart';
import '../../ui/widgets/states.dart';

const _empty = {
  'all': ('No notifications yet', 'Broker connections, trades, risk decisions and system events will show up here.'),
  'unread': ("You're all caught up", 'Every notification has been read.'),
  'critical': ('Nothing important', 'Important alerts — a broker that dropped, a halted platform — appear here.'),
};

/// Settings → Notifications: everything the robot and the platform told you,
/// plus push notifications for this phone.
class NotificationsScreen extends ConsumerStatefulWidget {
  const NotificationsScreen({super.key});

  @override
  ConsumerState<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends ConsumerState<NotificationsScreen> {
  String _filter = 'all';
  Object? _busy;

  Future<void> _mark([List<int>? ids]) async {
    setState(() => _busy = ids?.first ?? 'all');
    try {
      await ref.read(apiClientProvider).post('/notifications/read', body: ids == null ? <String, Object>{} : {'ids': ids});
      if (ids == null && mounted) showSnack(context, 'All notifications marked as read');
      await Future.wait([ref.read(notificationsProvider(_filter).notifier).load(), ref.read(unreadProvider.notifier).load()]);
    } catch (e) {
      if (mounted) showApiError(context, e, title: 'Could not mark as read');
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final res = ref.watch(notificationsProvider(_filter));
    final items = res.data?.data;
    final hasUnread = items?.any((n) => n.unread) ?? false;
    return Scaffold(
      appBar: AppBar(title: const Text('Notifications'), actions: [
        TextButton.icon(onPressed: _busy != null || !hasUnread ? null : () => _mark(), icon: const Icon(Icons.done_all_rounded, size: 18), label: const Text('Mark all read')),
        const SizedBox(width: 6),
      ]),
      body: RefreshIndicator(
        onRefresh: () async => ref.read(notificationsProvider(_filter).notifier).load(),
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 40), physics: const AlwaysScrollableScrollPhysics(), children: [
          const _PushCard(),
          const SizedBox(height: 16),
          SegmentedButton<String>(
            showSelectedIcon: false,
            segments: const [ButtonSegment(value: 'all', label: Text('All')), ButtonSegment(value: 'unread', label: Text('Unread')), ButtonSegment(value: 'critical', label: Text('Important'))],
            selected: {_filter},
            onSelectionChanged: (s) => setState(() => _filter = s.first),
          ),
          const SizedBox(height: 12),
          if (items == null)
            res.error != null ? ErrorView(error: res.error, onRetry: () => ref.read(notificationsProvider(_filter).notifier).load()) : const ListSkeleton(rows: 5, height: 80)
          else if (items.isEmpty)
            AppCard(child: EmptyState(icon: Icons.notifications_none_rounded, title: _empty[_filter]!.$1, message: _empty[_filter]!.$2))
          else
            AppCard(
              padding: EdgeInsets.zero,
              child: Column(children: [
                for (final n in items) _NotificationTile(n: n, busy: _busy != null, onMark: () => _mark([n.id])),
              ]),
            ),
          if (res.data != null && res.data!.total > (items?.length ?? 0))
            Padding(padding: const EdgeInsets.only(top: 10), child: Text('Showing the latest ${items!.length} of ${res.data!.total}.', style: context.text.bodySmall)),
        ]),
      ),
    );
  }
}

class _NotificationTile extends StatelessWidget {
  const _NotificationTile({required this.n, required this.busy, required this.onMark});
  final AppNotification n;
  final bool busy;
  final VoidCallback onMark;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final (PillTone tone, String label, Color dot) = switch (n.severity) {
      'success' => (PillTone.positive, 'Done', c.positive),
      'warning' => (PillTone.warning, 'Warning', c.warning),
      'critical' => (PillTone.negative, 'Important', c.negative),
      _ => (PillTone.info, 'Info', c.info),
    };
    return InkWell(
      onTap: n.tradeId != null ? () => context.push('/trades/${n.tradeId}') : null,
      child: Container(
        padding: const EdgeInsets.fromLTRB(14, 14, 8, 14),
        decoration: BoxDecoration(color: n.unread ? c.soft(c.primary, c.isDark ? 0.07 : 0.04) : null, border: Border(bottom: BorderSide(color: c.border))),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Padding(padding: const EdgeInsets.only(top: 6), child: Container(width: 8, height: 8, decoration: BoxDecoration(color: n.unread ? dot : Colors.transparent, shape: BoxShape.circle))),
          const SizedBox(width: 10),
          Expanded(
            child: Semantics(
              label: n.unread ? 'Unread' : null,
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  Text(n.title, style: TextStyle(fontWeight: n.unread ? FontWeight.w800 : FontWeight.w600, fontSize: 14.5)),
                  if (n.severity != 'info') Pill(label, tone: tone),
                ]),
                const SizedBox(height: 3),
                Text(n.message, style: context.text.bodySmall?.copyWith(fontSize: 13.5)),
                const SizedBox(height: 4),
                Text(formatRelative(n.createdAt), style: context.text.labelSmall?.copyWith(letterSpacing: 0, fontWeight: FontWeight.w500)),
              ]),
            ),
          ),
          if (n.unread) TextButton(onPressed: busy ? null : onMark, child: Text('Mark read', semanticsLabel: 'Mark “${n.title}” as read')),
        ]),
      ),
    );
  }
}

class _PushCard extends ConsumerWidget {
  const _PushCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final push = ref.watch(pushRegistrarProvider);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          secondary: IconBubble(Icons.notifications_active_outlined, color: c.brandInk, size: 38),
          title: const Text('Push notifications on this phone', style: TextStyle(fontWeight: FontWeight.w700)),
          subtitle: Text(!push.available
              ? 'Not available in this build'
              : push.enabled
                  ? 'On: trades, risk decisions and connection problems arrive even when the app is closed.'
                  : 'Off: alerts only appear in this list.'),
          value: push.enabled,
          onChanged: !push.available || push.busy
              ? null
              : (v) => v ? ref.read(pushRegistrarProvider.notifier).enable() : ref.read(pushRegistrarProvider.notifier).disable(),
        ),
        if (!push.available && push.reason != null) Notice(message: push.reason),
        if (push.error != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text(push.error!, style: TextStyle(color: c.negative, fontWeight: FontWeight.w600))),
      ]),
    );
  }
}
