import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/contracts.dart';
import '../../core/models/models.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/dialogs.dart';

const _commonMultipliers = [10, 20, 50, 100, 200];

/// "How should each trade work?" — contract family, then its settings, with
/// the ranges the broker allows (GET /api/markets/contracts).
class ContractFields extends StatelessWidget {
  const ContractFields({super.key, required this.spec, required this.onChanged, required this.families, this.offer, this.errors = const {}});
  final ContractSpec spec;
  final ValueChanged<ContractSpec> onChanged;
  final List<String> families;
  final ContractOffer? offer;
  final Map<String, String> errors;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final ranges = offer?.durations ?? const <DurationRange>[];
    final multipliers = (offer?.multipliers.isNotEmpty ?? false) ? offer!.multipliers : _commonMultipliers;
    Widget err(String key) => errors[key] == null
        ? const SizedBox.shrink()
        : Padding(padding: const EdgeInsets.only(top: 6), child: Text(errors[key]!, style: TextStyle(color: c.negative, fontWeight: FontWeight.w600, fontSize: 13)));

    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text('Contract type', style: context.text.titleSmall),
      const SizedBox(height: 8),
      if (families.isEmpty) Text('This market offers no contract 2kPilot can trade.', style: TextStyle(color: c.negative)),
      for (final f in families)
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Semantics(
            selected: spec.contractFamily == f,
            button: true,
            child: InkWell(
              borderRadius: BorderRadius.circular(14),
              onTap: () => onChanged(specForFamily(f, spec)),
              child: Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(14),
                  color: spec.contractFamily == f ? c.soft(c.primary, 0.08) : null,
                  border: Border.all(color: spec.contractFamily == f ? c.primary : c.border, width: spec.contractFamily == f ? 2 : 1),
                ),
                child: Row(children: [
                  Icon(spec.contractFamily == f ? Icons.radio_button_checked_rounded : Icons.radio_button_off_rounded, color: spec.contractFamily == f ? c.primary : c.subtle),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(familyLabel[f]!, style: const TextStyle(fontWeight: FontWeight.w800)),
                      Text(familyShort[f]!, style: context.text.bodySmall),
                    ]),
                  ),
                ]),
              ),
            ),
          ),
        ),
      err('contract_family'),
      Text(familyHelp[spec.contractFamily] ?? '', style: context.text.bodySmall?.copyWith(fontSize: 12.5)),
      if (spec.contractFamily == 'RISE_FALL') ...[
        const SizedBox(height: 14),
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
            child: TextFormField(
              key: ValueKey('duration-${spec.contractFamily}'),
              initialValue: spec.duration?.toString() ?? '',
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              style: tnum(const TextStyle(fontWeight: FontWeight.w600)),
              decoration: const InputDecoration(labelText: 'Lasts for'),
              onChanged: (v) => onChanged(spec.copyWith(duration: () => int.tryParse(v))),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: PickerField(
              label: 'Unit',
              value: durationUnits.firstWhere((u) => u.$1 == (spec.durationUnit ?? 'm'), orElse: () => durationUnits[2]).$2,
              onTap: () async {
                final u = await pickOption<String>(context, title: 'Unit', selected: spec.durationUnit, options: [for (final u in durationUnits) (u.$1, u.$2, null)]);
                if (u != null) onChanged(spec.copyWith(durationUnit: () => u));
              },
            ),
          ),
        ]),
        err('duration'),
        const SizedBox(height: 6),
        Text(
          "It settles automatically at expiry and can't be closed early.${ranges.isNotEmpty ? ' Allowed here: ${rangesText(ranges)}.' : ''} Strategies decide on closed candles, so a duration of a few candles works best.",
          style: context.text.bodySmall?.copyWith(fontSize: 12.5),
        ),
        if (offer?.riseFallAllowEquals ?? false)
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            value: spec.allowEquals,
            onChanged: (v) => onChanged(spec.copyWith(allowEquals: v ?? false)),
            title: const Text('Also win when the price ends exactly where it started (lower payout)', style: TextStyle(fontSize: 14)),
          ),
        err('allow_equals'),
      ],
      if (spec.contractFamily == 'MULTIPLIER') ...[
        const SizedBox(height: 14),
        PickerField(
          label: 'Multiplier',
          value: spec.multiplier == null ? 'Choose…' : '×${spec.multiplier}',
          error: errors['multiplier'],
          onTap: () async {
            final m = await pickOption<int>(context, title: 'Multiplier', selected: spec.multiplier, options: [for (final m in multipliers) (m, '×$m', null)]);
            if (m != null) onChanged(spec.copyWith(multiplier: () => m));
          },
        ),
        const SizedBox(height: 6),
        Text('Higher multipliers move faster both ways. You can never lose more than the stake.', style: context.text.bodySmall?.copyWith(fontSize: 12.5)),
        const SizedBox(height: 12),
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final key in ['take_profit_amount', 'stop_loss_amount']) ...[
            Expanded(
              child: TextFormField(
                initialValue: (key == 'take_profit_amount' ? spec.takeProfitAmount : spec.stopLossAmount) ?? '',
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                style: tnum(const TextStyle(fontWeight: FontWeight.w600)),
                decoration: InputDecoration(labelText: key == 'take_profit_amount' ? 'Take profit at' : 'Stop loss at', hintText: 'Optional', errorText: errors[key], errorMaxLines: 3),
                onChanged: (v) {
                  final value = v.trim().isEmpty ? null : v.trim().replaceAll(',', '.');
                  onChanged(key == 'take_profit_amount' ? spec.copyWith(takeProfitAmount: () => value) : spec.copyWith(stopLossAmount: () => value));
                },
              ),
            ),
            if (key == 'take_profit_amount') const SizedBox(width: 10),
          ],
        ]),
        const SizedBox(height: 6),
        Text("Money amounts. Leave them empty to use the strategy's own stop and target.", style: context.text.bodySmall?.copyWith(fontSize: 12.5)),
      ],
      if (spec.contractFamily == 'SPOT')
        Padding(
          padding: const EdgeInsets.only(top: 10),
          child: Text("Each trade is a position in lots with the strategy's stop loss and target, sized so that hitting the stop loses your risk per trade.", style: context.text.bodySmall),
        ),
    ]);
  }
}
