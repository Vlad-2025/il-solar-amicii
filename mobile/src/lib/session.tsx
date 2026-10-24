import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { api, ApiError, loadStored, setToken } from './api';
import type { Me, Session } from './types';

type Ctx = {
  me: Me | null;
  ready: boolean;
  signIn: (s: Session) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<Me | null>;
  setMe: (m: Me) => void;
};

const SessionContext = createContext<Ctx | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        if (await loadStored()) setMe(await api.me());
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) await setToken(null);
      } finally {
        setReady(true);
      }
    })();
  }, []);

  const signIn = useCallback(async (s: Session) => {
    await setToken(s.token);
    const { token: _t, ...rest } = s;
    setMe(rest);
  }, []);

  const signOut = useCallback(async () => {
    await setToken(null);
    setMe(null);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const m = await api.me();
      setMe(m);
      return m;
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        await setToken(null);
        setMe(null);
      }
      return null;
    }
  }, []);

  const value = useMemo(() => ({ me, ready, signIn, signOut, refresh, setMe }), [me, ready, signIn, signOut, refresh]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Ctx {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession must be used inside SessionProvider');
  return ctx;
}
