/** First login: three short steps — your village, who fixes water problems, add families. */

import { useEffect, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApi } from '../api/context';
import type { CreateVillageRequest, Place, Village } from '../api/types';
import { useAsync } from '../hooks/useAsync';
import { defineMessages, msgFn } from '../lib/text';
import { MISSED_CALL, normaliseMobile } from '../lib/phones';
import { useMe, villageName } from '../shell';
import { Button, ButtonLink, Card, Field, Loading, PageTitle, useErrorText } from '../ui';
import { BulkAdd } from './BulkAdd';

const m = defineMessages({
  step: msgFn<{ n: number }>(({ n }) => `Step ${n} of 3`),
  welcome: 'Welcome to JalSakshi',
  s1: 'Your village',
  search: 'Search your village',
  searchHint: 'Type the first few letters, in English or Hindi.',
  noMatch: 'No village found with that name.',
  notListed: 'My village is not in the list',
  useList: 'Search the list instead',
  name: 'Village name',
  gp: 'Gram Panchayat',
  block: 'Block',
  district: 'District',
  homes: msgFn<{ n: number }>(({ n }) => `${n} homes (Census)`),
  next: 'Next',
  back: 'Back',
  s2: 'Who fixes water problems?',
  operator: 'Pump operator',
  operatorHint: 'Gets a call for every complaint.',
  sarpanch: 'Sarpanch (optional)',
  sarpanchHint: 'Approves announcements and gets the Monday summary.',
  personName: 'Name',
  mobile: 'Mobile number',
  badMobile: 'Enter a 10-digit mobile number.',
  save: 'Save and continue',
  s3: 'Add families',
  s3intro: msgFn<{ v: string }>(({ v }) => `${v} is set up. The daily call goes out every evening at 7 pm. Now add the families.`),
  poster: msgFn<{ num: string }>(({ num }) => `Or print the missed-call poster: families give a missed call to ${num} and join themselves.`),
  printPoster: 'Print poster',
  finish: 'Finish',
  later: 'You can add more families any time from the Families tab.',
});

type Choice = { kind: 'place'; place: Place } | { kind: 'new'; name: string; gp: string; block: string; district: string };

