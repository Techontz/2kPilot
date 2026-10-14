import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/models/models.dart';
import '../../core/risk_form.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/badges.dart';
import '../../ui/widgets/dialogs.dart';
import '../../ui/widgets/states.dart';

/// Settings → Risk limits: the limits every trade must pass, per profile.
class RiskScreen extends ConsumerWidget {
  const RiskScreen({super.key});

  Future<void> _edit(BuildContext context, WidgetRef ref, RiskProfile? p, String? currency) async {
    final saved = await Navigator.of(context).push<bool>(MaterialPageRoute(fullscreenDialog: true, builder: (_) => ProfileEditorScreen(profile: p, currency: currency)));
    if (saved == true) {
      ref.read(riskProfilesProvider.notifier).load();
      ref.read(accountsProvider.notifier).load();
    }
  }

  Future<void> _delete(BuildContext context, WidgetRef ref, RiskProfile p) => confirmAction(
        context,
        title: 'Delete ${p.name}?',
        body: const ['This cannot be undone. A profile that is still assigned to an account cannot be deleted, and the Beginner profile is always kept.'],
        confirmLabel: 'Delete profile',
        destructive: true,
        onConfirm: () async {
          try {
            await ref.read(apiClientProvider).delete('/risk/profiles/${p.id}');
            ref.read(riskProfilesProvider.notifier).load();
            if (context.mounted) showSnack(context, 'Risk profile deleted', detail: p.name);
            return null;
          } on ApiException catch (e) {
            return e.message;
          }
        },
      );

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final res = ref.watch(riskProfilesProvider);
    final profiles = res.data;
    final account = ref.watch(currentAccountProvider);
    final accounts = ref.watch(accountsProvider.select((r) => r.data)) ?? const <Account>[];
    final currency = account?.currency;
    return Scaffold(
      appBar: AppBar(title: const Text('Risk limits'), actions: [IconButton(tooltip: 'New profile', onPressed: () => _edit(context, ref, null, currency), icon: const Icon(Icons.add_rounded))]),
      body: RefreshIndicator(
        onRefresh: () async => ref.read(riskProfilesProvider.notifier).load(),
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 40), physics: const AlwaysScrollableScrollPhysics(), children: [
          const SectionHeader('Risk profiles', subtitle: "Every automated and manual trade must pass its account's limits. A limit that cannot be checked blocks the trade."),
          if (profiles == null)
            res.error != null ? ErrorView(error: res.error, onRetry: () => ref.read(riskProfilesProvider.notifier).load()) : const ListSkeleton(rows: 2, height: 200)
          else if (profiles.isEmpty)
            AppCard(
              child: EmptyState(
                icon: Icons.shield_outlined,
                title: 'No risk profiles',
                message: 'Create a profile, then assign it to an account in Accounts. An account without one cannot trade.',
                action: FilledButton.icon(onPressed: () => _edit(context, ref, null, currency), icon: const Icon(Icons.add_rounded), label: const Text('New profile')),
              ),
            )
          else
            for (final p in profiles)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: AppCard(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Expanded(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(p.name, style: context.text.titleMedium),
                          Builder(builder: (_) {
                            final users = accounts.where((a) => a.riskProfile?.id == p.id).toList();
                            final n = p.accountsCount ?? users.length;
                            return Text(
                              '${n == 0 ? 'Not used by any account' : 'Used by $n account${n == 1 ? '' : 's'}'}${users.isNotEmpty ? ': ${users.map((a) => a.label).join(', ')}' : ''}',
                              style: context.text.bodySmall,
                            );
                          }),
                        ]),
                      ),
                      IconButton(tooltip: 'Delete ${p.name}', onPressed: () => _delete(context, ref, p), icon: Icon(Icons.delete_outline_rounded, color: c.subtle)),
                    ]),
                    const SizedBox(height: 8),
                    for (final s in limitSentences(p, currency))
                      Padding(
                        padding: const EdgeInsets.only(bottom: 4),
                        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Icon(s.off ? Icons.remove_rounded : Icons.check_rounded, size: 16, color: s.off ? c.subtle : c.brandInk),
                          const SizedBox(width: 8),
                          Expanded(child: Text(s.text, style: TextStyle(fontSize: 14, color: s.off ? c.subtle : c.fg))),
                        ]),
                      ),
                    const SizedBox(height: 8),
                    OutlinedButton.icon(onPressed: () => _edit(context, ref, p, currency), icon: const Icon(Icons.edit_outlined, size: 18), label: const Text('Edit limits')),
                  ]),
                ),
              ),
          if (account != null) ...[const SizedBox(height: 8), _Usage(accountId: account.id)],
        ]),
      ),
    );
  }
}

