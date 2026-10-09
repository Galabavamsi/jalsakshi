/**
 * Team-only "Set up a Panchayat" (one login, its village, call languages and team in one form)
 * and the village's own Settings (call languages, daily call time).
 */

import { useEffect, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { useApi } from '../api/context';
import type { CallLanguage, CreatePanchayatRequest, CreatePanchayatResponse, Place } from '../api/types';
import { useAsync } from '../hooks/useAsync';
import { normaliseMobile } from '../lib/phones';
import { defineMessages } from '../lib/text';
import { useMe, useVillage } from '../shell';
import { Button, Card, ErrorBox, Field, Loading, Note, PageTitle, useErrorText } from '../ui';

const m = defineMessages({
  back: '← More',
  title: 'Set up a Panchayat',
  intro: 'Creates the Panchayat’s login, its village, the call languages and the team in one go.',
  onlyTeam: 'Only the JalSakshi team can set up a Panchayat.',
  village: 'Village',
  search: 'Search the village list',
  searchHint: 'Type a few letters of the village name.',
  noMatch: 'No village with that name in the list.',
  notListed: 'Not in the list? Type it in',
  useList: 'Search the list instead',
  name: 'Village name',
  gp: 'Gram Panchayat',
  block: 'Block',
  district: 'District',
  languages: 'Call languages',
  languagesHint: 'The first one is the default. Families can choose their language on their first call.',
  ready: 'Ready',
  notReady: 'Needs recordings and translation',
  isDefault: 'Default',
  makeDefault: 'Make default',
  operator: 'Pump operator',
  sarpanch: 'Sarpanch (optional)',
  secretary: 'Secretary (optional)',
  personName: 'Name',
  mobile: 'Mobile number',
  login: 'Login',
  username: 'Username',
  usernameHint: '3 to 30 small letters, digits, dot, dash or underscore. For example: kharkhara-gp',
  password: 'Temporary password (optional)',
  passwordHint: 'Leave empty to generate one. They change it at first sign-in.',
  create: 'Create Panchayat',
  done: 'Panchayat created',
  user: 'Username',
  temp: 'Temporary password',
  copy: 'Copy login details',
  copied: 'Copied',
  openVillage: 'Open the village',
  another: 'Set up another',
  allVillages: 'All villages',
  settings: 'Settings',
  settingsIntro: 'Choose the languages JalSakshi calls this village in and when the daily call goes.',
  time: 'Daily call time',
  timeHint: 'The daily call goes to every family at this time.',
  save: 'Save',
  saved: 'Saved.',
});

// ------------------------------------------------------------------ the form, as pure data

export interface PanchayatForm {
  place: Place | null;
  manual: boolean;
  name: string;
  gp: string;
  block: string;
  district: string;
  languages: string[];
  operatorName: string;
  operatorPhone: string;
  sarpanchName: string;
  sarpanchPhone: string;
  secretaryName: string;
  secretaryPhone: string;
  username: string;
  password: string;
}

export const EMPTY_FORM: PanchayatForm = {
  place: null,
  manual: false,
  name: '',
  gp: '',
  block: '',
  district: '',
  languages: ['hi'],
  operatorName: '',
  operatorPhone: '',
  sarpanchName: '',
  sarpanchPhone: '',
  secretaryName: '',
  secretaryPhone: '',
  username: '',
  password: '',
};

/** Plain-English problems with the form; empty when it can be sent. */
export function validatePanchayat(f: PanchayatForm): string[] {
  const errors: string[] = [];
  if (f.manual) {
    if (!f.name.trim() || !f.block.trim() || !f.district.trim()) errors.push('Enter the village name, block and district.');
  } else if (!f.place) {
    errors.push('Choose the village from the list, or type it in.');
  }
  if (f.languages.length === 0) errors.push('Choose at least one call language.');
  if (!normaliseMobile(f.operatorPhone)) errors.push('Enter the pump operator’s 10-digit mobile number.');
  for (const [label, name, phone] of [
    ['sarpanch', f.sarpanchName, f.sarpanchPhone],
    ['secretary', f.secretaryName, f.secretaryPhone],
  ] as const) {
    if ((name.trim() || phone.trim()) && !normaliseMobile(phone)) errors.push(`Enter the ${label}’s 10-digit mobile number, or leave both empty.`);
  }
  if (!/^[a-z0-9._-]{3,30}$/.test(f.username.trim().toLowerCase())) {
    errors.push('Username: 3 to 30 small letters, digits, dot, dash or underscore.');
  }
  if (f.password && !(f.password.length >= 8 && /[a-z]/.test(f.password) && /[A-Z]/.test(f.password) && /\d/.test(f.password))) {
    errors.push('Password: at least 8 characters with a capital letter, a small letter and a number.');
  }
  return errors;
}

export function toPanchayatRequest(f: PanchayatForm): CreatePanchayatRequest {
  const person = (name: string, phone: string) => (phone.trim() ? { name: name.trim(), phone: phone.trim() } : undefined);
  return {
    username: f.username.trim().toLowerCase(),
    ...(f.password ? { temporary_password: f.password } : {}),
    village:
      f.manual || !f.place
        ? { name: f.name.trim(), gram_panchayat: f.gp.trim() || undefined, block: f.block.trim(), district: f.district.trim() }
        : { lgd_code: f.place.lgd_code },
    languages: f.languages,
    operator: { name: f.operatorName.trim(), phone: f.operatorPhone.trim() },
    sarpanch: person(f.sarpanchName, f.sarpanchPhone),
    secretary: person(f.secretaryName, f.secretaryPhone),
  };
}

// ------------------------------------------------------------------ call languages

export function LanguagePicker({
  options,
  value,
  onChange,
}: {
  options: CallLanguage[];
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const toggle = (code: string, on: boolean) => onChange(on ? [...value, code] : value.filter((c) => c !== code));
  const makeDefault = (code: string) => onChange([code, ...value.filter((c) => c !== code)]);
  return (
    <ul className="checks">
      {options.map((l) => {
        const on = value.includes(l.code);
        return (
          <li key={l.code}>
            <label className="check">
              <input type="checkbox" checked={on} onChange={(e) => toggle(l.code, e.target.checked)} />
              <span>
                {l.name}
                <span className="row-sub"> · {l.ready ? m.ready : m.notReady}</span>
              </span>
            </label>
            {on && value[0] === l.code && <span className="tag">{m.isDefault}</span>}
            {on && value[0] !== l.code && (
              <Button variant="link" onClick={() => makeDefault(l.code)}>
                {m.makeDefault}
              </Button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function BackToMore() {
  const { vid } = useVillage();
  return (
    <Link className="back" to={`/villages/${encodeURIComponent(vid)}/more`}>
      {m.back}
    </Link>
  );
}

function useDebounced(value: string, ms: number): string {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

function placeLine(p: Place): string {
  return [p.gram_panchayat, p.block, p.district].filter(Boolean).join(' · ');
}

// ------------------------------------------------------------------ Set up a Panchayat

export function SetupPanchayatPage() {
  const { me } = useMe();
  const api = useApi();
  const errorText = useErrorText();
  const { vid } = useVillage();
  const langs = useAsync(() => api.listLanguages(), 'languages');
  const [f, setF] = useState<PanchayatForm>(EMPTY_FORM);
  const [q, setQ] = useState('');
  const query = useDebounced(q.trim(), 250);
  const places = useAsync(() => (query ? api.listPlaces(query) : Promise.resolve([])), `places:${query}`);
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<CreatePanchayatResponse | null>(null);
  const set = (patch: Partial<PanchayatForm>) => setF((cur) => ({ ...cur, ...patch }));

  if (!me.is_admin) {
    return (
      <div className="page">
        <BackToMore />
        <p className="warn-box">{m.onlyTeam}</p>
      </div>
    );
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const problems = validatePanchayat(f);
    setErrors(problems);
    if (problems.length) return;
    setBusy(true);
    try {
      setDone(await api.createPanchayat(toPanchayatRequest(f)));
    } catch (err) {
      setErrors([errorText(err)]);
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="page">
        <BackToMore />
        <PageTitle title={m.done} />
        <CreatedLogin done={done} />
        <div className="actions">
          <Link className="btn btn-primary" to={`/villages/${encodeURIComponent(done.village.id)}`}>
            {m.openVillage}
          </Link>
          <Button
            onClick={() => {
              setDone(null);
              setF(EMPTY_FORM);
              setQ('');
            }}
          >
            {m.another}
          </Button>
          <Link className="btn" to={`/villages/${encodeURIComponent(vid)}/more/villages`}>
            {m.allVillages}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <form className="page" onSubmit={(e) => void submit(e)} noValidate>
      <BackToMore />
      <PageTitle title={m.title} />
      <p className="muted">{m.intro}</p>

      <Card title={m.village}>
        {!f.manual ? (
          <>
            <Field label={m.search} hint={m.searchHint}>
              {(id) => <input id={id} value={q} autoComplete="off" onChange={(e) => setQ(e.target.value)} />}
            </Field>
            {query && places.data && places.data.length === 0 && <p className="muted">{m.noMatch}</p>}
            {places.data && places.data.length > 0 && (
              <ul className="pick-list">
                {places.data.slice(0, 6).map((p) => (
                  <li key={p.lgd_code}>
                    <button type="button" className="pick" aria-pressed={f.place?.lgd_code === p.lgd_code} onClick={() => set({ place: p })}>
                      <b>{p.name}</b>
                      <span className="row-sub">{placeLine(p)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {f.place && !places.data?.some((p) => p.lgd_code === f.place?.lgd_code) && (
              <p className="ok-box">
                {f.place.name} · {placeLine(f.place)}
              </p>
            )}
            <div>
              <Button variant="link" onClick={() => set({ manual: true })}>
                {m.notListed}
              </Button>
            </div>
          </>
        ) : (
          <>
            <Field label={m.name}>{(id) => <input id={id} value={f.name} onChange={(e) => set({ name: e.target.value })} />}</Field>
            <Field label={m.gp}>{(id) => <input id={id} value={f.gp} onChange={(e) => set({ gp: e.target.value })} />}</Field>
            <Field label={m.block}>{(id) => <input id={id} value={f.block} onChange={(e) => set({ block: e.target.value })} />}</Field>
            <Field label={m.district}>{(id) => <input id={id} value={f.district} onChange={(e) => set({ district: e.target.value })} />}</Field>
            <div>
              <Button variant="link" onClick={() => set({ manual: false })}>
                {m.useList}
              </Button>
            </div>
          </>
        )}
      </Card>

      <Card title={m.languages}>
        <Note>{m.languagesHint}</Note>
        {langs.error && !langs.data ? (
          <ErrorBox error={langs.error} onRetry={langs.reload} />
        ) : !langs.data ? (
          <Loading />
        ) : (
          <LanguagePicker options={langs.data} value={f.languages} onChange={(languages) => set({ languages })} />
        )}
      </Card>

      {(
        [
          [m.operator, 'operatorName', 'operatorPhone'],
          [m.sarpanch, 'sarpanchName', 'sarpanchPhone'],
          [m.secretary, 'secretaryName', 'secretaryPhone'],
        ] as const
      ).map(([title, nameKey, phoneKey]) => (
        <Card key={nameKey} title={title}>
          <div className="pair">
            <Field label={m.personName}>{(id) => <input id={id} value={f[nameKey]} onChange={(e) => set({ [nameKey]: e.target.value })} />}</Field>
            <Field label={m.mobile}>
              {(id) => <input id={id} inputMode="tel" value={f[phoneKey]} onChange={(e) => set({ [phoneKey]: e.target.value })} />}
            </Field>
          </div>
        </Card>
      ))}

      <Card title={m.login}>
        <Field label={m.username} hint={m.usernameHint}>
          {(id) => <input id={id} value={f.username} autoCapitalize="none" autoComplete="off" onChange={(e) => set({ username: e.target.value })} />}
        </Field>
        <Field label={m.password} hint={m.passwordHint}>
          {(id) => <input id={id} value={f.password} autoComplete="new-password" onChange={(e) => set({ password: e.target.value })} />}
        </Field>
      </Card>

      {errors.length > 0 && (
        <ul className="warn-box errors" role="alert">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      <div className="actions">
        <Button type="submit" variant="primary" busy={busy}>
          {m.create}
        </Button>
      </div>
    </form>
  );
}

function CreatedLogin({ done }: { done: CreatePanchayatResponse }) {
  const [copied, setCopied] = useState(false);
  const text = `JalSakshi console: ${window.location.origin}\nUsername: ${done.username}\nTemporary password: ${done.temporary_password}`;
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }
  return (
    <Card>
      <p className="ok-box">
        {done.village.name} · {done.village.district}
      </p>
      <ul className="rows">
        <li className="row">
          <span className="muted">{m.user}</span>
          <b className="secret">{done.username}</b>
        </li>
        <li className="row">
          <span className="muted">{m.temp}</span>
          <b className="secret">{done.temporary_password}</b>
        </li>
      </ul>
      <div className="actions">
        <Button onClick={() => void copy()}>{copied ? m.copied : m.copy}</Button>
      </div>
      <Note>{done.note}</Note>
    </Card>
  );
}

// ------------------------------------------------------------------ village settings

export function VillageSettingsPage() {
  const api = useApi();
  const errorText = useErrorText();
  const { vid, detail, reload } = useVillage();
  const langs = useAsync(() => api.listLanguages(), 'languages');
  const [languages, setLanguages] = useState<string[]>(detail.village.languages?.length ? detail.village.languages : ['hi']);
  const [time, setTime] = useState(detail.village.checkin_local_time);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (languages.length === 0) {
      setMsg({ ok: false, text: 'Choose at least one call language.' });
      return;
    }
    if (!/^\d{2}:\d{2}$/.test(time)) {
      setMsg({ ok: false, text: 'Choose a time for the daily call.' });
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      await api.saveVillageSettings(vid, { languages, checkin_local_time: time });
      setMsg({ ok: true, text: m.saved });
      reload();
    } catch (err) {
      setMsg({ ok: false, text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="page" onSubmit={(e) => void save(e)}>
      <BackToMore />
      <PageTitle title={m.settings} />
      <p className="muted">{m.settingsIntro}</p>
      <Card title={m.languages}>
        <Note>{m.languagesHint}</Note>
        {langs.error && !langs.data ? (
          <ErrorBox error={langs.error} onRetry={langs.reload} />
        ) : !langs.data ? (
          <Loading />
        ) : (
          <LanguagePicker options={langs.data} value={languages} onChange={setLanguages} />
        )}
      </Card>
      <Card title={m.time}>
        <Field label={m.time} hint={m.timeHint}>
          {(id) => <input id={id} type="time" value={time} onChange={(e) => setTime(e.target.value)} />}
        </Field>
      </Card>
      {msg && (
        <p className={msg.ok ? 'ok-box' : 'warn-box'} role={msg.ok ? 'status' : 'alert'}>
          {msg.text}
        </p>
      )}
      <div className="actions">
        <Button type="submit" variant="primary" busy={busy}>
          {m.save}
        </Button>
      </div>
    </form>
  );
}
