import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_client.dart';
import '../../core/contracts.dart';
import '../../core/format.dart';
import '../../core/insights.dart';
import '../../core/models/models.dart';
import '../../core/web_links.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/badges.dart';
import '../../ui/widgets/dialogs.dart';
import '../../ui/widgets/states.dart';
import '../shell/trading_control.dart';
import 'contract_fields.dart';

/// Activate = run this strategy's latest version on one account + market with
/// a contract. Afterwards it says honestly whether anything will trade, and why not.
Future<void> showActivateSheet(BuildContext context, Strategy strategy) {
  return showModalBottomSheet<void>(useRootNavigator: true, 
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) => DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.94,
      minChildSize: 0.5,
      maxChildSize: 0.94,
      builder: (ctx, scroll) => ActivateForm(strategy: strategy, scroll: scroll),
    ),
  );
}

class ActivateForm extends ConsumerStatefulWidget {
  const ActivateForm({super.key, required this.strategy, required this.scroll});
  final Strategy strategy;
  final ScrollController scroll;

  @override
  ConsumerState<ActivateForm> createState() => _ActivateFormState();
}

class _ActivateFormState extends ConsumerState<ActivateForm> {
  String _accountId = '';
  List<Instrument>? _instruments;
  ApiException? _instrumentsError;
  Map<String, ContractOffer?> _suggestedOffers = {};
  bool _offersReady = false;
  String _symbol = '';
  ContractOffer? _offer;
  bool _offerLoading = false;
  ApiException? _offerError;
  ContractSpec? _spec;
  bool _customStake = false;
  bool _busy = false;
  ApiException? _error;
  ActivationResult? _result;
  int _seq = 0;

  Strategy get strategy => widget.strategy;

  @override
  void initState() {
    super.initState();
    final accounts = ref.read(accountsProvider).data ?? const <Account>[];
    _accountId = ref.read(currentAccountProvider)?.id ?? (accounts.isEmpty ? '' : accounts.first.id);
    if (_accountId.isNotEmpty) _loadAccount();
  }

  Account? get _account => (ref.read(accountsProvider).data ?? const <Account>[]).where((a) => a.id == _accountId).firstOrNull;

  List<Instrument> get _tradable {
    final only = allowedSymbols(strategy);
    return (_instruments ?? const <Instrument>[])
        .where((i) => i.tradeAllowed && (only == null || only.contains(i.canonical.isEmpty ? i.name : i.canonical) || only.contains(i.name)))
        .toList();
  }

  List<String> get _usableSuggested {
    final isDeriv = _account?.isDeriv ?? false;
    return _suggestedOffers.entries.where((e) => e.value != null && familiesFor(strategy, availableFamilies(e.value, isDeriv)).isNotEmpty).map((e) => e.key).toList();
  }

  Future<void> _loadAccount() async {
    final mine = ++_seq;
    setState(() {
      _instruments = null;
      _instrumentsError = null;
      _suggestedOffers = {};
      _offersReady = false;
      _symbol = '';
      _offer = null;
      _spec = null;
      _customStake = false;
    });
    final api = ref.read(apiClientProvider);
    try {
      final res = asJson(await api.get('/markets/instruments', query: {'account_id': _accountId}));
      if (mine != _seq || !mounted) return;
      setState(() => _instruments = res.objList('instruments').map(Instrument.fromJson).toList());
    } on ApiException catch (e) {
      if (mine != _seq || !mounted) return;
      setState(() {
        _instrumentsError = e;
        _instruments = const [];
      });
    }
    final candidates = strategy.details.suggestedSymbols.where((s) => _tradable.any((i) => i.name == s || i.canonical == s)).toList();
    final offers = await Future.wait(candidates.map((s) async {
      try {
        return ContractOffer.fromJson(asJson(await api.get('/markets/contracts', query: {'account_id': _accountId, 'symbol': s})));
      } catch (_) {
        return null;
      }
    }));
    if (mine != _seq || !mounted) return;
    setState(() {
      _suggestedOffers = {for (var i = 0; i < candidates.length; i++) candidates[i]: offers[i]};
      _offersReady = true;
    });
    final first = _usableSuggested.firstOrNull;
    if (first != null) _choose(first);
  }

  Future<void> _choose(String symbol) async {
    final mine = ++_seq;
    setState(() {
      _symbol = symbol;
      _offer = null;
      _offerError = null;
      _offerLoading = true;
      _spec = null;
    });
    try {
      final offer = ContractOffer.fromJson(asJson(await ref.read(apiClientProvider).get('/markets/contracts', query: {'account_id': _accountId, 'symbol': symbol})));
      if (mine != _seq || !mounted) return;
      setState(() {
        _offer = offer;
        _offerLoading = false;
      });
    } on ApiException catch (e) {
      if (mine != _seq || !mounted) return;
      setState(() {
        _offerError = e;
        _offerLoading = false;
      });
    }
  }

