import { router } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { DailyBars, HourlyChart } from '@/components/charts';
import { Button, C, Card, H2, Loading, Metric, Metrics, Notice, P, Row, Screen, Small, Title } from '@/components/ui';
import { api, ApiError } from '@/lib/api';
import { dayLabel, kwh, lei, monthName, num } from '@/lib/format';
import type { DayPoint, Forecast } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';

export default function Prognoza() {
  const { data, setData, loading, error, refreshing, reload } = useLoad(() => api.forecast());
  const [busy, setBusy] = useState(false);

  async function recompute() {
    setBusy(true);
    try {
      setData(await api.forecast(true));
    } finally {
      setBusy(false);
    }
  }

  if (error?.status === 402) {
    return (
      <Screen>
        <Title>Prognoză</Title>
        <Card>
          <H2>Funcție Premium</H2>
          <P>Producția pe ore pentru acoperișul dumneavoastră, consumul estimat, ce exportați și importați, și factura
            estimată pentru luna curentă.</P>
          <Button title="Vezi abonamentul (mod de test)" onPress={() => router.push('/cont')} />
        </Card>
      </Screen>
    );
  }

  return (
    <Screen onRefresh={reload} refreshing={refreshing}>
      <Title>Prognoză</Title>
      {loading && !data ? <Loading text="Calculăm prognoza..." /> : null}
      {error ? <Notice tone="error">{(error as ApiError).message}</Notice> : null}
      {data ? <ForecastView fc={data} onRecompute={recompute} busy={busy} /> : null}
    </Screen>
  );
}

function ForecastView({ fc, onRecompute, busy }: { fc: Forecast; onRecompute: () => void; busy: boolean }) {
  const m = fc.month;
  const sm = fc.solar_metrics;
  const days = fc.daily.slice(1, 8);
  return (
    <>
      <Small>Vreme: {fc.weather_source} · consum: {fc.load_method}</Small>

      <Card>
        <H2>Pe ore</H2>
        <HourlyChart data={fc.hourly} />
        <Small>{fc.lead_note} Banda arată incertitudinea modelului pentru vremea prognozată; nu include greșelile
          prognozei meteo.</Small>
      </Card>

      <Card>
        <H2>Pe zile</H2>
        <DailyBars data={days} series={[['pv', 'Producție', C.pv], ['load', 'Consum', C.load], ['exported', 'Export', '#7CB342']]} />
        <DayTable days={days} />
      </Card>

      <Card>
        <H2>Factura estimată pentru {monthName(m.month_start)}</H2>
        <Text style={{ fontSize: 20, fontWeight: '700', color: C.text, lineHeight: 27 }}>
          ~{kwh(m.billed_kwh)} facturați după compensare{m.est_lei !== null && m.est_lei !== undefined ? `, circa ${lei(m.est_lei)} pentru energie` : ''}.
        </Text>
        {m.est_lei === null || m.est_lei === undefined ? (
          <Button title="Adăugați prețul din contract" kind="ghost" onPress={() => router.push('/profil')} />
        ) : null}
        <Metrics>
          <Metric label="Consum din rețea" value={kwh(m.consumed_kwh)} />
          <Metric label="Livrat în rețea" value={kwh(m.delivered_kwh)} />
          <Metric label="Compensat" value={kwh(m.compensated_kwh)} />
          <Metric label="Credit la final" value={kwh(m.new_carryover_kwh)} />
        </Metrics>
        <Small>{num(m.measured_days)} zile măsurate, {num(m.forecast_days)} prognozate, {num(m.extrapolated_days)} extrapolate.
          Tarifele de rețea, contribuțiile și TVA se adaugă separat, ca pe factură.</Small>
      </Card>

      <Card>
        <H2>Precizia pentru sistemul dumneavoastră</H2>
        {sm ? (
          <View style={{ gap: 6 }}>
            <Row label="Model fizic + corecție învățată" value={`${num(Number(sm.nmae_pct_corrected), 2)}%`} strong />
            <Row label="Doar model fizic" value={`${num(Number(sm.nmae_pct_physics), 2)}%`} />
            <Row label="„Aceeași oră de ieri”" value={`${num(Number(sm.nmae_pct_persistence), 2)}%`} />
            <Small>Eroare medie pe oră, ca procent din puterea instalată, pe datele de după {String(sm.test_from)} (neatinse la antrenare).</Small>
          </View>
        ) : (
          <P muted>Încărcați exportul invertorului din ecranul Cont ca să antrenăm prognoza pe acoperișul dumneavoastră.</P>
        )}
      </Card>
      <Button title="Recalculează" kind="secondary" onPress={onRecompute} loading={busy} />
    </>
  );
}

const COLS: [keyof DayPoint, string][] = [['pv', 'Prod.'], ['load', 'Consum'], ['exported', 'Export'], ['imported', 'Import']];

function DayTable({ days }: { days: DayPoint[] }) {
  const cell = { flex: 1, textAlign: 'right' as const, fontSize: 14, color: C.text };
  return (
    <View style={{ gap: 4 }}>
      <View style={{ flexDirection: 'row' }}>
        <Text style={{ width: 64, fontSize: 12, color: C.muted }}>kWh/zi</Text>
        {COLS.map(([, h]) => <Text key={h} style={{ ...cell, fontSize: 12, color: C.muted }}>{h}</Text>)}
      </View>
      {days.map((d) => (
        <View key={d.date} style={{ flexDirection: 'row', paddingVertical: 3, borderTopWidth: 1, borderTopColor: C.border }}>
          <Text style={{ width: 64, fontSize: 14, color: C.text }}>{dayLabel(d.date)}</Text>
          {COLS.map(([k]) => <Text key={k} style={cell}>{num(Number(d[k] ?? 0), 1)}</Text>)}
        </View>
      ))}
    </View>
  );
}
