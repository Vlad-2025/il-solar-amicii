import * as Haptics from 'expo-haptics';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Alert, Pressable, Share, Text, TextInput, View } from 'react-native';

import { Button, C, Card, H2, Loading, Metric, Metrics, Notice, P, Screen, Segmented, Small } from '@/components/ui';
import { api, ApiError } from '@/lib/api';
import { draftNotes } from '@/lib/drafts';
import { kwh, lei, num, parseNum as parse, periodLabel } from '@/lib/format';
import type { Bill, BillLine } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';

const ENERGY = new Set(['energy_consumed', 'energy_delivered', 'energy_compensated', 'carryover']);

function lineValue(ln: BillLine): string {
  if (ln.amount_lei !== null && ln.amount_lei !== undefined) return lei(ln.amount_lei);
  if (ln.qty_kwh !== null && ln.qty_kwh !== undefined) return kwh(ln.qty_kwh);
  return '–';
}


export default function BillScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const billId = Number(id);
  const { data: bill, setData, loading, error } = useLoad(() => api.bill(billId));
  const notes = draftNotes(billId);

  return (
    <>
      <Stack.Screen options={{ title: bill?.status === 'draft' ? 'Verificați factura' : 'Factură' }} />
      {loading && !bill ? <Screen topInset={false}><Loading /></Screen>
        : error && !bill ? <Screen topInset={false}><Notice tone="error">{error.message}</Notice></Screen>
        : bill ? (bill.status === 'draft'
          ? <Review bill={bill} notes={notes} onDone={setData} />
          : <Explained bill={bill} onChange={setData} />) : null}
    </>
  );
}

function Review({ bill, notes, onDone }: { bill: Bill; notes?: ReturnType<typeof draftNotes>; onDone: (b: Bill) => void }) {
  const [editAll, setEditAll] = useState(false);
  const [edits, setEdits] = useState<Record<number, { qty?: string; amount?: string }>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setErr(null);
    const lines = bill.lines.map((ln, i) => {
      const e = edits[i] ?? {};
      return {
        line_type: ln.line_type, label_raw: ln.label_raw, unit_price: ln.unit_price, confidence: ln.confidence,
        qty_kwh: e.qty !== undefined ? parse(e.qty) : ln.qty_kwh,
        amount_lei: e.amount !== undefined ? parse(e.amount) : ln.amount_lei,
      };
    });
    try {
      const done = await api.confirmBill(bill.id, lines);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      onDone(done);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Nu am putut salva.');
    } finally {
      setBusy(false);
    }
  }

  const review = bill.lines.filter((l) => l.needs_review).length;
  return (
    <Screen topInset={false}>
      <P>{bill.supplier ?? 'Furnizor necunoscut'} · {periodLabel(bill.period_start, bill.period_end)}</P>
      <Notice tone={review ? 'warn' : 'ok'}>
        Am citit {bill.lines.length} rânduri{notes?.ocr_confidence ? ` (OCR, încredere ${num(notes.ocr_confidence)}%)` : ''}.
        {review ? ` ${review} rânduri au încredere scăzută: verificați-le cu factura.` : ' Verificați valorile, apoi confirmați.'}
      </Notice>
      {notes?.warnings.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
      {notes?.validation.map((v) => (
        <Small key={v.message}>{v.ok ? '✓' : '✗'} {v.message}</Small>
      ))}

      <Card>
        {bill.lines.map((ln, i) => {
          const editable = editAll || ln.needs_review;
          return (
            <View key={`${ln.line_type}-${i}`} style={{ paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: C.border, gap: 4 }}>
              <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: 8 }}>
                <Text style={{ flex: 1, fontSize: 15, color: C.text, fontWeight: ln.needs_review ? '700' : '400' }}>
                  {ln.needs_review ? '⚠ ' : ''}{ln.label}
                </Text>
                {!editable ? <Text style={{ fontSize: 15, color: C.text }}>{lineValue(ln)}</Text> : null}
              </View>
              {editable ? (
                <View style={{ flexDirection: 'row', gap: 8 }}>
                  <NumInput label="kWh" initial={ln.qty_kwh} onChange={(t) => setEdits((s) => ({ ...s, [i]: { ...s[i], qty: t } }))} />
                  {!ENERGY.has(ln.line_type) ? (
                    <NumInput label="lei" initial={ln.amount_lei} decimals={2}
                      onChange={(t) => setEdits((s) => ({ ...s, [i]: { ...s[i], amount: t } }))} />
                  ) : null}
                </View>
              ) : null}
            </View>
          );
        })}
        <Button title={editAll ? 'Editez doar rândurile marcate' : 'Corectez și alte rânduri'} kind="ghost"
          onPress={() => setEditAll((v) => !v)} />
      </Card>
      {err ? <Notice tone="error">{err}</Notice> : null}
      <Button title="Confirmă valorile" onPress={confirm} loading={busy} />
    </Screen>
  );
}

