import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/models/models.dart';
import '../../core/web_links.dart';
import '../../ui/theme.dart';
import '../shell/trading_control.dart';

class ChecklistStep {
  const ChecklistStep(this.key, this.title, this.detail, this.done, this.action);
  final String key;
  final String title;
  final String detail;
  final bool done;
  final Widget Function(BuildContext) action;
}

/// The four first-run steps, in order. The first unfinished one is "current".
List<ChecklistStep> checklistSteps(SetupChecklist s) => [
      ChecklistStep(
        'connect',
        'Connect Deriv or start Paper',
        'Paper practises with simulated money and needs no sign-up. A Deriv demo account uses real prices with virtual money.',
        s.hasAccount,
        (_) => FilledButton.icon(onPressed: () => WebLinks.open(WebLinks.addBroker), icon: const Icon(Icons.open_in_new_rounded, size: 18), label: const Text('Add an account on the website')),
      ),
      ChecklistStep(
        'strategy',
        'Pick a strategy',
        'Start from a ready-made template, build your own with simple rules, or describe it in your words.',
        s.hasStrategy,
        (ctx) => FilledButton(onPressed: () => ctx.go('/strategies?tab=templates'), child: const Text('Browse templates')),
      ),
      ChecklistStep(
        'test',
        'Test it on history',
        "See how the rules would have behaved on past prices before anything trades. Past results don't guarantee future ones.",
        s.hasBacktest,
        (ctx) => FilledButton(onPressed: () => ctx.go('/strategies'), child: const Text('Test a strategy')),
      ),
      ChecklistStep(
        'start',
        'Start in Demo',
        'Activate the strategy on your Paper or demo account, then press Start. You can stop at any moment with one tap.',
        s.hasActiveStrategy && s.tradingStarted,
        (ctx) => s.hasActiveStrategy
            ? FilledButton(
                style: FilledButton.styleFrom(backgroundColor: ctx.c.positive, foregroundColor: ctx.c.onPositive),
                onPressed: () => requestStart(ctx),
                child: const Text('Start trading'),
              )
            : FilledButton(onPressed: () => ctx.go('/strategies'), child: const Text('Activate a strategy')),
      ),
    ];

/// Friendly first-run guide shown on Home until the basics are in place.
class SetupChecklistCard extends StatelessWidget {
  const SetupChecklistCard({super.key, required this.setup});
  final SetupChecklist setup;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final steps = checklistSteps(setup);
    final done = steps.where((s) => s.done).length;
    final current = steps.indexWhere((s) => !s.done);
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        color: c.card,
        border: c.isDark ? null : Border.all(color: c.border),
        gradient: RadialGradient(center: const Alignment(1.1, -1.2), radius: 1.4, colors: [c.soft(c.primary, c.isDark ? 0.22 : 0.1), c.card]),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('YOUR FLIGHT PLAN', style: TextStyle(color: c.brandInk, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.4)),
        const SizedBox(height: 4),
        Semantics(header: true, child: Text('Get started in four steps', style: context.text.headlineSmall)),
        const SizedBox(height: 4),
        Text('Everything starts in Demo — no real money is involved until you deliberately choose otherwise.', style: context.text.bodySmall?.copyWith(fontSize: 13.5)),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(99),
              child: LinearProgressIndicator(value: done / steps.length, minHeight: 6, semanticsLabel: '$done of ${steps.length} steps done'),
            ),
          ),
          const SizedBox(width: 10),
          Text('$done/${steps.length}', style: tnum(TextStyle(color: c.muted, fontWeight: FontWeight.w800, fontSize: 12.5))),
        ]),
        const SizedBox(height: 14),
        for (var i = 0; i < steps.length; i++) _StepTile(step: steps[i], index: i, current: i == current),
      ]),
    );
  }
}

class _StepTile extends StatelessWidget {
  const _StepTile({required this.step, required this.index, required this.current});
  final ChecklistStep step;
  final int index;
  final bool current;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: current ? c.card : c.raised,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: current ? c.primary : c.border, width: current ? 2 : 1),
      ),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          width: 30,
          height: 30,
          alignment: Alignment.center,
          decoration: BoxDecoration(shape: BoxShape.circle, color: step.done ? c.positive : current ? c.primary : c.hover),
          child: step.done
              ? Icon(Icons.check_rounded, size: 18, color: c.onPositive, semanticLabel: 'Done')
              : Text('${index + 1}', style: TextStyle(fontWeight: FontWeight.w900, color: current ? Colors.white : c.muted)),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(step.title,
                style: TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: 14.5,
                  color: step.done ? c.muted : c.fg,
                  decoration: step.done ? TextDecoration.lineThrough : null,
                  decorationColor: c.subtle,
                )),
            if (!step.done) Padding(padding: const EdgeInsets.only(top: 3), child: Text(step.detail, style: context.text.bodySmall?.copyWith(fontSize: 13))),
            if (current) Padding(padding: const EdgeInsets.only(top: 10), child: step.action(context)),
          ]),
        ),
      ]),
    );
  }
}
