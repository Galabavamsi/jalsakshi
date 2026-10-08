import '@fontsource-variable/anek-devanagari/wght.css';
import '@fontsource/tiro-devanagari-hindi/400.css';
import './styles/global.css';

import { StrictMode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';
import { createHttpApi, type JalApi } from './api/client';
import { ApiProvider } from './api/context';
import { appConfig } from './appConfig';
import { AuthProvider, UNAUTHORIZED_EVENT } from './auth/AuthContext';
import { createCognitoAuth, type CognitoAuth } from './auth/cognito';
import { ConfigError } from './pages/AuthScreens';

async function createApi(auth: CognitoAuth | null): Promise<JalApi> {
  if (appConfig.mode === 'mock') {
    const { createMockApi } = await import('./api/mock');
    return createMockApi({ latencyMs: 250, actor: 'console:demo-user' });
  }
  return createHttpApi({
    baseUrl: appConfig.apiBase,
    getToken: () => (auth ? auth.getAccessToken() : Promise.resolve(null)),
    onUnauthorized: () => window.dispatchEvent(new Event(UNAUTHORIZED_EVENT)),
  });
}

async function boot(root: Root): Promise<void> {
  if (appConfig.missing.length > 0) {
    root.render(<ConfigError missing={appConfig.missing} />);
    return;
  }
  const auth = appConfig.cognito ? createCognitoAuth(appConfig.cognito) : null;
  const api = await createApi(auth);
  root.render(
    <StrictMode>
      <BrowserRouter>
        <AuthProvider auth={auth}>
          <ApiProvider api={api}>
            <App auth={auth} />
          </ApiProvider>
        </AuthProvider>
      </BrowserRouter>
    </StrictMode>,
  );
}

const container = document.getElementById('root');
if (container) void boot(createRoot(container));
