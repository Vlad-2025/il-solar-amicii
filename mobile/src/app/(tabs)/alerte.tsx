import { useState } from 'react';
import { Linking, Text, View } from 'react-native';

import { Button, C, Card, H2, Loading, Notice, P, Row, Screen, Small, Title } from '@/components/ui';
import { api, ApiError } from '@/lib/api';
import { date } from '@/lib/format';
import { useSession } from '@/lib/session';
import { useLoad } from '@/lib/useLoad';

const NTFY_PLAY = 'https://play.google.com/store/apps/details?id=io.heckel.ntfy';

export default function Alerte() {
  const { me } = useSession();
  const { data, loading, error, refreshing, reload } = useLoad(() => api.alerts());
  const [msg, setMsg] = useState<{ tone: 'ok' | 'warn' | 'error'; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const topic = me?.ntfy.topic;

  async function openNtfy() {
    const appUrl = me?.ntfy.app_url;
    // canOpenURL needs a <queries> entry on Android 11+; just try the ntfy:// link and fall back to the store.
    try {
      if (appUrl) {
        await Linking.openURL(appUrl);
        return;
      }
    } catch {
      /* ntfy not installed */
    }
    await Linking.openURL(NTFY_PLAY);
  }

  async function run(kind: 'test' | 'demo') {
    setBusy(kind);
    setMsg(null);
    try {
      const r = kind === 'test' ? await api.testAlert() : await api.demoAlert();
      setMsg(r.delivered ? { tone: 'ok', text: 'Trimisă. Verificați notificările telefonului.' }
                         : { tone: 'warn', text: 'Salvată în aplicație; serviciul ntfy nu a răspuns.' });
      reload();
    } catch (e) {
      setMsg({ tone: 'error', text: e instanceof ApiError ? e.message : 'Eroare.' });
    } finally {
      setBusy(null);
    }
  }

  const rule = data?.current_rule;
  return (
    <Screen onRefresh={reload} refreshing={refreshing}>
      <Title>Alerte</Title>

      <Card>
        <H2>Notificări pe telefon</H2>
        <P>Vă anunțăm când se schimbă regulile pentru prosumatori, cu ce înseamnă pentru instalația dumneavoastră.</P>
        <Small>1. Instalați aplicația gratuită ntfy. 2. Abonați-vă la subiectul de mai jos (butonul îl deschide direct).</Small>
        <Text selectable style={{ fontSize: 16, fontWeight: '700', color: C.primary }}>{topic}</Text>
        <Button title="Abonează-te în ntfy" onPress={openNtfy} />
        <Button title="Trimite o notificare de test" kind="secondary" onPress={() => run('test')} loading={busy === 'test'} />
        <Button title="Simulează o schimbare de lege (DEMO)" kind="ghost" onPress={() => run('demo')} loading={busy === 'demo'} />
        {msg ? <Notice tone={msg.tone}>{msg.text}</Notice> : null}
      </Card>

      {loading && !data ? <Loading /> : null}
      {error ? <Notice tone="error">{error.message}</Notice> : null}

      {rule ? (
        <Card>
          <H2>Regula care se aplică acum</H2>
          <P style={{ fontWeight: '700' }}>{rule.title}</P>
          <Small>În vigoare din {date(rule.effective_from)} · versiunea {rule.version}{rule.verified ? '' : ' · în curs de verificare'}</Small>
          <P>{rule.summary}</P>
          {rule.facts.map(([k, v]) => <Row key={k} label={k} value={v} />)}
        </Card>
      ) : null}

      {data?.change ? (
        <Card>
          <H2>Ce s-a schimbat pentru mine</H2>
          {data.change.changes.map((c) => <P key={c}>• {c}</P>)}
          <Notice>{data.change.impact}</Notice>
        </Card>
      ) : null}

      <H2>Istoric</H2>
      {!data?.notifications.length ? <P muted>Nicio alertă încă.</P> : data.notifications.map((n) => (
        <Card key={n.id}>
          <P style={{ fontWeight: '700' }}>{n.title ?? n.type}</P>
          <Small>{date(n.sent_at)} · {n.delivered ? 'trimisă pe telefon' : 'doar în aplicație'}</Small>
          <View><Text style={{ fontSize: 15, lineHeight: 21, color: C.text }}>{n.message}</Text></View>
        </Card>
      ))}
    </Screen>
  );
}
