import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_client.dart';
import '../../core/contracts.dart';
import '../../core/format.dart';
import '../../core/insights.dart';
import '../../core/models/models.dart';
import '../../state/providers.dart';
import '../../ui/theme.dart';
import '../../ui/widgets/dialogs.dart';
import '../../ui/widgets/states.dart';
import 'contract_fields.dart';

const _timeframes = [
  ('M1', '1-minute candles', 1),
  ('M5', '5-minute candles', 5),
  ('M15', '15-minute candles', 15),
  ('M30', '30-minute candles', 30),
  ('H1', '1-hour candles', 60),
  ('H4', '4-hour candles', 240),
  ('D1', 'Daily candles', 1440),
];

const _periods = [(30, 'Last 30 days'), (90, 'Last 90 days'), (180, 'Last 6 months'), (365, 'Last year')];

/// Practice data on short candles makes many bars, so its period is capped (the server checks too).
const Map<String, int> practiceMaxDays = {'M1': 60, 'M5': 365};

const _synthetic = 'synthetic';

/// "Test on history" — one guided flow: market, period and price data
/// (downloaded from the user's own connection, or labelled practice data),
/// then how each trade works and the stake. Runs as a queued job on the
/// server; the report screen shows progress and results.
Future<void> showBacktestSheet(BuildContext context, Strategy strategy) {
  final router = GoRouter.of(context);
  return showModalBottomSheet<String>(useRootNavigator: true, 
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) => DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.94,
      minChildSize: 0.5,
      maxChildSize: 0.94,
      builder: (ctx, scroll) => BacktestForm(strategy: strategy, scroll: scroll),
    ),
  ).then((id) {
    if (id != null) router.push('/strategies/backtests/$id');
  });
}

class BacktestForm extends ConsumerStatefulWidget {
  const BacktestForm({super.key, required this.strategy, required this.scroll});
  final Strategy strategy;
  final ScrollController scroll;

  @override
  ConsumerState<BacktestForm> createState() => _BacktestFormState();
}

class _BacktestFormState extends ConsumerState<BacktestForm> {
  late String _source;
  late String _timeframe = strategyTimeframe(widget.strategy);
  late final _symbol = TextEditingController(text: widget.strategy.details.suggestedSymbols.firstOrNull ?? 'R_75');
  int _days = 30;
  late ContractSpec _spec;
  String _stake = '';
  String _payout = '0.95';
  String _capital = '';
  String _phase = 'idle';
  String? _error;
  List<String> _problems = const [];

  Strategy get strategy => widget.strategy;

  @override
  void initState() {
    super.initState();
    final selected = ref.read(currentAccountProvider);
    _source = selected != null && canDownloadHistory(selected) ? selected.id : _synthetic;
    final suggestion = strategy.details.suggestedContract;
    final family = suggestion?.contractFamily ?? 'RISE_FALL';
    _spec = specForFamily(family, family == 'RISE_FALL' && suggestion?.duration == null ? _defaultDuration(_timeframe) : suggestion);
  }

  @override
  void dispose() {
    _symbol.dispose();
    super.dispose();
  }

  static ContractSpec _defaultDuration(String tf) {
    final minutes = (_timeframes.where((t) => t.$1 == tf).firstOrNull?.$3 ?? 5) * 5;
    return minutes >= 60 && minutes % 60 == 0
        ? ContractSpec(contractFamily: 'RISE_FALL', duration: minutes ~/ 60, durationUnit: 'h')
        : ContractSpec(contractFamily: 'RISE_FALL', duration: minutes, durationUnit: 'm');
  }

