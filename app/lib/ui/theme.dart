import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// 2kPilot design tokens — the web's globals.css, dark-first.
/// Green/red are only for profit/loss (and LIVE = real money), never decoration.
@immutable
class AppColors extends ThemeExtension<AppColors> {
  const AppColors({
    required this.background,
    required this.card,
    required this.raised,
    required this.hover,
    required this.border,
    required this.lineStrong,
    required this.fg,
    required this.muted,
    required this.subtle,
    required this.primary,
    required this.onPrimary,
    required this.brandInk,
    required this.positive,
    required this.onPositive,
    required this.negative,
    required this.onNegative,
    required this.warning,
    required this.onWarning,
    required this.live,
    required this.onLive,
    required this.isDark,
  });

  final Color background;
  final Color card;
  final Color raised;
  final Color hover;
  final Color border;
  final Color lineStrong;
  final Color fg;
  final Color muted;
  final Color subtle;
  final Color primary;
  final Color onPrimary;

  /// Lavender on dark, deep purple on light: accents, links, DEMO.
  final Color brandInk;
  final Color positive;
  final Color onPositive;
  final Color negative;
  final Color onNegative;
  final Color warning;
  final Color onWarning;
  final Color live;
  final Color onLive;
  final bool isDark;

  Color get info => brandInk;
  Color get demo => brandInk;
  Color soft(Color c, [double alpha = 0.12]) => c.withValues(alpha: alpha);

  static const dark = AppColors(
    background: Color(0xFF121212),
    card: Color(0xFF181818),
    raised: Color(0xFF1F1F1F),
    hover: Color(0xFF282828),
    border: Color(0xFF2A2A2A),
    lineStrong: Color(0xFF3A3A3A),
    fg: Color(0xFFFFFFFF),
    muted: Color(0xFFB3B3B3),
    subtle: Color(0xFF919191),
    primary: Color(0xFF8B3FD9),
    onPrimary: Color(0xFFFFFFFF),
    brandInk: Color(0xFFC8A2F0),
    positive: Color(0xFF3DCB83),
    onPositive: Color(0xFF03130B),
    negative: Color(0xFFF2716A),
    onNegative: Color(0xFF1A0504),
    warning: Color(0xFFF2B54A),
    onWarning: Color(0xFF1A1205),
    live: Color(0xFFE5484D),
    onLive: Color(0xFFFFFFFF),
    isDark: true,
  );

  static const light = AppColors(
    background: Color(0xFFFAFAFA),
    card: Color(0xFFFFFFFF),
    raised: Color(0xFFF5F5F5),
    hover: Color(0xFFEFEFEF),
    border: Color(0xFFE5E5E5),
    lineStrong: Color(0xFFD4D4D4),
    fg: Color(0xFF0A0A0A),
    muted: Color(0xFF575757),
    subtle: Color(0xFF686868),
    primary: Color(0xFF8B3FD9),
    onPrimary: Color(0xFFFFFFFF),
    brandInk: Color(0xFF7B2FC9),
    positive: Color(0xFF087443),
    onPositive: Color(0xFFFFFFFF),
    negative: Color(0xFFC52A1F),
    onNegative: Color(0xFFFFFFFF),
    warning: Color(0xFF8F5300),
    onWarning: Color(0xFFFFFFFF),
    live: Color(0xFFC52A1F),
    onLive: Color(0xFFFFFFFF),
    isDark: false,
  );

  @override
  AppColors copyWith() => this;

  @override
  AppColors lerp(ThemeExtension<AppColors>? other, double t) => t < 0.5 ? this : (other as AppColors? ?? this);
}

extension AppThemeX on BuildContext {
  AppColors get c => Theme.of(this).extension<AppColors>()!;
  TextTheme get text => Theme.of(this).textTheme;
  bool get reduceMotion => MediaQuery.maybeDisableAnimationsOf(this) ?? false;
}

const String fontFamily = 'Figtree';

/// Money and counts line up in columns.
const List<FontFeature> tabular = [FontFeature.tabularFigures()];

TextStyle tnum(TextStyle? base) => (base ?? const TextStyle()).copyWith(fontFeatures: tabular);