class _Usage extends ConsumerWidget {
  const _Usage({required this.accountId});
  final String accountId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final res = ref.watch(riskUsageProvider(accountId));
    final d = res.data;
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          Text('Limits used today', style: context.text.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
          if (d != null) ...[Text('· ${d.accountLabel}', style: context.text.bodySmall), EnvBadge(d.environment)],
        ]),
        const SizedBox(height: 4),
        Text(d == null ? 'For the account you are using.' : (d.profileName != null ? 'Profile: ${d.profileName}' : 'No risk profile assigned — this account cannot trade.'), style: context.text.bodySmall),
        const SizedBox(height: 12),
        if (d == null)
          res.error != null ? ErrorView(error: res.error) : const ListSkeleton(rows: 2, height: 30)
        else if (d.usage.isEmpty)
          Text('Nothing to show yet.', style: context.text.bodySmall)
        else
          for (final u in d.usage)
            Builder(builder: (_) {
              final pct = u.used != null && (u.limit ?? 0) > 0 ? (u.used! / u.limit! * 100).clamp(0, 100).round() : 0;
              final suffix = u.unit == '%' ? '%' : u.unit.isNotEmpty ? ' ${u.unit}' : '';
              String n(double v) => v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toStringAsFixed(2);
              return Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  Row(children: [
                    Expanded(child: Text(u.label, style: context.text.bodySmall?.copyWith(fontSize: 13.5))),
                    Text.rich(TextSpan(children: [
                      TextSpan(text: u.used == null ? '—' : '${n(u.used!)}$suffix'),
                      TextSpan(text: ' / ${u.limit == null ? 'no limit' : '${n(u.limit!)}$suffix'}', style: TextStyle(color: c.subtle)),
                    ]), style: tnum(const TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5))),
                  ]),
                  const SizedBox(height: 6),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(99),
                    child: LinearProgressIndicator(
                      value: pct / 100,
                      minHeight: 6,
                      color: pct >= 100 ? c.negative : pct >= 75 ? c.warning : c.brandInk,
                      semanticsLabel: '${u.label}: $pct% of the limit used',
                    ),
                  ),
                ]),
              );
            }),
      ]),
    );
  }
}

/// Create or edit a risk profile. Everyday (stake) limits first; Spot limits tucked away.
class ProfileEditorScreen extends ConsumerStatefulWidget {
  const ProfileEditorScreen({super.key, this.profile, this.currency});
  final RiskProfile? profile;
  final String? currency;

  @override
  ConsumerState<ProfileEditorScreen> createState() => _ProfileEditorScreenState();
}

class _ProfileEditorScreenState extends ConsumerState<ProfileEditorScreen> {
  late final ProfileForm _form = ProfileForm.from(widget.profile);
  bool _busy = false;
  ApiException? _error;
  bool _advanced = false;

  String? _err(String key) => _error?.field(key);

