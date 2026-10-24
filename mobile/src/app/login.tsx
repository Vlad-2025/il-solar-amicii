import { useState } from 'react';
import { KeyboardAvoidingView, Platform, View } from 'react-native';

import { Button, Card, Field, Notice, P, Screen, Segmented, Small, Title } from '@/components/ui';
import { api, ApiError, baseUrl } from '@/lib/api';
import { useSession } from '@/lib/session';

export default function Login() {
  const { signIn } = useSession();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState<'demo' | 'form' | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(kind: 'demo' | 'form') {
    setError(null);
    if (kind === 'form' && (!email.includes('@') || password.length < 8)) {
      setError('Introduceți un e-mail valid și o parolă de cel puțin 8 caractere.');
      return;
    }
    setBusy(kind);
    try {
      const s = kind === 'demo' ? await api.demo()
        : mode === 'login' ? await api.login(email.trim(), password) : await api.register(email.trim(), password);
      await signIn(s);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'A apărut o eroare.');
    } finally {
      setBusy(null);
    }
  }

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Screen>
        <View style={{ height: 24 }} />
        <Title>☀️ Asistent Prosumator</Title>
        <P muted>Înțelegeți-vă factura de energie, verificați-o cu datele invertorului și aflați cât veți produce.</P>

        <Button title="Intră în contul demo" onPress={() => run('demo')} loading={busy === 'demo'} />
        <Small>Gospodărie fictivă din București: 6 kWp, baterie 5 kWh, un an de date.</Small>

        <Card>
          <Segmented label="" value={mode} onChange={setMode}
            options={[{ value: 'login', label: 'Autentificare' }, { value: 'register', label: 'Cont nou' }]} />
          <Field label="E-mail" value={email} onChangeText={setEmail} keyboardType="email-address" />
          <Field label="Parolă" value={password} onChangeText={setPassword} secure
            hint={mode === 'register' ? 'Minim 8 caractere.' : undefined} />
          <Button title={mode === 'login' ? 'Intră' : 'Creează cont'} kind="secondary" onPress={() => run('form')}
            loading={busy === 'form'} />
        </Card>

        {error ? <Notice tone="error">{error}</Notice> : null}
        <Small>Server: {baseUrl()}. Plățile rulează în modul de test Stripe: nu se percep bani reali.</Small>
      </Screen>
    </KeyboardAvoidingView>
  );
}
