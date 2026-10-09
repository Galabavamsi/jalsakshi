// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { App } from '../src/App';
import { createMockApi, type MockUser } from '../src/api/mock';
import { ApiProvider } from '../src/api/context';
import { AuthProvider } from '../src/auth/AuthContext';
import { SignInScreen } from '../src/shell';

beforeAll(() => {
  window.scrollTo = () => {}; // jsdom does not implement it
});

const NOW = new Date();

function renderApp(path: string, user: MockUser = 'admin') {
  const api = createMockApi({ now: () => NOW, user });
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider auth={null}>
        <ApiProvider api={api}>
          <App auth={null} />
        </ApiProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
  return api;
}

afterEach(cleanup);

describe('Home', () => {
  it('opens the sample village with a summary and a quiet sample banner', async () => {
    renderApp('/');
    expect(await screen.findByText("Today's water")).toBeTruthy();
    expect(screen.getByText(/Sample village — example data/)).toBeTruthy();
    expect(screen.getByText('What to do now')).toBeTruthy();
    expect(screen.getByText('Closed this week')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Call families now' })).toBeTruthy();
    // Four text tabs, no sidebar.
    for (const tab of ['Home', 'Complaints', 'Families', 'More']) {
      expect(screen.getByRole('link', { name: tab })).toBeTruthy();
    }
    expect(document.querySelector('svg')).toBeNull();
  });

  it('explains the call before calling families', async () => {
    renderApp('/');
    fireEvent.click(await screen.findByRole('button', { name: 'Call families now' }));
    expect(screen.getByRole('dialog').textContent).toMatch(/one short call/);
  });
});

describe('First login', () => {
  it('walks a new Panchayat through village, team and families', async () => {
    const api = renderApp('/', 'new');
    expect(await screen.findByText('Step 1 of 3')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Search your village'), { target: { value: 'Sel' } });
    fireEvent.click(await screen.findByRole('button', { name: /Selud/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    expect(await screen.findByText('Step 2 of 3')).toBeTruthy();
    const names = screen.getAllByLabelText('Name');
    const mobiles = screen.getAllByLabelText('Mobile number');
    fireEvent.change(names[0] as HTMLElement, { target: { value: 'Ramesh' } });
    fireEvent.change(mobiles[0] as HTMLElement, { target: { value: '98765 43210' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save and continue' }));

    expect(await screen.findByText('Step 3 of 3')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Paste mobile numbers, one per line'), {
      target: { value: '91234 56789\nnot a number\n90000 11111' },
    });
    expect(screen.getByText(/2 numbers found · 1 line is not a mobile number/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Add families' }));
    expect(await screen.findByText(/Added 2 families/)).toBeTruthy();
    expect(screen.getByText(/080 6426 0325/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
    expect(await screen.findByText('Getting started')).toBeTruthy();
    await waitFor(async () => expect((await api.getMe()).needs_setup).toBe(false));
  });
});

describe('Complaints', () => {
  it('refuses to close a complaint until families confirm, in one plain sentence', async () => {
    const api = createMockApi({ now: () => NOW });
    const open = (await api.listTickets({ village_id: 'sample-village' })).find((t) => t.state !== 'CLOSED_VERIFIED');
    expect(open).toBeTruthy();
    cleanup();
    renderApp(`/villages/sample-village/complaints/${open?.id ?? ''}`);
    fireEvent.click(await screen.findByRole('button', { name: 'Close complaint' }));
    expect(await screen.findByText('Not closed yet:')).toBeTruthy();
  });
});

const DEVANAGARI = /[\u0900-\u097F]/;

describe('English only', () => {
  it('has no language switch and no Hindi in the console chrome', async () => {
    renderApp('/');
    await screen.findByText("Today's water");
    expect(screen.queryByRole('button', { name: 'हिन्दी' })).toBeNull();
    expect(screen.queryByRole('group', { name: /Language/ })).toBeNull();
    expect(DEVANAGARI.test(document.querySelector('header')?.textContent ?? '')).toBe(false);
    expect(DEVANAGARI.test(document.querySelector('nav')?.textContent ?? '')).toBe(false);
  });

  it('sign-in offers only Sign in; the team gives logins', () => {
    render(
      <AuthProvider auth={null}>
        <SignInScreen />
      </AuthProvider>,
    );
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Create account' })).toBeNull();
    expect(screen.getByText('Your login is given by the JalSakshi team.')).toBeTruthy();
  });
});

describe('Set up a Panchayat (team only)', () => {
  it('creates a login and shows the temporary password', async () => {
    renderApp('/villages/sample-village/more/new-panchayat');
    fireEvent.change(await screen.findByLabelText('Search the village list'), { target: { value: 'Kop' } });
    fireEvent.click(await screen.findByRole('button', { name: /Kopedih/ }));
    await screen.findByText(/Chhattisgarhi/);
    fireEvent.click(screen.getByRole('button', { name: 'Create Panchayat' }));
    expect(await screen.findByText(/pump operator.s 10-digit mobile/)).toBeTruthy();
    const mobiles = screen.getAllByLabelText('Mobile number');
    fireEvent.change(mobiles[0] as HTMLElement, { target: { value: '98765 43210' } });
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'kopedih-gp' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create Panchayat' }));
    expect(await screen.findByText('Panchayat created')).toBeTruthy();
    expect(screen.getByText('kopedih-gp')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Copy login details' })).toBeTruthy();
  });
});

describe('How JalSakshi works (/how)', () => {
  it('names each step and the AWS service behind it, without a login', async () => {
    renderApp('/how');
    expect(await screen.findByRole('heading', { name: 'How JalSakshi works' })).toBeTruthy();
    expect(screen.getAllByText(/AWS Step Functions/).length).toBeGreaterThan(0);
    expect(screen.getByText('Amazon Bedrock')).toBeTruthy();
    expect(screen.getByText(/never by AI/)).toBeTruthy();
  });
});