  Future<void> _save() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final api = ref.read(apiClientProvider);
      final body = _form.toBody();
      if (widget.profile != null) {
        await api.put('/risk/profiles/${widget.profile!.id}', body: body);
      } else {
        await api.post('/risk/profiles', body: body);
      }
      if (!mounted) return;
      showSnack(context, widget.profile != null ? 'Risk profile saved' : 'Risk profile created');
      Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e;
        if (advancedErrorKeys(e.fieldErrors).isNotEmpty) _advanced = true;
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _field(LimitField f) {
    final unit = unitLabel(f.unit, widget.currency);
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: TextFormField(
        initialValue: _form.values[f.key] ?? '',
        keyboardType: TextInputType.numberWithOptions(decimal: !f.integer),
        style: tnum(const TextStyle(fontWeight: FontWeight.w600)),
        decoration: InputDecoration(
          labelText: '${f.label}${unit.isNotEmpty ? ' ($unit)' : ''}${f.required ? ' *' : ''}',
          hintText: f.required ? 'required' : 'off',
          helperText: f.help,
          helperMaxLines: 3,
          errorText: _err(f.key),
          errorMaxLines: 3,
        ),
        onChanged: (v) => _form.values[f.key] = v,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final hiddenErrors = !_advanced && _error != null && advancedErrorKeys(_error!.fieldErrors).isNotEmpty;
    return Scaffold(
      appBar: AppBar(title: Text(widget.profile != null ? 'Edit ${widget.profile!.name}' : 'New risk profile')),
      body: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 24), children: [
        Text('Leave a limit empty to switch it off. STOP TRADING and the real-money lock always apply.', style: context.text.bodySmall?.copyWith(fontSize: 13.5)),
        const SizedBox(height: 16),
        TextFormField(
          initialValue: _form.name,
          maxLength: 120,
          decoration: InputDecoration(labelText: 'Name', errorText: _err('name')),
          onChanged: (v) => setState(() => _form.name = v),
        ),
        const SizedBox(height: 8),
        Text('Everyday limits', style: context.text.titleMedium),
        const SizedBox(height: 12),
        for (final f in basicFields) _field(f),
        if (hiddenErrors) const Padding(padding: EdgeInsets.only(bottom: 12), child: Notice(tone: NoticeTone.danger, message: 'Some advanced limits need fixing — open “Advanced (Spot trading on Paper)” below.')),
        Container(
          decoration: BoxDecoration(borderRadius: BorderRadius.circular(14), border: Border.all(color: c.border)),
          child: Theme(
            data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
            child: ExpansionTile(
              key: ValueKey(_advanced),
              initiallyExpanded: _advanced,
              onExpansionChanged: (v) => _advanced = v,
              title: const Text('Advanced (Spot trading on Paper)', style: TextStyle(fontWeight: FontWeight.w700)),
              childrenPadding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
              expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('These apply to Spot trades (lots and pips) on Paper accounts. Contract trades on Deriv use the everyday limits above.', style: context.text.bodySmall),
                for (final g in advancedGroups) ...[
                  const SizedBox(height: 16),
                  Text(g.$1, style: context.text.titleSmall),
                  const SizedBox(height: 10),
                  for (final f in g.$2) _field(f),
                ],
                const SizedBox(height: 8),
                Text('Trading hours', style: context.text.titleSmall),
                const SizedBox(height: 8),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  for (final s in sessions)
                    FilterChip(
                      label: Text(s.replaceAll('_', ' ').toLowerCase()),
                      selected: _form.sessions.contains(s),
                      onSelected: (on) => setState(() => on ? _form.sessions.add(s) : _form.sessions.remove(s)),
                      shape: const StadiumBorder(),
                    ),
                ]),
                const SizedBox(height: 6),
                Text('Market sessions the robot may trade in (none selected = any session).', style: context.text.bodySmall?.copyWith(fontSize: 12.5)),
                if (_err('allowed_sessions') != null) Text(_err('allowed_sessions')!, style: TextStyle(color: c.negative)),
                const SizedBox(height: 12),
                Row(children: [
                  Expanded(child: _TimeField(label: 'Only trade from (UTC)', value: _form.hoursStart, error: _err('trading_hours_start'), onChanged: (v) => setState(() => _form.hoursStart = v))),
                  const SizedBox(width: 10),
                  Expanded(child: _TimeField(label: 'Until (UTC)', value: _form.hoursEnd, error: _err('trading_hours_end'), onChanged: (v) => setState(() => _form.hoursEnd = v))),
                ]),
              ],
            ),
          ),
        ),
        if (_error != null && _error!.fieldErrors.isEmpty) Padding(padding: const EdgeInsets.only(top: 12), child: Notice(tone: NoticeTone.danger, message: _error!.message)),
      ]),
      bottomNavigationBar: SafeArea(
        child: Container(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
          decoration: BoxDecoration(border: Border(top: BorderSide(color: c.border))),
          child: Row(children: [
            Expanded(child: OutlinedButton(onPressed: _busy ? null : () => Navigator.pop(context), child: const Text('Cancel'))),
            const SizedBox(width: 10),
            Expanded(flex: 2, child: FilledButton(onPressed: _busy || _form.name.trim().isEmpty ? null : _save, child: Text(_busy ? 'Saving…' : 'Save profile'))),
          ]),
        ),
      ),
    );
  }
}

class _TimeField extends StatelessWidget {
  const _TimeField({required this.label, required this.value, required this.onChanged, this.error});
  final String label;
  final String value;
  final String? error;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return PickerField(
      label: label,
      value: value.isEmpty ? 'Any time' : value,
      error: error,
      onTap: () async {
        final parts = value.split(':');
        final t = await showTimePicker(
          context: context,
          initialTime: value.isEmpty ? const TimeOfDay(hour: 8, minute: 0) : TimeOfDay(hour: int.tryParse(parts[0]) ?? 8, minute: int.tryParse(parts.length > 1 ? parts[1] : '0') ?? 0),
          builder: (ctx, child) => MediaQuery(data: MediaQuery.of(ctx).copyWith(alwaysUse24HourFormat: true), child: child!),
        );
        if (t != null) onChanged('${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}');
      },
    );
  }
}
