import { lazy, Suspense, type ComponentType, type LazyExoticComponent } from 'react';
import { Route, Routes } from 'react-router-dom';
import { appConfig } from './appConfig';
import type { CognitoAuth } from './auth/cognito';
import { callbackPath } from './config';
import { ComplaintsPage } from './pages/Complaints';
import { FamiliesPage } from './pages/Families';
import { HomePage } from './pages/Home';
import { AuthCallback, NotFound, RequireAuth, RootRedirect, VillageLayout } from './shell';
import { Loading } from './ui';

function page<M>(load: () => Promise<M>, name: keyof M): LazyExoticComponent<ComponentType> {
  return lazy(async () => ({ default: (await load())[name] as ComponentType }));
}

const detail = () => import('./pages/ComplaintDetail');
const ComplaintDetailPage = page(detail, 'ComplaintDetailPage');
const RaiseComplaintPage = page(detail, 'RaiseComplaintPage');
const more = () => import('./pages/More');
const MorePage = page(more, 'MorePage');
const SourcesPage = page(more, 'SourcesPage');
const TeamPage = page(more, 'TeamPage');
const HelpPage = page(more, 'HelpPage');
const AllVillagesPage = page(more, 'AllVillagesPage');
const admin = () => import('./pages/Admin');
const SetupPanchayatPage = page(admin, 'SetupPanchayatPage');
const VillageSettingsPage = page(admin, 'VillageSettingsPage');
const AnnouncementsPage = page(() => import('./pages/Announcements'), 'AnnouncementsPage');
const reports = () => import('./pages/Reports');
const ReportsPage = page(reports, 'ReportsPage');
const GramSabhaSheet = page(reports, 'GramSabhaSheet');
const PosterPage = page(() => import('./pages/Poster'), 'PosterPage');
const TestCallPage = page(() => import('./pages/TestCall'), 'TestCallPage');
const SetupPage = page(() => import('./pages/Setup'), 'SetupPage');
const PublicPage = page(() => import('./pages/Public'), 'PublicPage');

/**
 * Routes (DESIGN.md §0, v4). Everything except the OAuth callback and the residents' page
 * (/v/:villageId) needs a session (skipped in mock mode).
 */
export function App({ auth }: { auth: CognitoAuth | null }) {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path={callbackPath(appConfig)} element={<AuthCallback auth={auth} />} />
        <Route path="v/:villageId" element={<PublicPage />} />
        <Route element={<RequireAuth />}>
          <Route index element={<RootRedirect />} />
          <Route path="setup" element={<SetupPage />} />
          <Route path="villages/:vid/poster" element={<PosterPage />} />
          <Route path="villages/:vid/gram-sabha-sheet" element={<GramSabhaSheet />} />
          <Route path="villages/:vid" element={<VillageLayout />}>
            <Route index element={<HomePage />} />
            <Route path="complaints" element={<ComplaintsPage />} />
            <Route path="complaints/new" element={<RaiseComplaintPage />} />
            <Route path="complaints/:tid" element={<ComplaintDetailPage />} />
            <Route path="families" element={<FamiliesPage />} />
            <Route path="more" element={<MorePage />} />
            <Route path="more/sources" element={<SourcesPage />} />
            <Route path="more/team" element={<TeamPage />} />
            <Route path="more/announcements" element={<AnnouncementsPage />} />
            <Route path="more/reports" element={<ReportsPage />} />
            <Route path="more/help" element={<HelpPage />} />
            <Route path="more/villages" element={<AllVillagesPage />} />
            <Route path="more/test-call" element={<TestCallPage />} />
            <Route path="more/settings" element={<VillageSettingsPage />} />
            <Route path="more/new-panchayat" element={<SetupPanchayatPage />} />
            <Route path="*" element={<NotFound />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
