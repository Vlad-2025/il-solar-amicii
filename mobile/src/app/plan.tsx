import { useState } from 'react';
import { Alert, Pressable, Text, View } from 'react-native';

import { GroupedBars } from '@/components/charts';
import { Button, C, Card, Field, H2, Loading, Metric, Metrics, Notice, P, Row, Screen, Segmented, Small } from '@/components/ui';
import { api, ApiError } from '@/lib/api';
import { kwh, lei, num, parseNum } from '@/lib/format';
import { useSession } from '@/lib/session';
import type { CatalogItem, Device, Plan, PlanCatalog, PlanSettings } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';

type Data = { plan: Plan; devices: Device[]; settings: PlanSettings; catalog: PlanCatalog };
const MONTHS = ['ian', 'feb', 'mar', 'apr', 'mai', 'iun', 'iul', 'aug', 'sep', 'oct', 'nov', 'dec'];

export default function PlanScreen() {
  const { data, setData, loading, error } = useLoad<Data>(async () => {
    const [plan, devices, settings, catalog] = await Promise.all([api.plan(), api.devices(), api.planSettings(), api.planCatalog()]);
    return { plan, devices, settings, catalog };
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function refresh(change: () => Promise<unknown>) {
    if (!data) return;
    setBusy(true);
    setMsg(null);
    try {
      await change();
      const [plan, devices, settings] = await Promise.all([api.plan(true), api.devices(), api.planSettings()]);
      setData({ ...data, plan, devices, settings });
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : 'A apărut o eroare.');
    } finally {
      setBusy(false);
    }
  }

  if (loading && !data) return <Screen topInset={false}><Loading text="Simulăm un an pentru fiecare combinație de panouri și baterii..." /></Screen>;
  if (error && !data) return <Screen topInset={false}><Notice tone="error">{error.message}</Notice></Screen>;
  if (!data) return null;
  const { plan } = data;

  return (
    <Screen topInset={false}>
      <P muted>Câte panouri și baterii vă trebuie ca să folosiți acasă aproape toată energia produsă, stocând surplusul:
        cumpărați și vindeți cât mai puțin din rețea.</P>
      {busy ? <Loading text="Recalculăm planul..." /> : null}
      {msg ? <Notice tone="error">{msg}</Notice> : null}
      <Recommendation plan={plan} />
      <Months plan={plan} />
      <Alternatives plan={plan} />
      <Tips plan={plan} />
      <Money plan={plan} />
      <Devices data={data} onChange={refresh} />
      <SettingsCard data={data} onChange={refresh} />
      <Card>
        <H2>De știut</H2>
        <Small>Consumul de bază: {plan.baseline.label} · {kwh(plan.baseline.annual_kwh)}/an · încredere {plan.baseline.confidence}.</Small>
        {plan.baseline.notes.map((n) => <Small key={n}>• {n}</Small>)}
        {plan.limits.map((n) => <Small key={n}>• {n}</Small>)}
        <Small>Vreme: {plan.production.weather_source} · {plan.combinations_tested} combinații testate.</Small>
      </Card>
    </Screen>
  );
}

function headline(plan: Plan): string {
  const r = plan.recommended;
  const mod = num(r.battery_module_kwh, 1);
  if (plan.current.kwp > 0) {
    if (!r.panels_added && !r.battery_modules_added) return 'Sistemul actual este deja cel mai eficient pentru consumul dumneavoastră.';
    const parts = [];
    if (r.panels_added) parts.push(`${r.panels_added} ${r.panels_added === 1 ? 'panou' : 'panouri'} de ${r.panel_wp} W`);
    if (r.battery_modules_added) parts.push(`${r.battery_modules_added} ${r.battery_modules_added === 1 ? 'modul' : 'module'} de baterie de ${mod} kWh`);
    return `Adăugați ${parts.join(' și ')}.`;
  }
  return `${r.panels_total} panouri de ${r.panel_wp} W (${num(r.kwp, 2)} kWp) și ${r.battery_modules_total} ` +
    `${r.battery_modules_total === 1 ? 'modul' : 'module'} de baterie de ${mod} kWh.`;
}

function Recommendation({ plan }: { plan: Plan }) {
  const r = plan.recommended;
  const c = plan.current;
  return (
    <Card>
      <H2>Recomandarea</H2>
      <Text style={{ fontSize: 19, fontWeight: '700', color: C.text, lineHeight: 26 }}>{headline(plan)}</Text>
      <Small>Total: {num(r.kwp, 2)} kWp, {num(r.battery_kwh, 1)} kWh stocare, invertor ~{num(r.inverter_kw_suggested, 1)} kW.</Small>
      <Metrics>
        <Metric label="Cumpărat / an" value={kwh(r.bought_kwh)} />
        <Metric label="Vândut / an" value={kwh(r.sold_kwh)} />
        <Metric label="Solar folosit acasă" value={`${num(r.self_consumption_pct)}%`} />
        <Metric label="Consum acoperit" value={`${num(r.self_sufficiency_pct)}%`} />
      </Metrics>
      <Small>Acum: cumpărați {kwh(c.bought_kwh)} și vindeți {kwh(c.sold_kwh)} pe an. Consum luat în calcul:
        {' '}{kwh(plan.demand_kwh)}.</Small>
    </Card>
  );
}

function Months({ plan }: { plan: Plan }) {
  // The window is the last 365 days, so the first and last month are partial and share a name: add the year.
  const names = plan.months_recommended.map((m) => MONTHS[Number(m.month.slice(5, 7)) - 1]);
  const label = (i: number) => (names.indexOf(names[i]) !== names.lastIndexOf(names[i])
    ? `${names[i]}'${plan.months_recommended[i].month.slice(2, 4)}` : names[i]);
  const rows = (key: 'bought' | 'sold') => plan.months_recommended.map((m, i) => ({
    label: label(i),
    values: [plan.months_current[i]?.[key] ?? 0, m[key]],
  }));
  return (
    <Card>
      <H2>Pe luni</H2>
      <Small>Cumpărat din rețea (kWh)</Small>
      <GroupedBars rows={rows('bought')} series={[['Acum', '#E8A0A0'], ['Cu planul', '#C0504D']]} />
      <Small>Vândut în rețea (kWh)</Small>
      <GroupedBars rows={rows('sold')} series={[['Acum', '#C5E1A5'], ['Cu planul', '#7CB342']]} />
      <Small>Iarna se cumpără mai mult, vara se vinde surplusul de la prânz: bateriile mută energia de la zi la seară,
        nu de la vară la iarnă.</Small>
    </Card>
  );
}

function Alternatives({ plan }: { plan: Plan }) {
  return (
    <Card>
      <H2>De ce exact atât</H2>
      {plan.alternatives.map((a) => (
        <View key={a.label} style={{ borderTopWidth: 1, borderTopColor: C.border, paddingTop: 6, gap: 2 }}>
          <Text style={{ fontSize: 15, fontWeight: a.label === 'Recomandat' ? '700' : '600', color: C.text }}>{a.label}</Text>
          <Small>{num(a.kwp, 2)} kWp · {num(a.battery_kwh, 1)} kWh · cumpărat {num(a.bought_kwh)} + vândut {num(a.sold_kwh)}
            {' '}= {kwh(a.exchange_kwh)} · acoperire {num(a.self_sufficiency_pct)}%{a.battery_cycles ? ` · ${a.battery_cycles} cicluri/an (toată bateria)` : ''}</Small>
        </View>
      ))}
      {plan.stop_reasons.map((s) => <Small key={s}>• {s}</Small>)}
    </Card>
  );
}

function Tips({ plan }: { plan: Plan }) {
  if (!plan.schedule_tips.length) return null;
  return (
    <Card>
      <H2>Mutați aparatele flexibile la soare</H2>
      {plan.schedule_tips.map((t) => (
        <Notice key={`${t.name}-${t.to_hour}`} tone="ok">
          {t.name}: mutați pornirea la ora {t.to_hour}:00 (acum {t.from_hour}:00). Ar folosi {kwh(t.solar_kwh_after)} pe an
          din panouri în loc de {kwh(t.solar_kwh_now)}.
        </Notice>
      ))}
    </Card>
  );
}

function Money({ plan }: { plan: Plan }) {
  const m = plan.payback;
  const c = plan.costs;
  return (
    <Card>
      <H2>Bani și amortizare</H2>
      {!m ? <P muted>Adăugați prețul pe kWh din contract în Profil ca să calculăm amortizarea.</P>
        : c.gross_lei === 0 ? <P muted>Nu este nimic de cumpărat.</P> : (
          <>
            <Metrics>
              <Metric label="Investiție" value={lei(c.gross_lei)} />
              <Metric label="De plătit (după subvenții)" value={lei(c.net_lei)} />
            </Metrics>
            <Small>Factura de energie pe un an: {lei(m.bills_year1.before_lei)} → {lei(m.bills_year1.after_lei)}.
              {m.battery_replacement_year ? ` Bateria se înlocuiește în anul ${m.battery_replacement_year} (inclus).` : ''}</Small>
            {Object.entries(m.scenarios).map(([k, s]) => (
              <Row key={k} label={s.label}
                value={s.payback_years !== null ? `${num(s.payback_years, 1)} ani` : 'peste 25 de ani'} />
            ))}
            <Small>Până în 2030 se aplică regulile de azi; după, scenariile sunt ipoteze, nu prognoze. Sub compensarea de azi
              bateriile economisesc puțini bani.</Small>
          </>
        )}
      {plan.existing_payback ? (
        <Notice>Sistemul actual economisește ~{lei(plan.existing_payback.saving_year_lei)} pe an
          {plan.existing_payback.payback_years.current ? ` și se amortizează în ~${num(plan.existing_payback.payback_years.current, 1)} ani` : ''}.</Notice>
      ) : null}
    </Card>
  );
}

function Devices({ data, onChange }: { data: Data; onChange: (fn: () => Promise<unknown>) => Promise<void> }) {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const annual = new Map(data.plan.devices.map((d) => [d.id, d.annual_kwh]));
  const devicesMode = data.settings.baseline_mode === 'devices';

  function add(item: CatalogItem) {
    const { key: _key, ...dev } = item;
    setAdding(false);
    onChange(() => api.addDevice({ ...dev, is_new: !devicesMode }));
  }

  function remove(d: Device) {
    Alert.alert(`Ștergeți „${d.name}”?`, '', [
      { text: 'Renunț', style: 'cancel' },
      { text: 'Șterge', style: 'destructive', onPress: () => onChange(() => api.deleteDevice(d.id!)) },
    ]);
  }

  return (
    <Card>
      <H2>Aparate</H2>
      <Small>{devicesMode ? 'Consumul se calculează doar din aceste aparate.'
        : 'Adăugați aparatele noi (mașină electrică, pompă de căldură...). Ele se adaugă peste consumul de acum.'}</Small>
      {data.devices.map((d) => (
        <View key={d.id} style={{ borderTopWidth: 1, borderTopColor: C.border, paddingTop: 6, gap: 4 }}>
          <Pressable onPress={() => setEditing(editing === d.id ? null : d.id!)}>
            <Text style={{ fontSize: 15, fontWeight: '600', color: C.text }}>
              {editing === d.id ? '▾' : '▸'} {d.name}{d.quantity && d.quantity > 1 ? ` × ${d.quantity}` : ''}
            </Text>
            <Small>{kwh(annual.get(d.id) ?? null)}/an · {d.is_new ? 'nou' : 'existent'}{d.flexible ? ' · ora se poate muta' : ''}</Small>
          </Pressable>
          {editing === d.id ? (
            <DeviceForm device={d} onSave={(nd) => { setEditing(null); onChange(() => api.updateDevice(d.id!, nd)); }}
              onDelete={() => remove(d)} />
          ) : null}
        </View>
      ))}
      {adding ? (
        <View style={{ gap: 6 }}>
          {data.catalog.catalog.map((c) => (
            <Pressable key={c.key} onPress={() => add(c)} style={{ paddingVertical: 8, borderTopWidth: 1, borderTopColor: C.border }}>
              <Text style={{ fontSize: 15, color: C.primary }}>+ {c.name}</Text>
            </Pressable>
          ))}
          <Button title="Renunț" kind="ghost" onPress={() => setAdding(false)} />
        </View>
      ) : <Button title="Adaugă un aparat" kind="secondary" onPress={() => setAdding(true)} />}
    </Card>
  );
}

function DeviceForm({ device, onSave, onDelete }: { device: Device; onSave: (d: Device) => void; onDelete: () => void }) {
  const s = (v?: number | null) => (v === null || v === undefined ? '' : String(v));
  const [f, setF] = useState({
    power_w: s(device.power_w), hours_per_day: s(device.hours_per_day), start_hour: s(device.start_hour),
    days_per_week: s(device.days_per_week), annual_kwh: s(device.annual_kwh), ev_km_day: s(device.ev_km_day),
    ev_kwh_100km: s(device.ev_kwh_100km), quantity: s(device.quantity ?? 1),
  });
  const [flexible, setFlexible] = useState(device.flexible ? 'da' : 'nu');
  const [isNew, setIsNew] = useState(device.is_new === false ? 'nu' : 'da');
  const set = (k: keyof typeof f) => (t: string) => setF((x) => ({ ...x, [k]: t }));
  const k = device.kind;
  const climate = k === 'heating' || k === 'cooling';

  function save() {
    const n = (t: string) => parseNum(t);
    onSave({
      ...device, power_w: n(f.power_w), hours_per_day: n(f.hours_per_day), start_hour: n(f.start_hour),
      days_per_week: n(f.days_per_week), annual_kwh: n(f.annual_kwh), ev_km_day: n(f.ev_km_day),
      ev_kwh_100km: n(f.ev_kwh_100km), quantity: Math.max(1, Math.round(n(f.quantity) ?? 1)),
      flexible: flexible === 'da', is_new: isNew === 'da',
    });
  }

  return (
    <View style={{ gap: 8 }}>
      {climate ? <Field label="Consum pe an (kWh)" value={f.annual_kwh} onChangeText={set('annual_kwh')} keyboardType="decimal-pad"
        hint="Se distribuie după temperatura de afară." /> : null}
      {!climate ? <Field label={k === 'ev' ? 'Putere încărcător (W)' : 'Putere (W)'} value={f.power_w} onChangeText={set('power_w')} keyboardType="number-pad" /> : null}
      {k === 'schedule' || k === 'continuous' ? <Field label={k === 'continuous' ? 'Ore de funcționare pe zi (compresor)' : 'Ore pe zi'}
        value={f.hours_per_day} onChangeText={set('hours_per_day')} keyboardType="decimal-pad" /> : null}
      {k === 'ev' ? (
        <>
          <Field label="Kilometri pe zi" value={f.ev_km_day} onChangeText={set('ev_km_day')} keyboardType="decimal-pad" />
          <Field label="Consum (kWh/100 km)" value={f.ev_kwh_100km} onChangeText={set('ev_kwh_100km')} keyboardType="decimal-pad" />
        </>
      ) : null}
      {k === 'schedule' || k === 'ev' ? (
        <>
          <Field label="Pornește la ora (0–23)" value={f.start_hour} onChangeText={set('start_hour')} keyboardType="number-pad" />
          <Field label="Zile pe săptămână" value={f.days_per_week} onChangeText={set('days_per_week')} keyboardType="number-pad" />
          <Segmented label="Pot muta ora de pornire" value={flexible} onChange={setFlexible}
            options={[{ value: 'da', label: 'Da' }, { value: 'nu', label: 'Nu' }]} />
        </>
      ) : null}
      <Field label="Bucăți" value={f.quantity} onChangeText={set('quantity')} keyboardType="number-pad" />
      <Segmented label="Aparat nou (încă nu îl aveți)" value={isNew} onChange={setIsNew}
        options={[{ value: 'da', label: 'Nou' }, { value: 'nu', label: 'Îl am deja' }]} />
      <Button title="Salvează aparatul" onPress={save} />
      <Button title="Șterge" kind="danger" onPress={onDelete} />
    </View>
  );
}

function SettingsCard({ data, onChange }: { data: Data; onChange: (fn: () => Promise<unknown>) => Promise<void> }) {
  const st = data.settings;
  const [open, setOpen] = useState(false);
  const [area, setArea] = useState(String(st.area));
  const [usage, setUsage] = useState(String(st.usage_type));
  const [mode, setMode] = useState(String(st.baseline_mode));
  const [f, setF] = useState({
    annual_kwh: st.annual_kwh ? String(st.annual_kwh) : '', panel_wp: String(st.panel_wp),
    battery_module_kwh: String(st.battery_module_kwh), max_panels: String(st.max_panels),
    max_battery_modules: String(st.max_battery_modules), price_pv_lei_kwp: String(st.price_pv_lei_kwp),
    price_batt_lei_kwh: String(st.price_batt_lei_kwh),
  });
  const [casa, setCasa] = useState(st.casa_verde_baterii ? 'da' : 'nu');
  const { me } = useSession();
  const set = (k: keyof typeof f) => (t: string) => setF((x) => ({ ...x, [k]: t }));

  function save() {
    const n = (t: string) => parseNum(t);
    onChange(() => api.savePlanSettings({
      area, usage_type: usage, baseline_mode: mode, annual_kwh: n(f.annual_kwh), panel_wp: n(f.panel_wp) ?? 450,
      battery_module_kwh: n(f.battery_module_kwh) ?? 5, max_panels: n(f.max_panels) ?? 30,
      max_battery_modules: n(f.max_battery_modules) ?? 4, price_pv_lei_kwp: n(f.price_pv_lei_kwp) ?? 4500,
      price_batt_lei_kwh: n(f.price_batt_lei_kwh) ?? 1200, casa_verde_baterii: casa === 'da',
    }));
    setOpen(false);
  }

  if (!open) return <Button title="Setări consum, panouri și prețuri" kind="secondary" onPress={() => setOpen(true)} />;
  return (
    <Card>
      <H2>Setări</H2>
      <Segmented label="Consumul de bază" value={mode} onChange={setMode}
        options={[{ value: 'auto', label: 'Din datele mele' }, { value: 'devices', label: 'Doar din aparate' }]} />
      <Field label="Consum anual (kWh, opțional)" value={f.annual_kwh} onChangeText={set('annual_kwh')} keyboardType="number-pad"
        hint="Folosit când nu avem cel puțin două săptămâni de date de la invertor." />
      <Segmented label="Zona" value={area} onChange={setArea}
        options={Object.entries(data.catalog.areas).map(([value, label]) => ({ value, label }))} />
      <Segmented label="Când consumați" value={usage} onChange={setUsage}
        options={[{ value: 'auto', label: 'Automat' }, { value: 'standard', label: 'Mediu' }, { value: 'day', label: 'Mult ziua' },
          { value: 'night', label: 'Mult seara' }]} />
      <Field label="Putere panou (W)" value={f.panel_wp} onChangeText={set('panel_wp')} keyboardType="number-pad" />
      <Field label="Modul baterie (kWh)" value={f.battery_module_kwh} onChangeText={set('battery_module_kwh')} keyboardType="decimal-pad" />
      <Field label="Maxim panouri pe acoperiș" value={f.max_panels} onChangeText={set('max_panels')} keyboardType="number-pad" />
      <Field label="Maxim module baterie" value={f.max_battery_modules} onChangeText={set('max_battery_modules')} keyboardType="number-pad" />
      <Field label="Preț montat (lei/kWp)" value={f.price_pv_lei_kwp} onChangeText={set('price_pv_lei_kwp')} keyboardType="number-pad" />
      <Field label="Preț baterie (lei/kWh)" value={f.price_batt_lei_kwh} onChangeText={set('price_batt_lei_kwh')} keyboardType="number-pad" />
      <Segmented label="Includ Casa Verde Baterii (≥10 kWh, sesiune neanunțată încă)" value={casa} onChange={setCasa}
        options={[{ value: 'da', label: 'Da' }, { value: 'nu', label: 'Nu' }]} />
      <Small>Prețuri implicite cu TVA (surse verificate la 13.10.2026): sisteme ~2.900–5.000 lei/kWp, baterii ~720–2.300 lei/kWh.
        {me?.site?.price_lei_kwh ? '' : ' Adăugați în Profil prețul pe kWh din contract pentru amortizare.'}</Small>
      <Button title="Salvează și recalculează" onPress={save} />
      <Button title="Renunț" kind="ghost" onPress={() => setOpen(false)} />
    </Card>
  );
}
