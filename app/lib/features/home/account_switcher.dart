import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/format.dart';
import '../../core/web_links.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/badges.dart';

/// "Which account am I looking at?" — opens the account list.
class AccountSwitcherButton extends ConsumerWidget {
  const AccountSwitcherButton({super.key, required this.label});
  final String label;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    return Semantics(
      button: true,
      label: 'Account: $label. Change account',
      excludeSemantics: true,
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: () => showAccountSwitcher(context),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 40),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Flexible(child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 15.5, fontWeight: FontWeight.w700, color: c.muted))),
            Icon(Icons.unfold_more_rounded, size: 18, color: c.subtle),
          ]),
        ),
      ),
    );
  }
}

Future<void> showAccountSwitcher(BuildContext context) {
  return showModalBottomSheet<void>(useRootNavigator: true, 
    context: context,
    isScrollControlled: true,
    builder: (ctx) => Consumer(builder: (ctx, ref, _) {
      final c = ctx.c;
      final accounts = ref.watch(accountsProvider.select((r) => r.data)) ?? const [];
      final current = ref.watch(currentAccountProvider);
      return SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(ctx).height * 0.8),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Padding(padding: const EdgeInsets.fromLTRB(20, 0, 20, 4), child: Text('Accounts', style: ctx.text.titleLarge)),
            Padding(padding: const EdgeInsets.fromLTRB(20, 0, 20, 8), child: Text('Home and History show the account you choose.', style: ctx.text.bodySmall)),
            Flexible(
              child: ListView(shrinkWrap: true, children: [
                for (final a in accounts)
                  ListTile(
                    minTileHeight: 64,
                    leading: ConnectionDot(a.connectionStatus),
                    title: Text(a.label, maxLines: 1, overflow: TextOverflow.ellipsis),
                    subtitle: Text('${formatCurrency(a.balance, a.currency)} · ${a.broker}', style: tnum(ctx.text.bodySmall)),
                    trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                      EnvBadge(a.environment),
                      if (a.id == current?.id) Padding(padding: const EdgeInsets.only(left: 8), child: Icon(Icons.check_rounded, color: c.brandInk, semanticLabel: 'Selected')),
                    ]),
                    onTap: () {
                      ref.read(selectedAccountIdProvider.notifier).select(a.id);
                      Navigator.pop(ctx);
                    },
                  ),
              ]),
            ),
            const Divider(),
            ListTile(
              minTileHeight: 56,
              leading: const Icon(Icons.add_rounded),
              title: const Text('Add a broker'),
              subtitle: const Text('Connecting a broker is done on the website'),
              trailing: const Icon(Icons.open_in_new_rounded, size: 18),
              onTap: () {
                Navigator.pop(ctx);
                WebLinks.open(WebLinks.addBroker);
              },
            ),
            const SizedBox(height: 8),
          ]),
        ),
      );
    }),
  );
}