export function SetupPage() {
  const { reload } = useMe();
  const navigate = useNavigate();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [village, setVillage] = useState<Village | null>(null);
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [step]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="wrap topbar-inner">
          <span className="brand">JalSakshi</span>
          <span className="village-name" />
        </div>
      </header>
      <main className="wrap page">
        <div>
          <p className="progress">{m.step({ n: step })}</p>
          <div className="progress-bar" aria-hidden="true">
            <span style={{ width: `${(step / 3) * 100}%` }} />
          </div>
        </div>
        {step === 1 && (
          <VillageStep
            initial={choice}
            onNext={(c) => {
              setChoice(c);
              setStep(2);
            }}
          />
        )}
        {step === 2 && choice && (
          <TeamStep
            choice={choice}
            onBack={() => setStep(1)}
            onDone={(v) => {
              setVillage(v);
              setStep(3);
            }}
          />
        )}
        {step === 3 && village && (
          <FamiliesStep
            village={village}
            onFinish={() => {
              reload();
              navigate(`/villages/${encodeURIComponent(village.id)}`, { replace: true });
            }}
          />
        )}
      </main>
    </div>
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

export function VillageStep({ initial, onNext }: { initial: Choice | null; onNext: (c: Choice) => void }) {
  const api = useApi();
  const [q, setQ] = useState('');
  const query = useDebounced(q.trim(), 250);
  const places = useAsync(() => (query ? api.listPlaces(query) : Promise.resolve([])), `places:${query}`);
  const [picked, setPicked] = useState<Place | null>(initial?.kind === 'place' ? initial.place : null);
  const [manual, setManual] = useState(initial?.kind === 'new');
  const [form, setForm] = useState(
    initial?.kind === 'new' ? initial : { name: '', gp: '', block: '', district: '' },
  );

  const canNext = manual ? form.name.trim() && form.block.trim() && form.district.trim() : picked;

  function next(e: FormEvent) {
    e.preventDefault();
    if (manual) onNext({ kind: 'new', ...form });
    else if (picked) onNext({ kind: 'place', place: picked });
  }

  return (
    <form className="form" onSubmit={next}>
      <PageTitle title={m.s1} />
      {!manual ? (
        <>
          <Field label={m.search} hint={m.searchHint}>
            {(id) => <input id={id} value={q} autoComplete="off" onChange={(e) => setQ(e.target.value)} />}
          </Field>
          {query && places.loading && !places.data && <Loading />}
          {query && places.data && places.data.length === 0 && <p className="muted">{m.noMatch}</p>}
          {places.data && places.data.length > 0 && (
            <ul className="pick-list">
              {places.data.slice(0, 8).map((p) => (
                <li key={p.lgd_code}>
                  <button
                    type="button"
                    className="pick"
                    aria-pressed={picked?.lgd_code === p.lgd_code}
                    onClick={() => setPicked(p)}
                  >
                    <b>{villageName(p)}</b>
                    <span className="row-sub">
                      {placeLine(p)}
                      {p.census_households ? ` · ${m.homes({ n: p.census_households })}` : ''}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {picked && !places.data?.some((p) => p.lgd_code === picked.lgd_code) && (
            <p className="ok-box">
              {villageName(picked)} · {placeLine(picked)}
            </p>
          )}
          <div>
            <Button variant="link" onClick={() => setManual(true)}>
              {m.notListed}
            </Button>
          </div>
        </>
      ) : (
        <Card>
          <Field label={m.name}>
            {(id) => <input id={id} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />}
          </Field>
          <Field label={m.gp}>
            {(id) => <input id={id} value={form.gp} onChange={(e) => setForm({ ...form, gp: e.target.value })} />}
          </Field>
          <Field label={m.block}>
            {(id) => <input id={id} value={form.block} onChange={(e) => setForm({ ...form, block: e.target.value })} required />}
          </Field>
          <Field label={m.district}>
            {(id) => <input id={id} value={form.district} onChange={(e) => setForm({ ...form, district: e.target.value })} required />}
          </Field>
          <div>
            <Button variant="link" onClick={() => setManual(false)}>
              {m.useList}
            </Button>
          </div>
        </Card>
      )}
      <div className="actions">
        <Button type="submit" variant="primary" disabled={!canNext}>
          {m.next}
        </Button>
      </div>
    </form>
  );
}

export function TeamStep({ choice, onBack, onDone }: { choice: Choice; onBack: () => void; onDone: (v: Village) => void }) {
  const api = useApi();
  const errorText = useErrorText();
  const [op, setOp] = useState({ name: '', phone: '' });
  const [sar, setSar] = useState({ name: '', phone: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!normaliseMobile(op.phone) || (sar.phone.trim() && !normaliseMobile(sar.phone))) {
      setError(m.badMobile);
      return;
    }
    const where =
      choice.kind === 'place'
        ? { lgd_code: choice.place.lgd_code }
        : { name: choice.name.trim(), gram_panchayat: choice.gp.trim(), block: choice.block.trim(), district: choice.district.trim() };
    const request: CreateVillageRequest = {
      ...where,
      operator: { name: op.name.trim(), phone: op.phone.trim() },
      ...(sar.phone.trim() ? { sarpanch: { name: sar.name.trim(), phone: sar.phone.trim() } } : {}),
    };
    setBusy(true);
    setError(null);
    try {
      onDone(await api.createVillage(request));
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={(e) => void submit(e)}>
      <PageTitle title={m.s2} />
      <Card title={m.operator}>
        <p className="note">{m.operatorHint}</p>
        <Field label={m.personName}>
          {(id) => <input id={id} value={op.name} onChange={(e) => setOp({ ...op, name: e.target.value })} required />}
        </Field>
        <Field label={m.mobile}>
          {(id) => <input id={id} value={op.phone} inputMode="tel" autoComplete="off" onChange={(e) => setOp({ ...op, phone: e.target.value })} required />}
        </Field>
      </Card>
      <Card title={m.sarpanch}>
        <p className="note">{m.sarpanchHint}</p>
        <Field label={m.personName}>
          {(id) => <input id={id} value={sar.name} onChange={(e) => setSar({ ...sar, name: e.target.value })} />}
        </Field>
        <Field label={m.mobile}>
          {(id) => <input id={id} value={sar.phone} inputMode="tel" autoComplete="off" onChange={(e) => setSar({ ...sar, phone: e.target.value })} />}
        </Field>
      </Card>
      {error && <p className="warn-box" role="alert">{error}</p>}
      <div className="actions">
        <Button type="submit" variant="primary" busy={busy}>
          {m.save}
        </Button>
        <Button onClick={onBack}>{m.back}</Button>
      </div>
    </form>
  );
}

function FamiliesStep({ village, onFinish }: { village: Village; onFinish: () => void }) {
  return (
    <div className="form">
      <PageTitle title={m.s3} />
      <p>{m.s3intro({ v: villageName(village) })}</p>
      <Card>
        <BulkAdd vid={village.id} />
      </Card>
      <Card footer={<ButtonLink to={`/villages/${encodeURIComponent(village.id)}/poster`}>{m.printPoster}</ButtonLink>}>
        <p>{m.poster({ num: MISSED_CALL })}</p>
      </Card>
      <div className="actions">
        <Button variant="primary" onClick={onFinish}>
          {m.finish}
        </Button>
      </div>
      <p className="note">{m.later}</p>
    </div>
  );
}
