import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/web_links.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../shell/app_shell.dart';
import 'backtests_list.dart';
import 'my_strategies.dart';
import 'template_gallery.dart';

/// STRATEGIES — my strategies, templates and tests on history.
/// A strategy is a set of simple rules the bot follows.
class StrategiesScreen extends ConsumerStatefulWidget {
  const StrategiesScreen({super.key, this.initialTab});
  final String? initialTab;

  @override
  ConsumerState<StrategiesScreen> createState() => _StrategiesScreenState();
}

class _StrategiesScreenState extends ConsumerState<StrategiesScreen> with SingleTickerProviderStateMixin {
  static const tabs = ['mine', 'templates', 'backtests'];
  late final TabController _tabs = TabController(length: 3, vsync: this, initialIndex: _indexOf(widget.initialTab));

  static int _indexOf(String? t) => t == null || !tabs.contains(t) ? 0 : tabs.indexOf(t);

  @override
  void didUpdateWidget(covariant StrategiesScreen old) {
    super.didUpdateWidget(old);
    if (widget.initialTab != old.initialTab && widget.initialTab != null) _tabs.index = _indexOf(widget.initialTab);
  }

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  void showTab(String tab) => _tabs.animateTo(_indexOf(tab));

  Future<void> _add() async {
    await showModalBottomSheet<void>(useRootNavigator: true, 
      context: context,
      isScrollControlled: true,
      builder: (ctx) {
        Widget choice(IconData icon, String title, String detail, VoidCallback onTap, {bool web = false, String? badge}) => ListTile(
              minTileHeight: 72,
              leading: Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(color: ctx.c.soft(ctx.c.primary, 0.16), borderRadius: BorderRadius.circular(12)),
                child: Icon(icon, color: ctx.c.brandInk),
              ),
              title: Row(children: [
                Flexible(child: Text(title)),
                if (badge != null) ...[const SizedBox(width: 8), Text(badge, style: TextStyle(fontSize: 11.5, color: ctx.c.brandInk, fontWeight: FontWeight.w800))],
              ]),
              subtitle: Text(detail),
              trailing: web ? Icon(Icons.open_in_new_rounded, size: 18, color: ctx.c.subtle) : Icon(Icons.chevron_right_rounded, color: ctx.c.subtle),
              onTap: () {
                Navigator.pop(ctx);
                onTap();
              },
            );
        return SafeArea(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(padding: const EdgeInsets.fromLTRB(20, 0, 20, 2), child: Text('Add a strategy', style: ctx.text.titleLarge)),
            Padding(padding: const EdgeInsets.fromLTRB(20, 0, 20, 10), child: Text('Nothing is saved until you choose to.', style: ctx.text.bodySmall)),
            choice(Icons.dashboard_customize_outlined, 'Start from a template', 'Ready-made starting points, explained in plain words.', () => showTab('templates'), badge: 'Best for beginners'),
            choice(Icons.tune_rounded, 'Build it step by step', 'The visual rule builder — on the website.', () => WebLinks.open(WebLinks.newStrategy), web: true),
            choice(Icons.chat_bubble_outline_rounded, 'Describe it', 'Write the idea in your words; review the draft — on the website (Add strategy → Describe it).', () => WebLinks.open(WebLinks.strategies), web: true),
            choice(Icons.upload_file_rounded, 'Import a file', 'A .json strategy file — on the website.', () => WebLinks.open(WebLinks.strategies), web: true),
            const SizedBox(height: 10),
          ]),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return TabPage(
      title: 'Strategies',
      actions: [IconButton(tooltip: 'Add a strategy', onPressed: _add, icon: const Icon(Icons.add_circle_outline_rounded))],
      bottom: PreferredSize(
        preferredSize: const Size.fromHeight(52),
        child: Align(
          alignment: Alignment.centerLeft,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
            child: SizedBox(
              height: 40,
              child: TabBar(controller: _tabs, isScrollable: true, tabs: const [Tab(text: 'My strategies'), Tab(text: 'Templates'), Tab(text: 'Tests')]),
            ),
          ),
        ),
      ),
      body: TabBarView(controller: _tabs, children: [
        RefreshIndicator(
          onRefresh: () async => ref.read(strategiesProvider.notifier).load(),
          child: MyStrategies(onBrowseTemplates: () => showTab('templates'), onAdd: _add),
        ),
        RefreshIndicator(
          onRefresh: () async => ref.read(strategiesProvider.notifier).load(),
          child: TemplateGallery(onCopied: () => showTab('mine')),
        ),
        RefreshIndicator(onRefresh: () async => ref.read(backtestsProvider.notifier).load(), child: const BacktestsList()),
      ]),
    );
  }
}