  Future<void> _run(Account? account, RiskProfile? profile, String stakeValue, String capitalValue) async {
    final version = latestVersion(strategy);
    if (version == null) return;
    setState(() {
      _error = null;
      _problems = const [];
      _phase = 'data';
    });
    final api = ref.read(apiClientProvider);
    try {
      final end = DateTime.now().toUtc();
      final endDay = DateTime.utc(end.year, end.month, end.day);
      final start = endDay.subtract(Duration(days: _days));
      final sym = _symbol.text.trim().toUpperCase();
      final kind = account != null ? 'broker' : 'synthetic';
      final datasets = asJsonList(await api.get('/datasets')).map(Dataset.fromJson).toList();
      var dataset = findDataset(datasets, sym, _timeframe, kind, start, endDay);
      dataset ??= Dataset.fromJson(asJson(account != null
          ? await api.post('/datasets/download', body: {'account_id': account.id, 'symbol': sym, 'timeframe': _timeframe, 'start': start.toIso8601String(), 'end': endDay.toIso8601String()})
          : await api.post('/datasets/synthetic', body: {'symbol': sym, 'timeframe': _timeframe, 'days': math.max(30, _days)})));
      if (!mounted) return;
      setState(() => _phase = 'queue');
      final first = dataset.firstBar == null ? null : DateTime.tryParse(dataset.firstBar!);
      final last = dataset.lastBar == null ? null : DateTime.tryParse(dataset.lastBar!);
      final from = first != null && first.isAfter(start) ? first : start;
      final to = last != null && last.isBefore(endDay) ? last : endDay;
      final risk = <String, Object?>{
        if (profile != null)
          for (final e in profile.raw.entries)
            if (!['id', 'name', 'user_id', 'created_at', 'updated_at', 'accounts_count'].contains(e.key)) e.key: e.value,
        'stake_amount': stakeValue,
      };
      final created = asJson(await api.post('/backtests', body: {
        'mode': 'single',
        'strategy_version_id': version.id,
        'dataset_id': dataset.id,
        'start': from.toUtc().toIso8601String(),
        'end': to.toUtc().toIso8601String(),
        'initial_capital': capitalValue,
        'name': '${strategy.name} · $sym $_timeframe',
        'risk': risk,
        'contract': _spec.copyWith(stake: () => _spec.contractFamily == 'SPOT' ? null : stakeValue).toJson(),
        if (_spec.contractFamily == 'RISE_FALL') 'payout_ratio': _payout,
      }));
      ref.read(backtestsProvider.notifier).load();
      if (!mounted) return;
      showSnack(context, 'Test started', detail: 'It runs on the server — you can leave this screen.');
      Navigator.pop(context, created.str('id'));
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _phase = 'idle';
        _error = e.message;
        _problems = [...e.fieldErrors.values.expand((v) => v), ...e.problems];
      });
    } catch (_) {
      if (mounted) {
        setState(() {
          _phase = 'idle';
          _error = 'Something went wrong.';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final accounts = ref.watch(accountsProvider.select((r) => r.data)) ?? const <Account>[];
    final selected = ref.watch(currentAccountProvider);
    final account = accounts.where((a) => a.id == _source).firstOrNull;
    final isDeriv = account?.isDeriv ?? false;
    final profiles = ref.watch(riskProfilesProvider.select((r) => r.data)) ?? const <RiskProfile>[];
    final profile = profiles.where((p) => p.id == (account ?? selected)?.riskProfile?.id).firstOrNull ?? profiles.firstOrNull;
    final stakeValue = _stake.isNotEmpty ? _stake : (profile?.value('stake_amount') ?? '1.00');
    final capitalValue = _capital.isNotEmpty ? _capital : '${math.max(100, (toNumber(account?.balance ?? selected?.balance) ?? 1000).round())}';
    final currency = account?.currency ?? 'USD';
    final strategyTf = strategyTimeframe(strategy);
    final families = familiesFor(strategy, isDeriv ? const ['RISE_FALL', 'MULTIPLIER'] : const ['RISE_FALL', 'MULTIPLIER', 'SPOT']);
    final errors = contractProblems(_spec.copyWith(stake: () => _spec.contractFamily == 'SPOT' ? null : stakeValue), null, isDeriv: isDeriv);
    if (!families.contains(_spec.contractFamily) && !errors.containsKey('contract_family')) errors['contract_family'] = "${strategy.name} can't be tested with this contract type.";
    final payoutNum = double.tryParse(_payout) ?? 0;
    final payoutError = _spec.contractFamily == 'RISE_FALL' && !(payoutNum >= 0.01 && payoutNum <= 2) ? 'Enter a number between 0.01 and 2 (0.95 means a win pays 95% of the stake as profit).' : null;
    final tfMinutes = _timeframes.where((t) => t.$1 == _timeframe).firstOrNull?.$3 ?? 5;
    final tooMuchData = _days * 1440 / tfMinutes > 120000;
    final practiceMax = practiceMaxDays[_timeframe] ?? 3650;
    final practiceTooLong = account == null && _days > practiceMax;
    final invalid = practiceTooLong || _symbol.text.trim().isEmpty || errors.isNotEmpty || payoutError != null || !((toNumber(capitalValue) ?? 0) > 0) || tooMuchData;
    final working = _phase != 'idle';

    return Column(children: [
      Expanded(
        child: ListView(controller: widget.scroll, padding: const EdgeInsets.fromLTRB(20, 0, 20, 20), children: [
          Text('Test ${strategy.name} on history', style: context.text.headlineSmall),
          const SizedBox(height: 4),
          Text("See how these rules would have traded on past prices — using the same risk rules as live trading. Past results don't guarantee future results.", style: context.text.bodySmall),
          const SizedBox(height: 20),
          Text('1. Market and period', style: context.text.titleSmall),
          const SizedBox(height: 10),
          TextField(
            controller: _symbol,
            textCapitalization: TextCapitalization.characters,
            autocorrect: false,
            decoration: const InputDecoration(labelText: 'Market (symbol)'),
            onChanged: (_) => setState(() {}),
          ),
          if (strategy.details.suggestedSymbols.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final s in strategy.details.suggestedSymbols)
                ActionChip(label: Text(s), onPressed: () => setState(() => _symbol.text = s), shape: const StadiumBorder(), side: BorderSide(color: c.border)),
            ]),
          ],
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: PickerField(
                label: 'Candles',
                value: _timeframes.firstWhere((t) => t.$1 == _timeframe, orElse: () => _timeframes[1]).$2,
                onTap: () async {
                  final tf = await pickOption<String>(context, title: 'Candles', selected: _timeframe, options: [
                    for (final t in _timeframes) (t.$1, '${t.$2}${t.$1 == strategyTf ? ' (strategy)' : ''}', null),
                  ]);
                  if (tf != null) setState(() => _timeframe = tf);
                },
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: PickerField(
                label: 'Period',
                value: _periods.firstWhere((p) => p.$1 == _days).$2,
                onTap: () async {
                  final d = await pickOption<int>(context, title: 'Period', selected: _days, options: [for (final p in _periods) (p.$1, p.$2, null)]);
                  if (d != null) setState(() => _days = d);
                },
              ),
            ),
          ]),
          if (tooMuchData) Padding(padding: const EdgeInsets.only(top: 6), child: Text('That is a lot of candles — choose a shorter period or longer candles.', style: TextStyle(color: c.negative, fontSize: 13))),
          if (_timeframe != strategyTf) Padding(padding: const EdgeInsets.only(top: 6), child: Text('The strategy decides on $strategyTf candles; shorter candles only make exits more precise.', style: context.text.bodySmall?.copyWith(fontSize: 12.5))),
          const SizedBox(height: 22),
          Text('2. Price data', style: context.text.titleSmall),
          const SizedBox(height: 10),
          PickerField(
            label: 'Use prices from',
            value: account == null ? 'Practice data — generated by 2kPilot' : '${account.label} — download past prices',
            onTap: () async {
              final s = await pickOption<String>(context, title: 'Use prices from', selected: _source, options: [
                for (final a in accounts.where(canDownloadHistory)) (a.id, a.label, 'Download past prices (${a.broker})'),
                (_synthetic, 'Practice data', 'Generated by 2kPilot'),
              ]);
              if (s != null) setState(() => _source = s);
            },
          ),
          const SizedBox(height: 8),
          if (account != null)
            Text('Past candles are downloaded from your ${account.broker} connection (public market data). Data you already have is reused.', style: context.text.bodySmall?.copyWith(fontSize: 12.5))
          else if (practiceTooLong)
            Notice(tone: NoticeTone.danger, title: 'Practice data on $_timeframe candles covers at most $practiceMax days', message: 'Choose a shorter period, or longer candles.')
          else
            Notice(
              tone: NoticeTone.warning,
              title: 'Practice data says nothing about real markets',
              message: '2kPilot generates $_timeframe candles to test that everything works — the same simulated prices Paper accounts trade. Use real prices before drawing any conclusion.',
            ),
          const SizedBox(height: 22),
          Text('3. How each trade works', style: context.text.titleSmall),
          const SizedBox(height: 10),
          ContractFields(key: ValueKey('bt-${_spec.contractFamily}'), spec: _spec, families: families, errors: errors, onChanged: (s) => setState(() => _spec = s)),
          if (strategy.details.suggestedContractNote != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text(strategy.details.suggestedContractNote!, style: context.text.bodySmall?.copyWith(fontSize: 12.5))),
          const SizedBox(height: 14),
          if (_spec.contractFamily != 'SPOT')
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: TextFormField(
                key: ValueKey('stake-$_source'),
                initialValue: stakeValue,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                style: tnum(const TextStyle(fontWeight: FontWeight.w600)),
                decoration: InputDecoration(labelText: 'Stake per trade ($currency)', errorText: errors['stake']),
                onChanged: (v) => setState(() => _stake = v.trim().replaceAll(',', '.')),
              ),
            ),
          if (_spec.contractFamily == 'RISE_FALL')
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: TextFormField(
                initialValue: _payout,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                style: tnum(const TextStyle(fontWeight: FontWeight.w600)),
                decoration: InputDecoration(
                  labelText: 'Payout (estimate)',
                  errorText: payoutError,
                  errorMaxLines: 3,
                  helperText: payoutError == null ? '0.95 = a win earns 95% of the stake. Real payouts vary with every quote.' : null,
                  helperMaxLines: 2,
                ),
                onChanged: (v) => setState(() => _payout = v.trim().replaceAll(',', '.')),
              ),
            ),
          TextFormField(
            key: ValueKey('capital-$_source'),
            initialValue: capitalValue,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            style: tnum(const TextStyle(fontWeight: FontWeight.w600)),
            decoration: InputDecoration(labelText: 'Starting balance ($currency)'),
            onChanged: (v) => setState(() => _capital = v.trim().replaceAll(',', '.')),
          ),
          if (profile != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text('Your “${profile.name}” risk limits apply, exactly as in live trading (losses in a row, daily limits, trades per day).', style: context.text.bodySmall?.copyWith(fontSize: 12.5)),
            ),
          if (working)
            Padding(
              padding: const EdgeInsets.only(top: 14),
              child: Notice(
                title: _phase == 'data' ? 'Getting the price data…' : 'Starting the test…',
                message: _phase == 'data' ? (account != null ? 'Downloading candles from your broker. This can take a minute.' : 'Generating practice data.') : 'Queuing the test on the server.',
              ),
            ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 14),
              child: Notice(
                tone: NoticeTone.danger,
                title: "The test didn't start",
                message: _error,
                child: _problems.isEmpty ? null : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [for (final p in _problems) Text('• $p', style: context.text.bodySmall)]),
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
            Expanded(child: OutlinedButton(onPressed: working ? null : () => Navigator.pop(context), child: const Text('Cancel'))),
            const SizedBox(width: 10),
            Expanded(
              flex: 2,
              child: FilledButton.icon(
                onPressed: invalid || working || latestVersion(strategy) == null ? null : () => _run(account, profile, stakeValue, capitalValue),
                icon: const Icon(Icons.science_outlined, size: 19),
                label: Text(working ? 'Working…' : 'Run the test'),
              ),
            ),
          ]),
        ),
      ),
    ]);
  }
}
