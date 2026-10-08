import { createContext, useContext, type ReactNode } from 'react';
import type { JalApi } from './client';

const ApiContext = createContext<JalApi | null>(null);

export function ApiProvider({ api, children }: { api: JalApi; children: ReactNode }) {
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
}

/** The API client chosen at startup (real HTTP or mock). */
export function useApi(): JalApi {
  const api = useContext(ApiContext);
  if (!api) throw new Error('useApi must be used inside <ApiProvider>');
  return api;
}
