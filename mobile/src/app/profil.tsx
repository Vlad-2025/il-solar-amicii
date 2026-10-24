import * as Location from 'expo-location';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { Button, C, Card, Field, H2, Notice, P, Screen, Segmented, Small } from '@/components/ui';
import { api, ApiError } from '@/lib/api';
import { kwh, num } from '@/lib/format';
import { useSession } from '@/lib/session';

const ORIENT = [
  { value: '180', label: 'Sud' }, { value: '135', label: 'SE' }, { value: '225', label: 'SV' },
  { value: '90', label: 'Est' }, { value: '270', label: 'Vest' },
];
const CUSTOMER = [
  { value: 'individual', label: 'Persoană fizică' }, { value: 'company', label: 'Companie' },
  { value: 'public_institution', label: 'Instituție' },
];

const toNum = (s: string) => {
  const v = Number(s.replace(',', '.'));
  return Number.isFinite(v) ? v : NaN;
};
const str = (v: number | null | undefined, fallback: string) => (v === null || v === undefined ? fallback : String(v));

export default function Profil() {
  const { me, setMe } = useSession();
  const site = me?.site;
  const onboarding = !site;

  const [lat, setLat] = useState(str(site?.lat, ''));
  const [lon, setLon] = useState(str(site?.lon, ''));
  const [kwp, setKwp] = useState(str(site?.kwp, '6'));
  const [tilt, setTilt] = useState(str(site?.tilt, '30'));
  const [azimuth, setAzimuth] = useState(str(site?.azimuth, '180'));
  const [inverter, setInverter] = useState(str(site?.inverter_kw, ''));
  const [battery, setBattery] = useState(str(site?.battery_kwh, '0'));
  const [monthly, setMonthly] = useState(str(site?.monthly_kwh, '250'));
  const [price, setPrice] = useState(str(site?.price_lei_kwh, ''));
  const [carry, setCarry] = useState(str(site?.carryover_kwh, '0'));
  const [ctype, setCtype] = useState(site?.customer_type ?? 'individual');
  const [query, setQuery] = useState('');
  const [places, setPlaces] = useState<{ name: string; admin?: string; lat: number; lon: number }[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: 'error' | 'ok' | 'info'; text: string } | null>(null);

  async function useMyLocation() {
    setBusy('gps');
    setMsg(null);
    try {
      const perm = await Location.requestForegroundPermissionsAsync();
      if (!perm.granted) {
        setMsg({ tone: 'info', text: 'Fără acces la locație. Căutați localitatea sau introduceți coordonatele.' });
        return;
      }
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      setLat(pos.coords.latitude.toFixed(4));
      setLon(pos.coords.longitude.toFixed(4));
      setMsg({ tone: 'ok', text: 'Locația a fost preluată. Salvați când sunteți acasă, pentru precizie.' });
    } catch {
      setMsg({ tone: 'error', text: 'Nu am putut afla locația.' });
    } finally {
      setBusy(null);
    }
  }

  async function search() {
    if (query.trim().length < 2) return;
    setBusy('search');
    try {
      setPlaces(await api.geocode(query.trim()));
    } catch (e) {
      setMsg({ tone: 'error', text: e instanceof ApiError ? e.message : 'Căutarea nu a reușit.' });
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    const body = {
      lat: toNum(lat), lon: toNum(lon), kwp: toNum(kwp), tilt: toNum(tilt), azimuth: toNum(azimuth),
      inverter_kw: inverter ? toNum(inverter) : null, battery_kwh: toNum(battery || '0'),
      monthly_kwh: monthly ? toNum(monthly) : null, price_lei_kwh: price ? toNum(price) : null,
      carryover_kwh: toNum(carry || '0'), customer_type: ctype, compensation_type: site?.compensation_type ?? 'quantity',
      supplier: site?.supplier ?? null,
    };
    if ([body.lat, body.lon, body.kwp, body.tilt, body.azimuth].some(Number.isNaN)) {
      setMsg({ tone: 'error', text: 'Completați locația, puterea (kWp), înclinarea și orientarea.' });
      return;
    }
    setBusy('save');
    setMsg(null);
    try {
      const m = await api.saveSite(body);
      setMe(m);
      if (onboarding) router.replace('/');
      else setMsg({ tone: 'ok', text: 'Profil salvat.' });
    } catch (e) {
      setMsg({ tone: 'error', text: e instanceof ApiError ? e.message : 'Nu am putut salva.' });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Screen topInset={false}>
      {onboarding ? (
        <P>Bun venit! Avem nevoie de locația casei și de datele panourilor pentru prognoză. Le găsiți în contractul
          cu instalatorul sau în aplicația invertorului.</P>
      ) : null}

      <Card>
        <H2>Locație</H2>
        <Button title="Folosește locația mea" kind="secondary" onPress={useMyLocation} loading={busy === 'gps'} />
        <Field label="Sau căutați localitatea" value={query} onChangeText={setQuery} placeholder="ex. Cluj-Napoca"
          autoCapitalize="sentences" />
        <Button title="Caută" kind="ghost" onPress={search} loading={busy === 'search'} />
        {places.map((p) => (
          <Pressable key={`${p.lat},${p.lon}`} onPress={() => { setLat(p.lat.toFixed(4)); setLon(p.lon.toFixed(4)); setPlaces([]); }}>
            <Text style={{ color: C.primary, fontSize: 16, paddingVertical: 6 }}>{p.name}{p.admin ? `, ${p.admin}` : ''}</Text>
          </Pressable>
        ))}
        <View style={{ flexDirection: 'row', gap: 10 }}>
          <View style={{ flex: 1 }}><Field label="Latitudine" value={lat} onChangeText={setLat} keyboardType="decimal-pad" /></View>
          <View style={{ flex: 1 }}><Field label="Longitudine" value={lon} onChangeText={setLon} keyboardType="decimal-pad" /></View>
        </View>
      </Card>

      <Card>
        <H2>Panouri și baterie</H2>
        <Field label="Putere instalată (kWp)" value={kwp} onChangeText={setKwp} keyboardType="decimal-pad"
          hint="0 dacă nu aveți încă panouri: Plan sistem vă spune câte vă trebuie." />
        <Field label="Înclinare panouri (°)" value={tilt} onChangeText={setTilt} keyboardType="number-pad" hint="0 = orizontal, 30–35 tipic" />
        <Segmented label="Orientare" options={ORIENT} value={ORIENT.some((o) => o.value === azimuth) ? azimuth : '180'} onChange={setAzimuth} />
        <Field label="Putere invertor (kW, opțional)" value={inverter} onChangeText={setInverter} keyboardType="decimal-pad" />
        <Field label="Baterie (kWh, 0 dacă nu aveți)" value={battery} onChangeText={setBattery} keyboardType="decimal-pad" />
      </Card>

      <Card>
        <H2>Contract</H2>
        <Segmented label="Tip client" options={CUSTOMER} value={ctype} onChange={setCtype} />
        <Field label="Preț total pe kWh din contract (lei, cu taxe)" value={price} onChangeText={setPrice}
          keyboardType="decimal-pad" hint="Pentru factura estimată. Îl găsiți pe factură." />
        <Field label="Consum lunar tipic (kWh)" value={monthly} onChangeText={setMonthly} keyboardType="number-pad" />
        <Field label="Credit reportat pe ultima factură (kWh)" value={carry} onChangeText={setCarry} keyboardType="number-pad" />
      </Card>

      {site?.pvgis_annual_kwh ? (
        <Notice>PVGIS estimează {kwh(site.pvgis_annual_kwh)} pe an pentru {num(site.kwp, 1)} kWp în această locație.</Notice>
      ) : null}
      {msg ? <Notice tone={msg.tone}>{msg.text}</Notice> : null}
      <Button title={onboarding ? 'Salvează și continuă' : 'Salvează'} onPress={save} loading={busy === 'save'} />
      <Small>Locația este folosită doar pentru prognoza producției.</Small>
    </Screen>
  );
}
