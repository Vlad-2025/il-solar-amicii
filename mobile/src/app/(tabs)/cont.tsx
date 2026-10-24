import * as DocumentPicker from 'expo-document-picker';
import * as Linking from 'expo-linking';
import { router } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';

import { Button, Card, Field, H2, Notice, P, Row, Screen, Small, Title } from '@/components/ui';
import { api, ApiError, baseUrl, setServer } from '@/lib/api';
import { date, kwh, num } from '@/lib/format';
import { useSession } from '@/lib/session';
import { useLoad } from '@/lib/useLoad';

type Msg = { tone: 'ok' | 'warn' | 'error' | 'info'; text: string } | null;

export default function Cont() {
  const { me, refresh, signOut, setMe } = useSession();
  const { data: sub, reload: reloadSub } = useLoad(() => api.subscription());
  const { data: readings, reload: reloadReadings } = useLoad(() => api.readingsSummary());
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<Msg>(null);
  const [server, setServerText] = useState(baseUrl());

  async function guarded(kind: string, fn: () => Promise<void>) {
    setBusy(kind);
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setMsg({ tone: 'error', text: e instanceof ApiError ? e.message : 'A apărut o eroare.' });
    } finally {
      setBusy(null);
    }
  }

  const subscribe = () => guarded('pay', async () => {
    const returnUrl = Linking.createURL('cont');                 // prosumer://cont, or exp://… in Expo Go
    const { url } = await api.checkout(returnUrl);
    const res = await WebBrowser.openAuthSessionAsync(url, returnUrl);
    if (res.type === 'success') {
      const status = Linking.parse(res.url).queryParams?.status;
      setMsg(status === 'ok' ? { tone: 'ok', text: 'Plata de test a fost confirmată. Premium este activ.' }
                             : { tone: 'warn', text: 'Plata nu a fost finalizată.' });
    }
    await refresh();
    reloadSub();
  });

  const demoUnlock = () => guarded('unlock', async () => {
    setMe(await api.demoUnlock());
    reloadSub();
    setMsg({ tone: 'ok', text: 'Premium activat pentru contul demo.' });
  });

  const cancel = () => guarded('cancel', async () => {
    setMe(await api.cancel());
    reloadSub();
  });

  const uploadExport = () => guarded('upload', async () => {
    const res = await DocumentPicker.getDocumentAsync({
      type: ['text/csv', 'text/comma-separated-values', 'application/json', 'text/plain',
             'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-excel'],
      copyToCacheDirectory: true,
    });
    if (res.canceled) return;
    const a = res.assets[0];
    const r = await api.uploadReadings({ uri: a.uri, name: a.name, type: a.mimeType ?? 'text/csv' });
    setMsg({ tone: 'ok', text: `Am importat ${num(r.hours)} ore (${date(r.report.start)} – ${date(r.report.end)}). `
      + 'Apăsați „Antrenează prognoza” ca să o potrivim pe acoperișul dumneavoastră.'
      + (r.report.warnings.length ? `\n${r.report.warnings.join('\n')}` : '') });
    reloadReadings();
  });

  const train = () => guarded('train', async () => {
    const r = await api.train();
    const parts = Object.entries(r).map(([k, v]) => `${k === 'solar' ? 'Producție' : 'Consum'}: ${'error' in v ? String(v.error) : 'antrenat'}`);
    setMsg({ tone: 'info', text: parts.join('\n') });
  });

  const saveServer = () => guarded('server', async () => {
    await setServer(server.trim() || null);
    setServerText(baseUrl());
    await api.health();
    setMsg({ tone: 'ok', text: `Conectat la ${baseUrl()}.` });
  });

  const premium = me?.user.premium;
  return (
    <Screen>
      <Title>Cont</Title>
      <Small>{me?.user.email}</Small>

      <Card>
        <H2>{premium ? 'Plan Premium' : 'Plan gratuit'}</H2>
        {premium ? (
          <>
            <P>Verificarea facturii cu invertorul, prognoza, factura estimată și cererea către furnizor sunt active.</P>
            {sub?.current_period_end ? <Small>Perioada curentă se încheie pe {date(sub.current_period_end)}.</Small> : null}
            <Button title="Revino la planul gratuit (test)" kind="ghost" onPress={cancel} loading={busy === 'cancel'} />
          </>
        ) : (
          <>
            <P>Premium · 19 lei/lună: verificarea facturii cu datele invertorului, recalcularea compensării, prognoza pe
              ore, factura estimată și cererea de verificare către furnizor.</P>
            <Notice tone="warn">Mod de test: nu se percep bani reali. Card de test: {sub?.test_card ?? '4242 4242 4242 4242'},
              orice dată viitoare, orice CVC.</Notice>
            {sub?.stripe_configured ? <Button title="Abonează-te (Stripe, test)" onPress={subscribe} loading={busy === 'pay'} /> : null}
            {sub?.demo_unlock ? <Button title="Activează Premium pentru demo" onPress={demoUnlock} loading={busy === 'unlock'} /> : null}
            {sub && !sub.stripe_configured && !sub.demo_unlock ? <Small>Plățile nu sunt configurate pe acest server.</Small> : null}
          </>
        )}
      </Card>

      <Card>
        <H2>Instalația</H2>
        {me?.site ? (
          <>
            <Row label="Putere" value={`${num(me.site.kwp, 1)} kWp`} />
            <Row label="Înclinare / orientare" value={`${num(me.site.tilt)}° / ${num(me.site.azimuth)}°`} />
            <Row label="Baterie" value={kwh(me.site.battery_kwh ?? 0, 1)} />
          </>
        ) : null}
        <Button title="Editează profilul" kind="secondary" onPress={() => router.push('/profil')} />
        <Button title="Plan sistem: panouri, baterii, amortizare" kind="ghost" onPress={() => router.push('/plan')} />
      </Card>

      <Card>
        <H2>Date de la invertor</H2>
        {readings && readings.rows ? (
          <Small>{num(readings.rows)} ore, {date(readings.start)} – {date(readings.end)}{readings.has_load ? '' : ' · fără consumul casei'}</Small>
        ) : <Small>Încă nu ați încărcat un export.</Small>}
        <P muted>Exportați datele din aplicația invertorului (CSV, Excel sau JSON) și încărcați fișierul aici.</P>
        <Button title="Încarcă exportul" kind="secondary" onPress={uploadExport} loading={busy === 'upload'} />
        <Button title="Antrenează prognoza" kind="ghost" onPress={train} loading={busy === 'train'} />
      </Card>

      {msg ? <Notice tone={msg.tone}>{msg.text}</Notice> : null}

      <Card>
        <H2>Server</H2>
        <Field label="Adresa API" value={server} onChangeText={setServerText} placeholder="https://..."
          hint="Pentru testare locală: http://IP-ul-laptopului:8000" />
        <Button title="Salvează și testează" kind="ghost" onPress={saveServer} loading={busy === 'server'} />
      </Card>

      <Button title="Ieșire din cont" kind="danger" onPress={signOut} />
    </Screen>
  );
}