function NumInput({ label, initial, onChange, decimals = 0 }: {
  label: string; initial?: number | null; onChange: (t: string) => void; decimals?: number;
}) {
  const [v, setV] = useState(initial === null || initial === undefined ? '' : num(initial, decimals).replace(/\./g, ''));
  return (
    <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 6 }}>
      <TextInput value={v} keyboardType="decimal-pad" onChangeText={(t) => { setV(t); onChange(t); }}
        style={{ flex: 1, borderWidth: 1, borderColor: C.border, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6,
                 fontSize: 16, color: C.text, backgroundColor: '#fff' }} />
      <Text style={{ color: C.muted }}>{label}</Text>
    </View>
  );
}

function Explained({ bill, onChange }: { bill: Bill; onChange: (b: Bill) => void }) {
  const [open, setOpen] = useState<number | null>(null);
  const [threshold, setThreshold] = useState('10');
  const [busy, setBusy] = useState(false);
  const b = bill.balance;
  const flagged = bill.checks?.filter((c) => c.severity === 'worth_checking') ?? [];

  async function recheck(t: string) {
    setThreshold(t);
    setBusy(true);
    try {
      onChange(await api.recheckBill(bill.id, Number(t)));
    } finally {
      setBusy(false);
    }
  }

  function remove() {
    Alert.alert('Ștergeți factura?', 'Valorile salvate pentru această factură vor fi șterse.', [
      { text: 'Renunț', style: 'cancel' },
      { text: 'Șterge', style: 'destructive', onPress: async () => { await api.deleteBill(bill.id); router.back(); } },
    ]);
  }

  return (
    <Screen topInset={false}>
      <P>{bill.supplier ?? 'Furnizor'} · {periodLabel(bill.period_start, bill.period_end)}</P>
      <Text style={{ fontSize: 18, fontWeight: '700', color: C.text, lineHeight: 25 }}>{b.sentence}</Text>
      {bill.why_pay ? <Notice>{bill.why_pay}</Notice> : null}
      <Metrics>
        <Metric label="Consumat din rețea" value={kwh(b.consumed)} />
        <Metric label="Livrat în rețea" value={kwh(b.delivered)} />
        <Metric label="Compensat" value={kwh(b.compensated)} />
        <Metric label="Total de plată" value={lei(bill.total_lei)} />
      </Metrics>

      <H2>Ce înseamnă fiecare rând</H2>
      <Card>
        {bill.lines.map((ln, i) => (
          <Pressable key={`${ln.line_type}-${i}`} onPress={() => setOpen(open === i ? null : i)}
            style={{ paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: C.border }}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: 8 }}>
              <Text style={{ flex: 1, fontSize: 15, color: C.text }}>{open === i ? '▾' : '▸'} {ln.label}</Text>
              <Text style={{ fontSize: 15, color: C.text }}>{lineValue(ln)}</Text>
            </View>
            {open === i ? <Text style={{ marginTop: 6, fontSize: 15, lineHeight: 21, color: C.muted }}>{ln.explanation}</Text> : null}
          </Pressable>
        ))}
        {bill.rule ? <Small>Regula folosită: {bill.rule.label}{bill.rule.verified ? '' : ' (în curs de verificare)'}.</Small> : null}
      </Card>

      <H2>Verificare cu invertorul</H2>
      {!bill.premium ? (
        <Card>
          <P>Comparăm energia de pe factură cu ce a măsurat invertorul și recalculăm compensarea după lege.</P>
          <Button title="Deblochează cu Premium" onPress={() => router.push('/cont')} />
        </Card>
      ) : (
        <Card>
          <Segmented label="Semnalez diferențe mai mari de" value={threshold} onChange={recheck}
            options={['5', '10', '15', '20'].map((v) => ({ value: v, label: `${v}%` }))} />
          {busy ? <Loading text="Recalculăm..." /> : bill.checks?.map((c) => (
            <Notice key={c.check_type} tone={c.severity === 'worth_checking' ? 'warn' : c.severity === 'ok' ? 'ok' : 'info'}>
              {c.message}
            </Notice>
          ))}
        </Card>
      )}

      {bill.complaint && flagged.length ? (
        <Card>
          <H2>Cerere de verificare către furnizor</H2>
          <Small>Textul este pre-completat cu dovezile. Îl revizuiți și îl trimiteți dumneavoastră.</Small>
          <Text style={{ fontSize: 13, color: C.text, lineHeight: 19 }} numberOfLines={12}>{bill.complaint.body}</Text>
          <Button title="Trimite / copiază textul" kind="secondary"
            onPress={() => Share.share({ title: bill.complaint!.subject, message: bill.complaint!.body })} />
        </Card>
      ) : null}

      <Button title="Șterge factura" kind="danger" onPress={remove} />
    </Screen>
  );
}
