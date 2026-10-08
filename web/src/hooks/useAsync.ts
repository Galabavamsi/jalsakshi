import { useCallback, useEffect, useRef, useState } from 'react';

export interface AsyncState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  /** Runs the loader again, keeping the current data on screen meanwhile. */
  reload: () => void;
  /** Replaces the data, e.g. with the ticket an action returned. */
  setData: (data: T) => void;
}

interface Snapshot<T> {
  key: string;
  data: T | undefined;
  error: unknown;
  loading: boolean;
}

/**
 * Loads data for a `key` (a string of everything the loader depends on).
 * Data from a previous key is never shown for a new one.
 */
export function useAsync<T>(load: () => Promise<T>, key: string): AsyncState<T> {
  const loadRef = useRef(load);
  loadRef.current = load;
  const [version, setVersion] = useState(0);
  const [snap, setSnap] = useState<Snapshot<T>>({
    key,
    data: undefined,
    error: null,
    loading: true,
  });

  useEffect(() => {
    let live = true;
    setSnap((s) => ({
      key,
      data: s.key === key ? s.data : undefined,
      error: null,
      loading: true,
    }));
    loadRef.current().then(
      (data) => live && setSnap({ key, data, error: null, loading: false }),
      (error: unknown) => live && setSnap((s) => ({ ...s, key, error, loading: false })),
    );
    return () => {
      live = false;
    };
  }, [key, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  const setData = useCallback(
    (data: T) => setSnap({ key, data, error: null, loading: false }),
    [key],
  );
  const current = snap.key === key;
  return {
    data: current ? snap.data : undefined,
    error: current ? snap.error : null,
    loading: !current || snap.loading,
    reload,
    setData,
  };
}
