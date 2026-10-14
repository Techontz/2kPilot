import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/contracts.dart';
import '../../core/insights.dart';
import '../../core/models/models.dart';
import '../../core/web_links.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/brand.dart';
import '../../ui/widgets/dialogs.dart';
import '../../ui/widgets/states.dart';
import 'backtest_sheet.dart';
import 'strategy_insights.dart';

const _levelOrder = {'beginner': 0, 'intermediate': 1, 'advanced': 2};

/// Copy a template into My strategies (POST /strategies/{id}/copy).
Future<bool> copyTemplate(BuildContext context, WidgetRef ref, Strategy t) async {
  final all = ref.read(strategiesProvider).data ?? const <Strategy>[];
  final name = uniqueName(t.name, all.where((s) => !s.builtIn).map((s) => s.name).toList());
  try {
    final copy = Strategy.fromJson(asJson(await ref.read(apiClientProvider).post('/strategies/${t.id}/copy', body: {'name': name})));
    ref.read(strategiesProvider.notifier).load();
    if (context.mounted) {
      showSnack(
        context,
        '“$name” is now in My strategies',
        detail: 'Review the rules, test it, then activate it.',
        action: isRuleBased(t) ? SnackBarAction(label: 'Edit on web', onPressed: () => WebLinks.open(WebLinks.editStrategy(copy.id))) : null,
      );
    }
    return true;
  } catch (e) {
    if (context.mounted) showApiError(context, e, title: "Couldn't copy the template");
    return false;
  }
}

/// Built-in templates as compact cards; the detail sheet has the full explanation.
class TemplateGallery extends ConsumerStatefulWidget {
  const TemplateGallery({super.key, required this.onCopied});
  final VoidCallback onCopied;

  @override
  ConsumerState<TemplateGallery> createState() => _TemplateGalleryState();
}

class _TemplateGalleryState extends ConsumerState<TemplateGallery> {
  String? _copying;

  Future<void> _use(Strategy t) async {
    setState(() => _copying = t.id);
    final ok = await copyTemplate(context, ref, t);
    if (mounted) setState(() => _copying = null);
    if (ok) widget.onCopied();
  }

  @override
  Widget build(BuildContext context) {
    final res = ref.watch(strategiesProvider);
    final data = res.data;
    final List<Widget> children;
    if (data == null) {
      children = [res.error != null ? ErrorView(error: res.error, onRetry: () => ref.read(strategiesProvider.notifier).load()) : const ListSkeleton(rows: 4, height: 96)];
    } else {
      final templates = data.where((s) => s.builtIn).toList()
        ..sort((a, b) {
          final la = _levelOrder[a.details.difficulty] ?? 3, lb = _levelOrder[b.details.difficulty] ?? 3;
          return la != lb ? la.compareTo(lb) : a.name.compareTo(b.name);
        });
      children = templates.isEmpty
          ? [const AppCard(child: EmptyState(icon: Icons.dashboard_customize_outlined, title: 'No templates available', message: 'The server has no built-in templates yet.'))]
          : [
              Padding(
                padding: const EdgeInsets.only(left: 2, bottom: 4),
                child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Text('Template library', style: context.text.headlineSmall),
                  Padding(padding: const EdgeInsets.only(left: 8, bottom: 2), child: Text('${templates.length}', style: context.text.labelMedium?.copyWith(color: context.c.subtle))),
                ]),
              ),
              Padding(padding: const EdgeInsets.only(left: 2, bottom: 12), child: Text('Learning starting points — none is claimed to be profitable.', style: context.text.bodySmall)),
              for (final t in templates)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: _TemplateCard(template: t, copying: _copying, onUse: () => _use(t), onOpen: () => _openSheet(t)),
                ),
            ];
    }
    return ListView(padding: const EdgeInsets.fromLTRB(16, 12, 16, 32), physics: const AlwaysScrollableScrollPhysics(), children: children);
  }

  Future<void> _openSheet(Strategy t) {
    return showModalBottomSheet<void>(useRootNavigator: true, 
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.9,
        maxChildSize: 0.95,
        builder: (ctx, scroll) => _TemplateSheet(
          template: t,
          scroll: scroll,
          onUse: () async {
            Navigator.pop(ctx);
            await _use(t);
          },
          onTest: () {
            Navigator.pop(ctx);
            showBacktestSheet(context, t);
          },
        ),
      ),
    );
  }
}

class DifficultyChip extends StatelessWidget {
  const DifficultyChip(this.level, {super.key});
  final String? level;

  @override
  Widget build(BuildContext context) {
    final l = level;
    if (l == null || l.isEmpty) return const SizedBox.shrink();
    final c = context.c;
    final bars = _levelOrder[l] == null ? 0 : _levelOrder[l]! + 1;
    return Container(
      height: 24,
      padding: const EdgeInsets.symmetric(horizontal: 9),
      decoration: BoxDecoration(color: c.hover, borderRadius: BorderRadius.circular(999), border: Border.all(color: c.border)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        if (bars > 0)
          ExcludeSemantics(
            child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              for (var b = 1; b <= 3; b++)
                Container(margin: const EdgeInsets.only(right: 2), width: 3, height: 4.0 + b * 2, decoration: BoxDecoration(color: b <= bars ? c.brandInk : c.lineStrong, borderRadius: BorderRadius.circular(1))),
            ]),
          ),
        const SizedBox(width: 4),
        Text(l[0].toUpperCase() + l.substring(1), style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: c.muted)),
      ]),
    );
  }
}