  List<String> get _families => familiesFor(strategy, availableFamilies(_offer, _account?.isDeriv ?? false));

  ContractSpec get _startSpec {
    final isDeriv = _account?.isDeriv ?? false;
    final suggestion = (!isDeriv ? strategy.details.suggestedContractPaper : null) ?? strategy.details.suggestedContract;
    final initial = initialContract(suggestion, _offer, isDeriv);
    final families = _families;
    return families.contains(initial.contractFamily) || families.isEmpty ? initial : initialContract(ContractSpec(contractFamily: families.first), _offer, isDeriv);
  }

  Future<void> _submit(ContractSpec spec) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final body = {
        'account_id': _accountId,
        'symbol': _symbol,
        'contract': spec.copyWith(stake: () => _customStake && (spec.stake?.isNotEmpty ?? false) ? spec.stake : null).toJson(),
      };
      final res = ActivationResult.fromJson(asJson(await ref.read(apiClientProvider).post('/strategies/${strategy.id}/activate', body: body)));
      ref.read(strategiesProvider.notifier).load();
      if (mounted) setState(() => _result = res);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_result != null) return _Done(strategy: strategy, result: _result!, scroll: widget.scroll);
    final c = context.c;
    final accounts = ref.watch(accountsProvider.select((r) => r.data)) ?? const <Account>[];
    final account = accounts.where((a) => a.id == _accountId).firstOrNull;
    final profiles = ref.watch(riskProfilesProvider.select((r) => r.data));
    final profile = profiles?.where((p) => p.id == account?.riskProfile?.id).firstOrNull;
    final isDeriv = account?.isDeriv ?? false;
    final spec = _spec ?? _startSpec;
    final maxStake = toNumber(profile?.value('max_stake_amount'));
    final local = _offer != null || spec.contractFamily == 'SPOT' ? contractProblems(spec, _offer, isDeriv: isDeriv, maxStake: maxStake) : <String, String>{};
    if (!_families.contains(spec.contractFamily) && !local.containsKey('contract_family') && _symbol.isNotEmpty) local['contract_family'] = "${strategy.name} can't trade this contract type here.";
    final server = <String, String>{
      for (final e in (_error?.fieldErrors ?? const <String, List<String>>{}).entries)
        if (e.key.startsWith('contract') && e.value.isNotEmpty) e.key.replaceFirst('contract.', ''): e.value.first,
    };
    final errors = {...server, ...local};
    final blocked = account == null || account.riskProfile == null || _symbol.isEmpty || local.isNotEmpty;
    final suggested = strategy.details.suggestedSymbols;
    final usable = _usableSuggested;
    final tradable = _tradable;
    String describe(String s) {
      final i = tradable.where((i) => i.name == s || i.canonical == s).firstOrNull;
      return i == null || i.description.isEmpty ? s : i.description;
    }

    return Column(children: [
      Expanded(
        child: ListView(controller: widget.scroll, padding: const EdgeInsets.fromLTRB(20, 0, 20, 20), children: [
          Text('Activate ${strategy.name}', style: context.text.headlineSmall),
          const SizedBox(height: 4),
          Text('Choose where it trades and how each trade works. You can deactivate it at any time.', style: context.text.bodySmall),
          const SizedBox(height: 18),
          PickerField(
            label: 'Account',
            value: account == null ? 'Choose an account' : '${account.label} · ${account.environment.wire}${account.isLive ? ' (real money)' : ''}',
            onTap: () async {
              final id = await pickOption<String>(context, title: 'Account', selected: _accountId, options: [
                for (final a in accounts) (a.id, a.label, '${a.environment.wire}${a.isLive ? ' — real money' : ''} · ${formatCurrency(a.balance, a.currency)}'),
              ]);
              if (id != null && id != _accountId) {
                setState(() => _accountId = id);
                _loadAccount();
              }
            },
          ),
          if (account != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Row(children: [
                EnvBadge(account.environment),
                const SizedBox(width: 8),
                Expanded(child: Text('${account.broker} · balance ${formatCurrency(account.balance, account.currency)}', style: tnum(context.text.bodySmall))),
              ]),
            ),
          if (accounts.isEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Notice(
                tone: NoticeTone.warning,
                title: 'No account yet',
                message: 'Add a Paper or Deriv demo account first — on the website.',
                action: OutlinedButton(onPressed: () => WebLinks.open(WebLinks.addBroker), child: const Text('Add an account')),
              ),
            ),
          if (account?.isLive ?? false)
            const Padding(
              padding: EdgeInsets.only(top: 10),
              child: Notice(tone: NoticeTone.live, title: 'This is a real-money account', message: 'It only trades after you authorise real-money trading on the website, and you can lose money.'),
            ),
          if (account != null && account.riskProfile == null)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Notice(
                tone: NoticeTone.danger,
                title: 'This account has no risk profile',
                message: 'Nothing can trade without limits.',
                action: OutlinedButton(
                  onPressed: () {
                    final router = GoRouter.of(context);
                    Navigator.pop(context);
                    router.push('/settings/accounts');
                  },
                  child: const Text('Choose a risk profile'),
                ),
              ),
            ),
          const SizedBox(height: 22),
          Text('Market', style: context.text.titleSmall),
          const SizedBox(height: 8),
          if (_instruments == null || (!_offersReady && _instrumentsError == null))
            const Skeleton(height: 52)
          else ...[
            if (_instrumentsError != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: ErrorView(error: _instrumentsError, onRetry: _loadAccount)),
            if (usable.isNotEmpty)
              Wrap(spacing: 8, runSpacing: 8, children: [
                for (final s in usable)
                  ChoiceChip(
                    label: Text(describe(s)),
                    selected: _symbol == s,
                    showCheckmark: false,
                    onSelected: (_) => _choose(s),
                    selectedColor: c.soft(c.primary, 0.18),
                    side: BorderSide(color: _symbol == s ? c.primary : c.border),
                    shape: const StadiumBorder(),
                    labelStyle: TextStyle(fontFamily: fontFamily, fontWeight: FontWeight.w700, color: c.fg),
                  ),
              ]),
            const SizedBox(height: 8),
            PickerField(
              label: 'Market',
              value: _symbol.isEmpty ? (tradable.isEmpty ? 'No markets available on this account' : 'Or choose another market…') : '${describe(_symbol)} ($_symbol)',
              enabled: tradable.isNotEmpty,
              onTap: () async {
                final s = await pickOption<String>(context, title: 'Market', selected: _symbol, options: [
                  for (final i in tradable) (i.name, i.description.isEmpty ? i.canonical : i.description, i.name),
                ]);
                if (s != null) _choose(s);
              },
            ),
            const SizedBox(height: 6),
            Text(
              usable.isNotEmpty
                  ? 'Suggested markets are the ones this strategy was designed for and that this account offers.'
                  : suggested.isNotEmpty
                      ? 'This account offers none of the suggested markets (${suggested.join(', ')}); pick another.'
                      : 'Pick the market the strategy should watch.',
              style: context.text.bodySmall?.copyWith(fontSize: 12.5),
            ),
          ],
          if (_symbol.isNotEmpty) ...[
            const SizedBox(height: 22),
            Text('How each trade works', style: context.text.titleSmall),
            const SizedBox(height: 8),
            if (_offerLoading)
              const Skeleton(height: 140)
            else if (_offerError != null)
              Notice(tone: NoticeTone.warning, title: "Couldn't ask the broker what it offers", message: _offerError!.message)
            else
              ContractFields(
                key: ValueKey('$_accountId:$_symbol:${spec.contractFamily}'),
                spec: spec,
                families: _families,
                offer: _offer,
                errors: errors,
                onChanged: (s) => setState(() => _spec = s),
              ),
            for (final n in _offer?.notes ?? const <String>[]) Padding(padding: const EdgeInsets.only(top: 6), child: Text(n, style: context.text.bodySmall?.copyWith(fontSize: 12.5))),
          ],
          if (_symbol.isNotEmpty && spec.contractFamily != 'SPOT' && account?.riskProfile != null) ...[
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(color: c.raised, borderRadius: BorderRadius.circular(14)),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Text.rich(TextSpan(children: [
                  const TextSpan(text: 'Each trade stakes '),
                  TextSpan(text: profile == null ? '…' : formatCurrency(profile.value('stake_amount'), account!.currency), style: tnum(const TextStyle(fontWeight: FontWeight.w800))),
                  TextSpan(text: ' — from your “${account!.riskProfile!.name}” risk profile. That is the most one trade can lose.'),
                ]), style: const TextStyle(fontSize: 14)),
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  value: _customStake,
                  onChanged: (v) => setState(() {
                    _customStake = v ?? false;
                    if (!_customStake) _spec = spec.copyWith(stake: () => null);
                  }),
                  title: const Text('Use a different stake for this strategy', style: TextStyle(fontSize: 14)),
                ),
                if (_customStake)
                  TextFormField(
                    initialValue: spec.stake ?? '',
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    style: tnum(const TextStyle(fontWeight: FontWeight.w600)),
                    decoration: InputDecoration(
                      labelText: 'Stake (${account.currency})',
                      errorText: errors['stake'],
                      helperText: maxStake != null ? 'Your profile allows at most ${formatCurrency(maxStake, account.currency)}.' : null,
                    ),
                    onChanged: (v) => setState(() => _spec = spec.copyWith(stake: () => v.trim().isEmpty ? null : v.trim().replaceAll(',', '.'))),
                  ),
              ]),
            ),
          ],
          if (_symbol.isNotEmpty) ...[
            const SizedBox(height: 14),
            Text.rich(TextSpan(children: [
              const TextSpan(text: 'Summary: '),
              TextSpan(
                text: '$_symbol · ${contractSummary(spec.copyWith(stake: () => _customStake ? spec.stake : null), currency: account?.currency, profileStake: profile?.value('stake_amount'))}',
                style: TextStyle(color: c.fg, fontWeight: FontWeight.w600),
              ),
            ]), style: context.text.bodySmall?.copyWith(fontSize: 13.5)),
          ],
          if (_error != null && server.isEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 14),
              child: _error!.isWebOnly
                  ? ErrorView(error: _error)
                  : Notice(tone: NoticeTone.danger, title: 'Not activated', message: _error!.message),
            ),
        ]),
      ),
      SafeArea(
        top: false,
        child: Container(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          decoration: BoxDecoration(border: Border(top: BorderSide(color: c.border))),
          child: Row(children: [
            Expanded(child: OutlinedButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel'))),
            const SizedBox(width: 10),
            Expanded(
              flex: 2,
              child: FilledButton(
                key: const Key('activate-submit'),
                onPressed: blocked || _busy ? null : () => _submit(spec),
                child: Text(_busy ? 'Activating…' : 'Activate'),
              ),
            ),
          ]),
        ),
      ),
    ]);
  }
}

