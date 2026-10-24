import * as DocumentPicker from 'expo-document-picker';
import * as ImagePicker from 'expo-image-picker';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text } from 'react-native';

import { Button, C, Card, H2, Loading, Notice, P, Screen, Small, Title } from '@/components/ui';
import { api, ApiError, type UploadFile } from '@/lib/api';
import { rememberDraft } from '@/lib/drafts';
import { lei, periodLabel } from '@/lib/format';
import { useLoad } from '@/lib/useLoad';

export default function Scan() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { data: bills, reload, refreshing } = useLoad(() => api.bills());

  async function upload(file: UploadFile) {
    setBusy(true);
    setError(null);
    try {
      const bill = await api.uploadBill(file);
      rememberDraft(bill.id, { warnings: bill.warnings ?? [], validation: bill.validation ?? [],
                               ocr_confidence: bill.ocr_confidence });
      router.push(`/bill/${bill.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Nu am putut trimite factura.');
    } finally {
      setBusy(false);
    }
  }

  async function camera() {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) {
      setError('Aplicația are nevoie de acces la cameră ca să fotografiați factura.');
      return;
    }
    // Full resolution, no cropping: OCR needs every pixel of the small print.
    const res = await ImagePicker.launchCameraAsync({ mediaTypes: ['images'], quality: 0.9, allowsEditing: false });
    if (!res.canceled) {
      const a = res.assets[0];
      await upload({ uri: a.uri, name: a.fileName ?? 'factura.jpg', type: a.mimeType ?? 'image/jpeg' });
    }
  }

  async function gallery() {
    const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.9 });
    if (!res.canceled) {
      const a = res.assets[0];
      await upload({ uri: a.uri, name: a.fileName ?? 'factura.jpg', type: a.mimeType ?? 'image/jpeg' });
    }
  }

  async function pdf() {
    const res = await DocumentPicker.getDocumentAsync({ type: 'application/pdf', copyToCacheDirectory: true });
    if (!res.canceled) {
      const a = res.assets[0];
      await upload({ uri: a.uri, name: a.name ?? 'factura.pdf', type: a.mimeType ?? 'application/pdf' });
    }
  }

  return (
    <Screen onRefresh={reload} refreshing={refreshing}>
      <Title>Factură</Title>
      <P muted>Fotografiați factura sau încărcați PDF-ul primit pe e-mail. Vă explicăm fiecare rând și, în Premium,
        o verificăm cu datele invertorului.</P>

      {busy ? <Card><Loading text="Citim factura... (o poză poate dura 10–20 de secunde)" /></Card> : (
        <Card>
          <Button title="📷  Fotografiază factura" onPress={camera} />
          <Button title="🖼  Alege o poză din galerie" kind="secondary" onPress={gallery} />
          <Button title="📄  Încarcă PDF" kind="secondary" onPress={pdf} />
          <Small>Sfat: puneți factura pe o masă, la lumină bună, și fotografiați-o drept, cât mai de aproape.
            Fișierul nu este păstrat: salvăm doar valorile citite, după ce le confirmați.</Small>
        </Card>
      )}
      {error ? <Notice tone="error">{error}</Notice> : null}

      <H2>Facturi salvate</H2>
      {!bills?.length ? <P muted>Nicio factură salvată încă.</P> : bills.map((b) => (
        <Pressable key={b.id} onPress={() => router.push(`/bill/${b.id}`)}>
          <Card>
            <Text style={{ fontSize: 16, fontWeight: '700', color: C.text }}>
              {b.supplier ?? 'Furnizor'} · {lei(b.total_lei)}
            </Text>
            <Small>{periodLabel(b.period_start, b.period_end)}{b.flagged ? ` · ⚠ ${b.flagged} de verificat` : ''}</Small>
          </Card>
        </Pressable>
      ))}
    </Screen>
  );
}
