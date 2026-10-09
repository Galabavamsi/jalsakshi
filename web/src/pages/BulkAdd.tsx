/**
 * Add families three ways: paste numbers, a photo of a register (read by AI, checked by a
 * person), or let families give a missed call themselves. Every family first gets one short
 * consent call; nobody is called daily before they agree.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useApi } from '../api/context';
import type { BulkAddResponse, FamilyRow, RegisterRow } from '../api/types';
import { photoToJpegBase64 } from '../lib/image';
import { MISSED_CALL, normaliseMobile, parsePhoneList, shortMasked } from '../lib/phones';
import { defineMessages, msgFn } from '../lib/text';
import { Button, Field, Note, useErrorText } from '../ui';

const m = defineMessages({
  paste: 'Paste numbers',
  photo: 'Photo of a register',
  missed: 'Missed call',
  label: 'Paste mobile numbers, one per line',
  explain: 'Each family gets a short call asking if they agree. They press 1 to join.',
  found: msgFn<{ n: number; bad: number }>(
    ({ n, bad }) =>
      `${n} ${n === 1 ? 'number' : 'numbers'} found${bad ? ` · ${bad} ${bad === 1 ? 'line is' : 'lines are'} not a mobile number` : ''}`,
  ),
  add: 'Add families',
  addN: msgFn<{ n: number }>(({ n }) => `Add ${n} ${n === 1 ? 'family' : 'families'}`),
  added: msgFn<{ n: number }>(
    ({ n }) => `Added ${n} ${n === 1 ? 'family' : 'families'}. Each gets a short call now asking if they agree.`,
  ),
  skipped: 'Not added',
  photoIntro:
    'Take a clear photo of a page of the register (names, mobile numbers, mohalla). JalSakshi reads it; you check every row before anything is added.',
  pick: 'Take or choose a photo',
  reading: 'Reading the photo…',
  another: 'Use another photo',
  include: 'Add',
  name: 'Name',
  mobile: 'Mobile',
  area: 'Area (mohalla)',
  badNumber: 'Not a mobile number. Fix it or leave it out.',
  noRows: 'No names or numbers were found in this photo. Try a sharper photo in good light.',
  missedIntro: 'Families can join on their own, without anyone typing their number:',
  missed1: 'They give a missed call to',
  missed2: 'JalSakshi calls them back and asks if they agree to a daily call. They press 1.',
  missed3: 'They say their name and their mohalla. It is filled in here automatically.',
  missedNote: 'New families appear in this list after their first call.',
  poster: 'Print the poster with this number',
});

/** The API's reason, without the consent code it appends ("already added (GRANTED)"). */
export function whyText(why: string): string {
  return why.startsWith('already added') ? 'already added' : why;
}

/** A row read from the photo, as the person reviews it. Rows with a bad number start unticked. */
export interface ReviewRow {
  name: string;
  phone: string;
  area: string;
  include: boolean;
}

export function toReview(rows: RegisterRow[]): ReviewRow[] {
  return rows.map((r) => ({
    name: r.name ?? '',
    phone: r.phone,
    area: r.area ?? '',
    include: r.phone_ok && normaliseMobile(r.phone) !== null,
  }));
}

/** Only ticked rows with a real mobile number are sent. */
export function reviewToFamilies(rows: ReviewRow[]): FamilyRow[] {
  return rows
    .filter((r) => r.include && normaliseMobile(r.phone) !== null)
    .map((r) => ({ phone: r.phone.trim(), name: r.name.trim() || null, area: r.area.trim() || null }));
}

type Tab = 'paste' | 'photo' | 'missed';