class _Done extends StatelessWidget {
  const _Done({required this.strategy, required this.result, required this.scroll});
  final Strategy strategy;
  final ActivationResult result;
  final ScrollController scroll;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final a = result.assignment;
    return ListView(controller: scroll, padding: const EdgeInsets.fromLTRB(20, 0, 20, 24), children: [
      Row(children: [
        Icon(result.willTrade ? Icons.check_circle_rounded : Icons.error_outline_rounded, color: result.willTrade ? c.positive : c.warning, size: 28),
        const SizedBox(width: 10),
        Expanded(child: Text('${strategy.name} is active', style: context.text.headlineSmall)),
      ]),
      const SizedBox(height: 6),
      Text('${a.symbol} on ${a.account?.label ?? 'your account'} · ${contractSummary(a.contract)}', style: context.text.bodySmall?.copyWith(fontSize: 13.5)),
      const SizedBox(height: 16),
      if (result.willTrade)
        const Notice(tone: NoticeTone.success, title: 'It will trade', message: 'The bot checks it every time a candle closes. Every trade still passes your risk limits.')
      else ...[
        const Notice(tone: NoticeTone.warning, title: "It won't trade yet", message: 'It is switched on, but nothing will trade until these are sorted:'),
        const SizedBox(height: 10),
        for (final b in result.blockers)
          Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(borderRadius: BorderRadius.circular(12), border: Border.all(color: c.border)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text(b.message),
              if (b.code == 'trading_stopped')
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: FilledButton(
                    style: FilledButton.styleFrom(backgroundColor: c.positive, foregroundColor: c.onPositive),
                    onPressed: () {
                      final root = Navigator.of(context, rootNavigator: true).context;
                      Navigator.pop(context);
                      requestStart(root);
                    },
                    child: const Text('Start trading'),
                  ),
                ),
              if (b.code == 'account_trading_disabled' || b.code == 'mode_mismatch')
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: OutlinedButton(
                    onPressed: () {
                      final router = GoRouter.of(context);
                      Navigator.pop(context);
                      router.push('/settings/accounts');
                    },
                    child: Text(b.code == 'mode_mismatch' ? 'Accounts' : 'Turn trading on'),
                  ),
                ),
              if (b.code == 'live_locked')
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: OutlinedButton.icon(onPressed: () => WebLinks.open(WebLinks.realMoney), icon: const Icon(Icons.open_in_new_rounded, size: 16), label: const Text('Real-money settings')),
                ),
            ]),
          ),
      ],
      if (result.contractVerified == false)
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Notice(title: "The broker couldn't confirm the contract right now", message: '${result.contractDetail ?? ''} It is checked again before every trade.'),
        ),
      const SizedBox(height: 18),
      Row(children: [
        Expanded(
          child: OutlinedButton(
            onPressed: () {
              final router = GoRouter.of(context);
              Navigator.pop(context);
              router.go('/home');
            },
            child: const Text('Go to Home'),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(child: FilledButton(onPressed: () => Navigator.pop(context), child: const Text('Done'))),
      ]),
    ]);
  }
}
