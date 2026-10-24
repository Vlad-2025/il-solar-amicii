import { useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError } from './api';

/** Loads data when the screen gains focus; pull-to-refresh calls reload(). */
export function useLoad<T>(fn: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;                // always call the latest closure
  });

  const run = useCallback(async (mode: 'focus' | 'pull') => {
    if (mode === 'pull') setRefreshing(true);
    try {
      setData(await fnRef.current());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, 'A apărut o eroare.'));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => {
    run('focus');
  }, [run]));

  return { data, setData, error, loading, refreshing, reload: () => run('pull') };
}
