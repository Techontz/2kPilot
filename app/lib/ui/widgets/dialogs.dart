import 'package:flutter/material.dart';

import '../../core/api/api_client.dart';
import '../../core/web_links.dart';
import '../theme.dart';

void showSnack(BuildContext context, String message, {String? detail, bool error = false, SnackBarAction? action, Duration? duration}) {
  final messenger = ScaffoldMessenger.maybeOf(context);
  if (messenger == null) return;
  messenger.hideCurrentSnackBar();
  messenger.showSnackBar(SnackBar(
    duration: duration ?? Duration(seconds: error ? 8 : 4),
    action: action,
    content: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Icon(error ? Icons.error_outline_rounded : Icons.check_circle_rounded, size: 20, color: error ? const Color(0xFFE5484D) : const Color(0xFF1E9E5A)),
      const SizedBox(width: 10),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Text(message, style: const TextStyle(fontWeight: FontWeight.w800)),
          if (detail != null) Padding(padding: const EdgeInsets.only(top: 2), child: Text(detail, style: const TextStyle(fontWeight: FontWeight.w500))),
        ]),
      ),
    ]),
  ));
}

/// "Do this on the 2kPilot website" with a button that opens it.
Future<void> showWebOnly(BuildContext context, {String? message, Uri? link, String title = 'Do this on the 2kPilot website'}) {
  return showDialog<void>(
    context: context,
    builder: (ctx) => AlertDialog(
      icon: Icon(Icons.language_rounded, color: ctx.c.brandInk, size: 30),
      title: Text(title, textAlign: TextAlign.center),
      content: Text(
        message ?? 'For your safety, this is only available on the 2kPilot website. Sign in there with the same email and password.',
        textAlign: TextAlign.center,
      ),
      actionsAlignment: MainAxisAlignment.center,
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Not now')),
        FilledButton.icon(
          onPressed: () {
            Navigator.pop(ctx);
            WebLinks.open(link ?? WebLinks.home);
          },
          icon: const Icon(Icons.open_in_new_rounded, size: 18),
          label: const Text('Open the website'),
        ),
      ],
    ),
  );
}

/// One place to explain a failed action: web-only refusals get the website
/// dialog; anything else a snackbar.
void showApiError(BuildContext context, Object error, {String title = 'That did not work', Uri? webLink}) {
  if (error is ApiException && (error.isWebOnly || error.needsMfaEnrollment)) {
    showWebOnly(context, message: error.message, link: webLink ?? (error.needsMfaEnrollment ? WebLinks.security : null));
    return;
  }
  showSnack(context, title, detail: error is ApiException ? error.message : 'Something went wrong.', error: true);
}

/// A destructive or important confirmation. [onConfirm] runs with a busy
/// state; return an error message to keep the dialog open and show it.
Future<bool> confirmAction(
  BuildContext context, {
  required String title,
  required List<String> body,
  required String confirmLabel,
  bool destructive = false,
  Color? confirmColor,
  Future<String?> Function()? onConfirm,
  String? typeToConfirm,
}) async {
  final result = await showDialog<bool>(
    context: context,
    builder: (ctx) => _ConfirmDialog(
      title: title,
      body: body,
      confirmLabel: confirmLabel,
      destructive: destructive,
      confirmColor: confirmColor,
      onConfirm: onConfirm,
      typeToConfirm: typeToConfirm,
    ),
  );
  return result ?? false;
}

class _ConfirmDialog extends StatefulWidget {
  const _ConfirmDialog({required this.title, required this.body, required this.confirmLabel, required this.destructive, this.confirmColor, this.onConfirm, this.typeToConfirm});
  final String title;
  final List<String> body;
  final String confirmLabel;
  final bool destructive;
  final Color? confirmColor;
  final Future<String?> Function()? onConfirm;
  final String? typeToConfirm;

  @override
  State<_ConfirmDialog> createState() => _ConfirmDialogState();
}

