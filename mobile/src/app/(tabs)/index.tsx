import { Redirect, router } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { DailyBars } from '@/components/charts';
import { Button, C, Card, H2, Loading, Metric, Metrics, Notice, P, Screen, Small, Title } from '@/components/ui';
import { api, ApiError } from '@/lib/api';
import { kwh, lei, num, periodLabel } from '@/lib/format';
import { useSession } from '@/lib/session';
import type { Alerts, BillSummary, ForecastSummary } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';

type Home = { summary: ForecastSummary | null; bills: BillSummary[]; alerts: Alerts | null; summaryError?: string };

export default function HomeScreen() {
  const { me } = useSession();
  const { data, loading, refreshing, reload, error } = useLoad<Home>(async () => {
    const [summary, bills, alerts] = await Promise.allSettled([api.forecastSummary(), api.bills(), api.alerts()]);
    return {
      summary: summary.status === 'fulfilled' ? summary.value : null,
      summaryError: summary.status === 'rejected' ? (summary.reason as ApiError).message : undefined,
      bills: bills.status === 'fulfilled' ? bills.value : [],
      alerts: alerts.status === 'fulfilled' ? alerts.value : null,
    };
  });

  if (me?.needs_onboarding) return <Redirect href="/profil" />;
  const site = me?.site;
  const days = data?.summary?.daily.slice(1, 8) ?? [];      // first day starts now: partial
  const lastBill = data?.bills[0];
  const lastAlert = data?.alerts?.notifications[0];

  return (
    <Screen onRefresh={reload} refreshing={refreshing}>
      <Title>Acasă</Title>
      {site ? (
        <Small>{num(site.kwp, 1)} kWp · înclinare {num(site.tilt)}° · baterie {num(site.battery_kwh ?? 0, 1)} kWh
          {me?.user.premium ? ' · Premium' : ' · plan gratuit'}</Small>
      ) : null}
      {loading ? <Loading /> : null}
      {error ? <Notice tone="error">{error.message}</Notice> : null}

      {data?.summary ? (
        <Card>
          <H2>Producția următoarelor 7 zile</H2>
          <Metrics>
            <Metric label="Total estimat" value={kwh(days.reduce((s, d) => s + d.pv, 0))} />
            <Metric label="Cea mai bună zi" value={kwh(Math.max(0, ...days.map((d) => d.pv)), 1)} />
          </Metrics>
          <DailyBars data={days} series={[['pv', 'Producție (kWh/zi)', C.pv]]} />
          <Small>Vreme: {data.summary.weather_source}. {data.summary.lead_note}</Small>
          <Button title={me?.user.premium ? 'Prognoză detaliată' : 'Consum și factura estimată (Premium)'} kind="secondary"
            onPress={() => router.push('/prognoza')} />
        </Card>
      ) : data?.summaryError ? <Notice tone="warn">{data.summaryError}</Notice> : null}

      <Card>
        <H2>Plan sistem</H2>
        <P muted>{site && site.kwp > 0
          ? 'Câte panouri și baterii să adăugați ca să cumpărați și să vindeți cât mai puțin din rețea.'
          : 'Nu aveți încă panouri: aflați câte panouri și baterii vi se potrivesc și în cât timp se amortizează.'}</P>
        <Button title="Fă planul" kind={site && site.kwp > 0 ? 'secondary' : 'primary'} onPress={() => router.push('/plan')} />
      </Card>

      <Card>
        <H2>Ultima factură</H2>
        {lastBill ? (
          <Pressable onPress={() => router.push(`/bill/${lastBill.id}`)}>
            <P>{lastBill.supplier ?? 'Furnizor'} · {periodLabel(lastBill.period_start, lastBill.period_end)}</P>
            <Text style={{ fontSize: 24, fontWeight: '700', color: C.text }}>{lei(lastBill.total_lei)}</Text>
            <Small>Consumat {kwh(lastBill.consumed_kwh)} · livrat {kwh(lastBill.delivered_kwh)} · compensat {kwh(lastBill.compensated_kwh)}</Small>
            {lastBill.flagged ? <View style={{ marginTop: 8 }}><Notice tone="warn">{lastBill.flagged} diferență(e) de verificat față de invertor.</Notice></View> : null}
          </Pressable>
        ) : <P muted>Nu ați încărcat încă nicio factură.</P>}
        <Button title="📷  Scanează o factură" onPress={() => router.push('/scan')} />
      </Card>

      {lastAlert ? (
        <Card>
          <H2>Ultima alertă</H2>
          <P style={{ fontWeight: '700' }}>{lastAlert.title}</P>
          <Small>{lastAlert.message?.split('\n').slice(-2).join(' ')}</Small>
          <Button title="Toate alertele" kind="ghost" onPress={() => router.push('/alerte')} />
        </Card>
      ) : null}
    </Screen>
  );
}
