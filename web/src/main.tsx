import '@fontsource-variable/inter/wght.css';
import './styles/tokens.css';
import './styles/base.css';
import './styles/app.css';

import { StrictMode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';
import { createHttpApi, type JalApi } from './api/client';
import { ApiProvider } from './api/context';
import { appConfig } from './appConfig';
import { AuthProvider, UNAUTHORIZED_EVENT } from './auth/AuthContext';
import { createCognitoAuth, type CognitoAuth } from './auth/cognito';
import { mockIdentityFromUrl } from './lib/demo';
import { ConfigError } from './shell';

function sessionStore(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

async function createApi(auth: CognitoAuth | null): Promise<JalApi> {
  if (appConfig.mode === 'mock') {
    const { createMockApi } = await import('./api/mock');
    // Default: an admin who sees the sample village. ?as=new is a fresh account (setup flow);
    // ?as=sarpanch can approve announcements.
    const { user, role } = mockIdentityFromUrl(window.location.search, sessionStore());
    return createMockApi({ latencyMs: 150, actor: 'console:secretary', role, user });
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
