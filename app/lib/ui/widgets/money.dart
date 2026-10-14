import 'package:flutter/material.dart';

import '../../core/format.dart';
import '../theme.dart';

/// Signed P/L in the account currency: green for profit, red for loss.
class PnlText extends StatelessWidget {
  const PnlText(this.value, {super.key, this.currency, this.style});
  final Object? value;
  final String? currency;
  final TextStyle? style;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final color = switch (pnlTone(value)) {
      PnlTone.positive => c.positive,
      PnlTone.negative => c.negative,
      PnlTone.neutral => c.fg,
    };
    final text = formatSignedCurrency(value, currency);
    final word = switch (pnlTone(value)) { PnlTone.positive => 'profit', PnlTone.negative => 'loss', _ => '' };
    return Semantics(
      label: word.isEmpty ? text : '$text $word',
      excludeSemantics: true,
      child: Text(text, maxLines: 1, overflow: TextOverflow.ellipsis, style: tnum((style ?? const TextStyle(fontWeight: FontWeight.w700)).copyWith(color: color))),
    );
  }
}

class MoneyText extends StatelessWidget {
  const MoneyText(this.value, {super.key, this.currency, this.style});
  final Object? value;
  final String? currency;
  final TextStyle? style;

  @override
  Widget build(BuildContext context) =>
      Text(formatCurrency(value, currency), maxLines: 1, overflow: TextOverflow.ellipsis, style: tnum(style ?? TextStyle(color: context.c.fg, fontWeight: FontWeight.w600)));
}