export function BulkAdd({ vid, onAdded }: { vid: string; onAdded?: (result: BulkAddResponse) => void }) {
  const [tab, setTab] = useState<Tab>('paste');
  const tabs: Array<[Tab, string]> = [
    ['paste', m.paste],
    ['photo', m.photo],
    ['missed', m.missed],
  ];
  return (
    <div className="form">
      <div className="seg seg-wrap" role="group" aria-label={m.add}>
        {tabs.map(([key, label]) => (
          <button key={key} type="button" aria-pressed={tab === key} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'paste' && <PasteNumbers vid={vid} onAdded={onAdded} />}
      {tab === 'photo' && <RegisterPhoto vid={vid} onAdded={onAdded} />}
      {tab === 'missed' && <MissedCall vid={vid} />}
    </div>
  );
}

function AddResult({ result }: { result: BulkAddResponse }) {
  return (
    <div role="status" className="form">
      {result.added.length > 0 && <p className="ok-box">{m.added({ n: result.added.length })}</p>}
      {result.skipped.length > 0 && (
        <div>
          <b>{m.skipped}</b>
          <ul className="rows">
            {result.skipped.map((s, i) => (
              <li key={i} className="row">
                <span>{s.input.includes('X') ? shortMasked(s.input) : s.input}</span>
                <span className="row-end">{whyText(s.why)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function PasteNumbers({ vid, onAdded }: { vid: string; onAdded?: (result: BulkAddResponse) => void }) {
  const api = useApi();
  const errorText = useErrorText();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<BulkAddResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const parsed = parsePhoneList(text);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const lines = text.split(/[\n,;]+/).map((s) => s.trim()).filter(Boolean);
      const res = await api.addHouseholdsBulk(vid, lines);
      setResult(res);
      setText('');
      onAdded?.(res);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <Field label={m.label} hint={m.explain}>
        {(id) => (
          <textarea
            id={id}
            value={text}
            inputMode="tel"
            placeholder={'98765 43210\n91234 56789'}
            onChange={(e) => setText(e.target.value)}
          />
        )}
      </Field>
      {text.trim() && <p className="muted">{m.found({ n: parsed.valid.length, bad: parsed.invalid.length })}</p>}
      <div className="actions">
        <Button variant="primary" busy={busy} disabled={!text.trim()} onClick={() => void submit()}>
          {m.add}
        </Button>
      </div>
      {error && <p className="warn-box" role="alert">{error}</p>}
      {result && <AddResult result={result} />}
    </div>
  );
}

export function RegisterPhoto({ vid, onAdded }: { vid: string; onAdded?: (result: BulkAddResponse) => void }) {
  const api = useApi();
  const errorText = useErrorText();
  const [busy, setBusy] = useState<'read' | 'add' | null>(null);
  const [rows, setRows] = useState<ReviewRow[] | null>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BulkAddResponse | null>(null);
  const families = rows ? reviewToFamilies(rows) : [];

  async function read(file: File | undefined) {
    if (!file) return;
    setBusy('read');
    setError(null);
    setResult(null);
    setRows(null);
    try {
      const image = await photoToJpegBase64(file);
      const res = await api.readRegisterPhoto(vid, image, 'image/jpeg');
      setRows(toReview(res.rows));
      setNote(res.note);
    } catch (err) {
      setError(err instanceof Error && !('status' in err) ? err.message : errorText(err));
    } finally {
      setBusy(null);
    }
  }

  function edit(i: number, patch: Partial<ReviewRow>) {
    setRows((cur) => cur && cur.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  }

  async function add() {
    setBusy('add');
    setError(null);
    try {
      const res = await api.addFamilies(vid, families);
      setResult(res);
      setRows(null);
      onAdded?.(res);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="form">
      {!rows && (
        <>
          <p className="muted">{m.photoIntro}</p>
          <label className={`btn btn-primary file-btn${busy === 'read' ? ' is-busy' : ''}`}>
            {busy === 'read' ? m.reading : m.pick}
            <input
              type="file"
              accept="image/*"
              disabled={busy !== null}
              onChange={(e) => {
                void read(e.target.files?.[0]);
                e.target.value = '';
              }}
            />
          </label>
        </>
      )}
      {rows && rows.length === 0 && <p className="warn-box">{m.noRows}</p>}
      {rows && rows.length > 0 && (
        <>
          <ul className="review" aria-label={m.photo}>
            {rows.map((r, i) => {
              const bad = normaliseMobile(r.phone) === null;
              return (
                <li key={i} className={r.include ? '' : 'is-off'}>
                  <label className="check">
                    <input type="checkbox" checked={r.include} onChange={(e) => edit(i, { include: e.target.checked })} />
                    {m.include}
                  </label>
                  <label>
                    <span>{m.name}</span>
                    <input value={r.name} onChange={(e) => edit(i, { name: e.target.value })} />
                  </label>
                  <label>
                    <span>{m.mobile}</span>
                    <input inputMode="tel" value={r.phone} aria-invalid={bad || undefined} onChange={(e) => edit(i, { phone: e.target.value })} />
                  </label>
                  <label>
                    <span>{m.area}</span>
                    <input value={r.area} onChange={(e) => edit(i, { area: e.target.value })} />
                  </label>
                  {bad && <p className="row-warn">{m.badNumber}</p>}
                </li>
              );
            })}
          </ul>
          <Note>{note}</Note>
          <div className="actions">
            <Button variant="primary" busy={busy === 'add'} disabled={families.length === 0} onClick={() => void add()}>
              {m.addN({ n: families.length })}
            </Button>
            <Button onClick={() => setRows(null)}>{m.another}</Button>
          </div>
        </>
      )}
      {rows?.length === 0 && <Button onClick={() => setRows(null)}>{m.another}</Button>}
      {error && <p className="warn-box" role="alert">{error}</p>}
      {result && <AddResult result={result} />}
    </div>
  );
}

function MissedCall({ vid }: { vid: string }) {
  return (
    <div className="form">
      <p>{m.missedIntro}</p>
      <ol className="steps">
        <li>
          {m.missed1} <b className="nowrap">{MISSED_CALL}</b>.
        </li>
        <li>{m.missed2}</li>
        <li>{m.missed3}</li>
      </ol>
      <Note>{m.missedNote}</Note>
      <div>
        <Link className="btn" to={`/villages/${encodeURIComponent(vid)}/poster`}>
          {m.poster}
        </Link>
      </div>
    </div>
  );
}