ThemeData buildTheme(Brightness brightness) {
  final c = brightness == Brightness.dark ? AppColors.dark : AppColors.light;
  final scheme = ColorScheme(
    brightness: brightness,
    primary: c.primary,
    onPrimary: c.onPrimary,
    secondary: c.brandInk,
    onSecondary: c.isDark ? const Color(0xFF14081F) : Colors.white,
    error: c.negative,
    onError: c.onNegative,
    surface: c.card,
    onSurface: c.fg,
    surfaceContainerLowest: c.background,
    surfaceContainerLow: c.card,
    surfaceContainer: c.raised,
    surfaceContainerHigh: c.raised,
    surfaceContainerHighest: c.hover,
    onSurfaceVariant: c.muted,
    outline: c.lineStrong,
    outlineVariant: c.border,
  );

  TextStyle t(double size, FontWeight w, {double? height, double spacing = 0, Color? color}) =>
      TextStyle(fontFamily: fontFamily, fontSize: size, fontWeight: w, height: height, letterSpacing: spacing, color: color ?? c.fg);

  final textTheme = TextTheme(
    displayLarge: t(44, FontWeight.w900, height: 1.05, spacing: -1.6),
    displayMedium: t(36, FontWeight.w900, height: 1.05, spacing: -1.2),
    displaySmall: t(30, FontWeight.w800, height: 1.1, spacing: -0.9),
    headlineMedium: t(26, FontWeight.w800, height: 1.15, spacing: -0.6),
    headlineSmall: t(22, FontWeight.w800, height: 1.2, spacing: -0.4),
    titleLarge: t(19, FontWeight.w800, height: 1.25, spacing: -0.3),
    titleMedium: t(16, FontWeight.w700, height: 1.3, spacing: -0.1),
    titleSmall: t(14, FontWeight.w700, height: 1.3),
    bodyLarge: t(16, FontWeight.w500, height: 1.45),
    bodyMedium: t(14.5, FontWeight.w500, height: 1.45, color: c.fg),
    bodySmall: t(13, FontWeight.w500, height: 1.4, color: c.muted),
    labelLarge: t(15, FontWeight.w700, height: 1.2),
    labelMedium: t(13, FontWeight.w700, height: 1.2, color: c.muted),
    labelSmall: t(11.5, FontWeight.w700, height: 1.2, spacing: 0.3, color: c.subtle),
  );

  final pill = RoundedRectangleBorder(borderRadius: BorderRadius.circular(999));
  const minSize = Size(48, 48);

  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    fontFamily: fontFamily,
    textTheme: textTheme,
    scaffoldBackgroundColor: c.background,
    canvasColor: c.background,
    extensions: [c],
    splashFactory: InkSparkle.splashFactory,
    visualDensity: VisualDensity.standard,
    materialTapTargetSize: MaterialTapTargetSize.padded,
    dividerTheme: DividerThemeData(color: c.border, thickness: 1, space: 1),
    appBarTheme: AppBarTheme(
      backgroundColor: c.background,
      surfaceTintColor: Colors.transparent,
      foregroundColor: c.fg,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: textTheme.titleLarge,
      systemOverlayStyle: c.isDark ? SystemUiOverlayStyle.light : SystemUiOverlayStyle.dark,
    ),
    cardTheme: CardThemeData(
      color: c.card,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: BorderSide(color: c.isDark ? Colors.transparent : c.border)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: c.primary,
        foregroundColor: c.onPrimary,
        disabledBackgroundColor: c.hover,
        disabledForegroundColor: c.subtle,
        minimumSize: minSize,
        padding: const EdgeInsets.symmetric(horizontal: 22),
        shape: pill,
        textStyle: textTheme.labelLarge,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: c.fg,
        minimumSize: minSize,
        padding: const EdgeInsets.symmetric(horizontal: 20),
        side: BorderSide(color: c.lineStrong),
        shape: pill,
        textStyle: textTheme.labelLarge,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(foregroundColor: c.brandInk, minimumSize: minSize, shape: pill, textStyle: textTheme.labelLarge),
    ),
    iconButtonTheme: IconButtonThemeData(style: IconButton.styleFrom(minimumSize: minSize, foregroundColor: c.fg)),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: c.isDark ? c.raised : c.card,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
      labelStyle: TextStyle(fontFamily: fontFamily, color: c.muted, fontWeight: FontWeight.w600),
      floatingLabelStyle: TextStyle(color: c.brandInk, fontWeight: FontWeight.w700),
      hintStyle: TextStyle(color: c.subtle),
      helperStyle: TextStyle(color: c.subtle, fontSize: 12.5),
      errorStyle: TextStyle(color: c.negative, fontSize: 12.5, fontWeight: FontWeight.w600),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: c.lineStrong)),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: c.isDark ? c.border : c.lineStrong)),
      focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: c.primary, width: 2)),
      errorBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: c.negative)),
      focusedErrorBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: c.negative, width: 2)),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: c.isDark ? const Color(0xFF0B0B0B) : c.card,
      surfaceTintColor: Colors.transparent,
      indicatorColor: c.soft(c.primary, c.isDark ? 0.28 : 0.14),
      height: 68,
      elevation: 0,
      labelTextStyle: WidgetStateProperty.resolveWith((s) => TextStyle(
            fontFamily: fontFamily,
            fontSize: 12,
            fontWeight: s.contains(WidgetState.selected) ? FontWeight.w800 : FontWeight.w600,
            color: s.contains(WidgetState.selected) ? c.fg : c.subtle,
          )),
      iconTheme: WidgetStateProperty.resolveWith((s) => IconThemeData(color: s.contains(WidgetState.selected) ? c.fg : c.subtle, size: 24)),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: c.isDark ? const Color(0xFF1A1A1A) : c.card,
      surfaceTintColor: Colors.transparent,
      showDragHandle: true,
      dragHandleColor: c.lineStrong,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: c.isDark ? const Color(0xFF1E1E1E) : c.card,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22)),
      titleTextStyle: textTheme.titleLarge,
      contentTextStyle: textTheme.bodyMedium?.copyWith(color: c.muted),
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: c.isDark ? const Color(0xFFF2F2F2) : const Color(0xFF1C1C1C),
      contentTextStyle: TextStyle(fontFamily: fontFamily, color: c.isDark ? Colors.black : Colors.white, fontWeight: FontWeight.w600),
      actionTextColor: c.isDark ? const Color(0xFF6C25B0) : const Color(0xFFC8A2F0),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? Colors.white : c.muted),
      trackColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? c.primary : c.hover),
      trackOutlineColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? c.primary : c.lineStrong),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: ButtonStyle(
        minimumSize: const WidgetStatePropertyAll(Size(48, 44)),
        side: WidgetStatePropertyAll(BorderSide(color: c.lineStrong)),
        backgroundColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? c.fg : Colors.transparent),
        foregroundColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? c.background : c.fg),
        textStyle: WidgetStatePropertyAll(textTheme.labelLarge?.copyWith(fontSize: 14)),
      ),
    ),
    chipTheme: ChipThemeData(backgroundColor: c.hover, selectedColor: c.soft(c.primary, 0.2), side: BorderSide(color: c.border), labelStyle: TextStyle(fontFamily: fontFamily, color: c.fg, fontWeight: FontWeight.w600)),
    progressIndicatorTheme: ProgressIndicatorThemeData(color: c.brandInk, linearTrackColor: c.hover, circularTrackColor: Colors.transparent),
    tabBarTheme: TabBarThemeData(
      dividerColor: Colors.transparent,
      indicatorSize: TabBarIndicatorSize.tab,
      labelColor: c.isDark ? Colors.black : Colors.white,
      unselectedLabelColor: c.fg,
      labelStyle: textTheme.labelLarge?.copyWith(fontSize: 14),
      unselectedLabelStyle: textTheme.labelLarge?.copyWith(fontSize: 14, fontWeight: FontWeight.w600),
      indicator: BoxDecoration(color: c.fg, borderRadius: BorderRadius.circular(999)),
      overlayColor: WidgetStatePropertyAll(c.soft(c.fg, 0.06)),
      splashFactory: NoSplash.splashFactory,
      tabAlignment: TabAlignment.start,
      labelPadding: const EdgeInsets.symmetric(horizontal: 18),
    ),
    listTileTheme: ListTileThemeData(
      iconColor: c.muted,
      titleTextStyle: textTheme.titleSmall?.copyWith(fontSize: 15.5),
      subtitleTextStyle: textTheme.bodySmall,
      minVerticalPadding: 12,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16),
    ),
    checkboxTheme: CheckboxThemeData(
      fillColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? c.primary : Colors.transparent),
      side: BorderSide(color: c.lineStrong, width: 1.6),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(5)),
    ),
    radioTheme: RadioThemeData(fillColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? c.primary : c.lineStrong)),
    pageTransitionsTheme: const PageTransitionsTheme(builders: {
      TargetPlatform.android: FadeForwardsPageTransitionsBuilder(),
      TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
    }),
  );
}