class _TemplateCard extends StatelessWidget {
  const _TemplateCard({required this.template, required this.copying, required this.onUse, required this.onOpen});
  final Strategy template;
  final String? copying;
  final VoidCallback onUse;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final t = template;
    final c = context.c;
    return AppCard(
      padding: EdgeInsets.zero,
      child: Column(children: [
        InkWell(
          onTap: onOpen,
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              Artwork(seed: '${t.name} ${t.description}', size: 64, radius: 10),
              const SizedBox(width: 14),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(t.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 15.5, letterSpacing: -0.2)),
                  const SizedBox(height: 2),
                  Text(t.description, maxLines: 2, overflow: TextOverflow.ellipsis, style: context.text.bodySmall),
                  const SizedBox(height: 6),
                  Row(children: [DifficultyChip(t.details.difficulty), const SizedBox(width: 8), Text('${strategyTimeframe(t)} candles', style: context.text.labelSmall?.copyWith(letterSpacing: 0, fontSize: 12))]),
                ]),
              ),
              Icon(Icons.chevron_right_rounded, color: c.subtle, semanticLabel: 'About ${t.name}'),
            ]),
          ),
        ),
        Container(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 10),
          decoration: BoxDecoration(border: Border(top: BorderSide(color: c.border))),
          child: Row(children: [
            Expanded(
              child: FilledButton.tonalIcon(
                style: FilledButton.styleFrom(backgroundColor: c.hover, foregroundColor: c.fg),
                onPressed: copying != null ? null : onUse,
                icon: const Icon(Icons.copy_rounded, size: 18),
                label: Text(copying == t.id ? 'Copying…' : 'Use', semanticsLabel: 'Use the ${t.name} template'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(child: TextButton.icon(onPressed: () => showBacktestSheet(context, t), icon: const Icon(Icons.science_outlined, size: 18), label: const Text('Test'))),
          ]),
        ),
      ]),
    );
  }
}

class _TemplateSheet extends StatelessWidget {
  const _TemplateSheet({required this.template, required this.scroll, required this.onUse, required this.onTest});
  final Strategy template;
  final ScrollController scroll;
  final VoidCallback onUse;
  final VoidCallback onTest;

  @override
  Widget build(BuildContext context) {
    final t = template;
    final d = t.details;
    final c = context.c;
    return Column(children: [
      Expanded(
        child: ListView(controller: scroll, padding: const EdgeInsets.fromLTRB(20, 0, 20, 20), children: [
          AspectRatio(aspectRatio: 5 / 2, child: Artwork(seed: '${t.name} ${t.description}', radius: 16)),
          const SizedBox(height: 14),
          Row(children: [DifficultyChip(d.difficulty), const SizedBox(width: 8), Text('TEMPLATE', style: context.text.labelSmall?.copyWith(letterSpacing: 1.2))]),
          const SizedBox(height: 8),
          Text(t.name, style: context.text.headlineMedium),
          const SizedBox(height: 4),
          Text(t.description, style: context.text.bodyMedium?.copyWith(color: c.muted)),
          if (d.howItWorks != null) ...[const SizedBox(height: 18), _h(context, 'How it works'), Text(d.howItWorks!, style: const TextStyle(height: 1.5))],
          if (d.struggles != null) ...[const SizedBox(height: 16), _h(context, 'When it struggles'), Text(d.struggles!, style: TextStyle(height: 1.5, color: c.muted))],
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
            decoration: BoxDecoration(color: c.raised, borderRadius: BorderRadius.circular(14)),
            child: KeyValueList([
              ('Candles', KV(strategyTimeframe(t))),
              if (d.suggestedSymbols.isNotEmpty) ('Markets', KV(d.suggestedSymbols.join(', '))),
              if (d.suggestedContract != null) ('Contract', KV(contractSummary(d.suggestedContract).replaceFirst(RegExp(r' · stake from risk profile$'), ''))),
            ]),
          ),
          if (t.key != 'rules') ...[const SizedBox(height: 14), StrategyInsights(strategy: t)],
          if (d.suggestedContractNote != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(d.suggestedContractNote!, style: context.text.bodySmall)),
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(borderRadius: BorderRadius.circular(12), border: Border.all(color: c.border)),
            child: Text(
              d.disclaimer ?? 'Educational template — not a recommendation. No strategy is claimed to be profitable; test it on history and run it on a demo account first.',
              style: context.text.bodySmall?.copyWith(fontSize: 12.5),
            ),
          ),
        ]),
      ),
      SafeArea(
        top: false,
        child: Container(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          decoration: BoxDecoration(border: Border(top: BorderSide(color: c.border))),
          child: Row(children: [
            Expanded(child: FilledButton.icon(onPressed: onUse, icon: const Icon(Icons.copy_rounded, size: 18), label: const Text('Use this template'))),
            const SizedBox(width: 10),
            OutlinedButton.icon(
              onPressed: onTest,
              icon: const Icon(Icons.science_outlined, size: 18),
              label: const Text('Test'),
            ),
          ]),
        ),
      ),
    ]);
  }

  Widget _h(BuildContext context, String text) => Padding(padding: const EdgeInsets.only(bottom: 6), child: Text(text.toUpperCase(), style: context.text.labelSmall?.copyWith(letterSpacing: 1.2)));
}
