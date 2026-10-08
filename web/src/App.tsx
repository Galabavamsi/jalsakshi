import type { ReactNode } from 'react';
import { Route, Routes } from 'react-router-dom';
import { appConfig } from './appConfig';
import { useAuth } from './auth/AuthContext';
import type { CognitoAuth } from './auth/cognito';
import { Layout } from './components/Layout';
import { callbackPath } from './config';
import { ActivityPage } from './pages/ActivityPage';
import { AuthCallback, NotFound, SignInScreen, Splash } from './pages/AuthScreens';
import { BriefPage } from './pages/BriefPage';
import { SimulatorPage } from './pages/SimulatorPage';
import { TicketPage } from './pages/TicketPage';
import { VillageDetailPage } from './pages/VillageDetailPage';
import { VillagesPage } from './pages/VillagesPage';

function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  if (status === 'loading') return <Splash />;
  if (status === 'signed_out') return <SignInScreen />;
  return children;
}

/** Routes. Everything except the OAuth callback needs a session (skipped in mock mode). */
export function App({ auth }: { auth: CognitoAuth | null }) {
  return (
    <Routes>
      <Route path={callbackPath(appConfig)} element={<AuthCallback auth={auth} />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<VillagesPage />} />
        <Route path="villages/:vid" element={<VillageDetailPage />} />
        <Route path="villages/:vid/brief" element={<BriefPage />} />
        <Route path="tickets/:tid" element={<TicketPage />} />
        <Route path="simulator" element={<SimulatorPage />} />
        <Route path="activity" element={<ActivityPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