class _ConfirmDialogState extends State<_ConfirmDialog> {
  bool _busy = false;
  String? _error;
  final _typed = TextEditingController();

  @override
  void dispose() {
    _typed.dispose();
    super.dispose();
  }

  Future<void> _confirm() async {
    if (widget.onConfirm == null) {
      Navigator.pop(context, true);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final error = await widget.onConfirm!();
    if (!mounted) return;
    if (error == null) {
      Navigator.pop(context, true);
    } else {
      setState(() {
        _busy = false;
        _error = error;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final color = widget.confirmColor ?? (widget.destructive ? c.negative : c.primary);
    final typedOk = widget.typeToConfirm == null || _typed.text.trim() == widget.typeToConfirm;
    return AlertDialog(
      title: Text(widget.title),
      content: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final p in widget.body) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(p, style: context.text.bodyMedium?.copyWith(color: c.muted))),
          if (widget.typeToConfirm != null) ...[
            const SizedBox(height: 4),
            TextField(
              controller: _typed,
              autocorrect: false,
              enableSuggestions: false,
              textCapitalization: TextCapitalization.characters,
              decoration: InputDecoration(labelText: 'Type ${widget.typeToConfirm} to confirm'),
              onChanged: (_) => setState(() {}),
            ),
          ],
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Semantics(liveRegion: true, child: Text(_error!, style: TextStyle(color: c.negative, fontWeight: FontWeight.w600))),
            ),
        ]),
      ),
      actions: [
        TextButton(onPressed: _busy ? null : () => Navigator.pop(context, false), child: Text('Cancel', style: TextStyle(color: c.fg))),
        FilledButton(
          style: FilledButton.styleFrom(backgroundColor: color, foregroundColor: widget.destructive ? c.onNegative : Colors.white),
          onPressed: _busy || !typedOk ? null : _confirm,
          child: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : Text(widget.confirmLabel),
        ),
      ],
    );
  }
}

/// A bottom-sheet picker (large tap targets instead of dropdowns).
Future<T?> pickOption<T>(BuildContext context, {required String title, required List<(T, String, String?)> options, T? selected, Widget? leading}) {
  return showModalBottomSheet<T>(useRootNavigator: true, 
    context: context,
    isScrollControlled: true,
    builder: (ctx) {
      final c = ctx.c;
      return SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(ctx).height * 0.75),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Padding(padding: const EdgeInsets.fromLTRB(20, 0, 20, 8), child: Text(title, style: ctx.text.titleLarge)),
            ?leading,
            Flexible(
              child: ListView(shrinkWrap: true, padding: const EdgeInsets.only(bottom: 12), children: [
                for (final o in options)
                  ListTile(
                    minTileHeight: 56,
                    title: Text(o.$2),
                    subtitle: o.$3 == null ? null : Text(o.$3!),
                    trailing: o.$1 == selected ? Icon(Icons.check_rounded, color: c.brandInk) : null,
                    selected: o.$1 == selected,
                    selectedColor: c.fg,
                    onTap: () => Navigator.pop(ctx, o.$1),
                  ),
              ]),
            ),
          ]),
        ),
      );
    },
  );
}

/// A field-like button that opens [pickOption].
class PickerField extends StatelessWidget {
  const PickerField({super.key, required this.label, required this.value, required this.onTap, this.enabled = true, this.error});
  final String label;
  final String value;
  final VoidCallback onTap;
  final bool enabled;
  final String? error;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Semantics(
      button: true,
      label: '$label: $value',
      excludeSemantics: true,
      child: InkWell(
        onTap: enabled ? onTap : null,
        borderRadius: BorderRadius.circular(12),
        child: InputDecorator(
          isEmpty: false,
          decoration: InputDecoration(labelText: label, errorText: error, enabled: enabled, suffixIcon: Icon(Icons.expand_more_rounded, color: c.muted)),
          child: Text(value, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: enabled ? c.fg : c.subtle, fontWeight: FontWeight.w600, fontSize: 15)),
        ),
      ),
    );
  }
}
