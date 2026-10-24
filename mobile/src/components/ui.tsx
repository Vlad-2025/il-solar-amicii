import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type KeyboardTypeOptions,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

export const C = {
  bg: '#F4F6F9',
  card: '#FFFFFF',
  text: '#16202C',
  muted: '#5B6573',
  border: '#E1E5EB',
  primary: '#1D4E89',
  primarySoft: '#E5EDF7',
  pv: '#E8A317',
  pvBand: '#F5D38A',
  load: '#2F6DB5',
  ok: '#1E7B45',
  okBg: '#E6F4EA',
  warn: '#8A5A00',
  warnBg: '#FFF4D6',
  info: '#24527A',
  infoBg: '#E8F1FA',
  err: '#A12B2B',
  errBg: '#FBE9E9',
};

// On web, Expo's native tabs render as a floating bar at the top; keep titles clear of it.
const WEB_TABS = Platform.OS === 'web' ? 72 : 0;

export function Screen({ children, onRefresh, refreshing = false, topInset = true }: {
  children: ReactNode; onRefresh?: () => void; refreshing?: boolean; topInset?: boolean;
}) {
  const insets = useSafeAreaInsets();
  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: C.bg }}
      contentContainerStyle={{ padding: 16, paddingTop: (topInset ? insets.top + WEB_TABS : 0) + 12, paddingBottom: 40, gap: 12 }}
      keyboardShouldPersistTaps="handled"
      refreshControl={onRefresh ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} /> : undefined}>
      {children}
    </ScrollView>
  );
}

export function Title({ children }: { children: ReactNode }) {
  return <Text style={s.title}>{children}</Text>;
}

export function H2({ children }: { children: ReactNode }) {
  return <Text style={s.h2}>{children}</Text>;
}

export function P({ children, muted, style }: { children: ReactNode; muted?: boolean; style?: object }) {
  return <Text style={[s.p, muted && { color: C.muted }, style]}>{children}</Text>;
}

export function Small({ children }: { children: ReactNode }) {
  return <Text style={s.small}>{children}</Text>;
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[s.card, style]}>{children}</View>;
}

type BtnKind = 'primary' | 'secondary' | 'danger' | 'ghost';

export function Button({ title, onPress, kind = 'primary', loading, disabled, icon }: {
  title: string; onPress: () => void; kind?: BtnKind; loading?: boolean; disabled?: boolean; icon?: string;
}) {
  const bg = { primary: C.primary, secondary: C.primarySoft, danger: C.errBg, ghost: 'transparent' }[kind];
  const fg = { primary: '#fff', secondary: C.primary, danger: C.err, ghost: C.primary }[kind];
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [s.btn, { backgroundColor: bg, opacity: disabled ? 0.5 : pressed ? 0.85 : 1 }]}>
      {loading ? <ActivityIndicator color={fg} /> : (
        <Text style={[s.btnText, { color: fg }]}>{icon ? `${icon}  ` : ''}{title}</Text>
      )}
    </Pressable>
  );
}

export function Metric({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <View style={[s.metric, wide && { flexBasis: '100%' }]}>
      <Text style={s.metricLabel}>{label}</Text>
      <Text style={s.metricValue}>{value}</Text>
    </View>
  );
}

export function Metrics({ children }: { children: ReactNode }) {
  return <View style={s.metrics}>{children}</View>;
}

type Tone = 'info' | 'warn' | 'ok' | 'error';

export function Notice({ tone = 'info', children }: { tone?: Tone; children: ReactNode }) {
  const map = { info: [C.infoBg, C.info], warn: [C.warnBg, C.warn], ok: [C.okBg, C.ok], error: [C.errBg, C.err] };
  const [bg, fg] = map[tone];
  return (
    <View style={[s.notice, { backgroundColor: bg }]}>
      <Text style={{ color: fg, fontSize: 15, lineHeight: 21 }}>{children}</Text>
    </View>
  );
}

export function Field({ label, value, onChangeText, keyboardType, secure, placeholder, hint, autoCapitalize }: {
  label: string; value: string; onChangeText: (t: string) => void; keyboardType?: KeyboardTypeOptions;
  secure?: boolean; placeholder?: string; hint?: string; autoCapitalize?: 'none' | 'sentences';
}) {
  return (
    <View style={{ gap: 4 }}>
      <Text style={s.label}>{label}</Text>
      <TextInput
        style={s.input}
        value={value}
        onChangeText={onChangeText}
        keyboardType={keyboardType}
        secureTextEntry={secure}
        placeholder={placeholder}
        placeholderTextColor="#9AA3AE"
        autoCapitalize={autoCapitalize ?? 'none'}
        autoCorrect={false}
      />
      {hint ? <Text style={s.small}>{hint}</Text> : null}
    </View>
  );
}

export function Segmented<T extends string>({ label, options, value, onChange }: {
  label: string; options: { value: T; label: string }[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <View style={{ gap: 4 }}>
      <Text style={s.label}>{label}</Text>
      <View style={s.segment}>
        {options.map((o) => (
          <Pressable key={o.value} onPress={() => onChange(o.value)}
            style={[s.segItem, o.value === value && { backgroundColor: C.primary }]}>
            <Text style={{ color: o.value === value ? '#fff' : C.text, fontWeight: '600', fontSize: 14 }}>{o.label}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

export function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <View style={s.row}>
      <Text style={[s.p, { flex: 1, color: C.muted }]}>{label}</Text>
      <Text style={[s.p, { flexShrink: 1, maxWidth: '58%', textAlign: 'right' }, strong && { fontWeight: '700' }]}>{value}</Text>
    </View>
  );
}

export function Loading({ text = 'Se încarcă...' }: { text?: string }) {
  return (
    <View style={{ padding: 32, alignItems: 'center', gap: 12 }}>
      <ActivityIndicator size="large" color={C.primary} />
      <Text style={s.small}>{text}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  title: { fontSize: 28, fontWeight: '700', color: C.text },
  h2: { fontSize: 19, fontWeight: '700', color: C.text, marginTop: 4 },
  p: { fontSize: 16, lineHeight: 23, color: C.text },
  small: { fontSize: 13, lineHeight: 18, color: C.muted },
  card: { backgroundColor: C.card, borderRadius: 14, padding: 16, gap: 10, borderWidth: 1, borderColor: C.border },
  btn: { minHeight: 50, borderRadius: 12, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 16 },
  btnText: { fontSize: 16, fontWeight: '700' },
  metrics: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  metric: { flexGrow: 1, flexBasis: '45%', backgroundColor: C.card, borderRadius: 12, padding: 12, borderWidth: 1, borderColor: C.border },
  metricLabel: { fontSize: 13, color: C.muted },
  metricValue: { fontSize: 22, fontWeight: '700', color: C.text, marginTop: 2 },
  notice: { borderRadius: 12, padding: 12 },
  label: { fontSize: 14, fontWeight: '600', color: C.text },
  input: { backgroundColor: '#fff', borderWidth: 1, borderColor: C.border, borderRadius: 10, paddingHorizontal: 12,
           paddingVertical: 10, fontSize: 16, color: C.text },
  segment: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  segItem: { paddingVertical: 9, paddingHorizontal: 12, borderRadius: 999, backgroundColor: C.primarySoft },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, paddingVertical: 2 },
});
