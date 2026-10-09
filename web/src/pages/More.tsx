/** More: a plain list, plus water sources, team, help and (admins) all villages. */

import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { useApi } from '../api/context';
import { WATER_POINT_KINDS, type Operator, type TeamRole, type WaterPointKind } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { useAsync } from '../hooks/useAsync';
import { defineMessages } from '../lib/text';
import { WATER_POINT_KIND } from '../lib/labels';
import { MISSED_CALL, normaliseMobile, shortMasked } from '../lib/phones';
import { WATER_WORD } from '../lib/summary';
import { useMe, useVillage, villageName } from '../shell';
import { Button, Card, ErrorBox, Field, Loading, Note, PageTitle, useErrorText } from '../ui';

const m = defineMessages({
  title: 'More',
  back: '← More',
  sources: 'Water sources',
  team: 'Team',
  announcements: 'Announcements',
  reports: 'Reports',
  poster: 'Missed-call poster',
  residents: "Residents' page",
  help: 'Help',
  how: 'How JalSakshi works',
  howSub: 'Each step and the AWS service behind it',
  signOut: 'Sign out',
  admin: 'Admin',
  allVillages: 'All villages',
  sourcesSub: 'Taps, handpumps, borewells',
  teamSub: 'Pump operator, sarpanch, secretary',
  annSub: 'Write → sarpanch approves → send (2 a week)',
  reportsSub: 'Weekly summary and Gram Sabha sheet',
  posterSub: 'Print and put up in the village',
  residentsSub: 'Public page, no login needed',
  // sources
  noSources: 'No water sources yet. Add the tap supply, handpumps or borewells families use.',
  addSource: 'Add a water source',
  name: 'Name',
  kind: 'Type',
  hamlet: 'Hamlet / mohalla (optional)',
  save: 'Save',
  saved: 'Saved.',
  sourcesNote: 'Families are asked about the source they use. Complaints are tracked per source.',
  // team
  operator: 'Pump operator',
  operatorSub: 'Gets a call for every complaint',
  sarpanch: 'Sarpanch',
  sarpanchSub: 'Approves announcements, gets the Monday summary',
  secretary: 'Secretary',
  secretarySub: 'Runs JalSakshi for the Panchayat',
  notSet: 'Not added yet',
  change: 'Change',
  add: 'Add',
  mobile: 'Mobile number',
  badMobile: 'Enter a 10-digit mobile number.',
  cancel: 'Cancel',
  teamNote: 'Numbers are hidden except the last four digits.',
  // all villages
  settings: 'Settings',
  settingsSub: 'Call languages and daily call time',
  newPanchayat: 'Set up a Panchayat',
  newPanchayatSub: 'Create a login, its village, languages and team',
  newVillage: 'Set up a new village',
  today: 'Today',
  openComplaints: 'open complaints',
});

interface Item {
  to: string;
  label: string;
  sub?: string;
  external?: boolean;
}

export function MorePage() {
  const { vid } = useVillage();
  const { me } = useMe();
  const { signOut } = useAuth();
  const base = `/villages/${encodeURIComponent(vid)}`;
  const items: Item[] = [
    { to: `${base}/more/sources`, label: m.sources, sub: m.sourcesSub },
    { to: `${base}/more/team`, label: m.team, sub: m.teamSub },
    { to: `${base}/more/announcements`, label: m.announcements, sub: m.annSub },
    { to: `${base}/more/reports`, label: m.reports, sub: m.reportsSub },
    { to: `${base}/poster`, label: m.poster, sub: m.posterSub },
    { to: `/v/${encodeURIComponent(vid)}`, label: m.residents, sub: m.residentsSub, external: true },
    { to: `${base}/more/settings`, label: m.settings, sub: m.settingsSub },
    { to: `${base}/more/help`, label: m.help },
    { to: '/how', label: m.how, sub: m.howSub },
  ];
  const admin: Item[] = [
    { to: `${base}/more/new-panchayat`, label: m.newPanchayat, sub: m.newPanchayatSub },
    { to: `${base}/more/villages`, label: m.allVillages },
  ];
  const row = (it: Item) => (
    <li key={it.to}>
      <Link className="row" to={it.to} target={it.external ? '_blank' : undefined} rel={it.external ? 'noopener' : undefined}>
        <span className="row-main">
          <span>{it.label}</span>
          {it.sub && <span className="row-sub">{it.sub}</span>}
        </span>
        <span className="row-end">›</span>
      </Link>
    </li>
  );
  return (
    <div className="page">
      <PageTitle title={m.title} />
      <Card>
        <ul className="rows">{items.map(row)}</ul>
      </Card>
      {me.is_admin && (
        <Card title={m.admin}>
          <ul className="rows">{admin.map(row)}</ul>
        </Card>
      )}
      <div>
        <Button onClick={signOut}>{m.signOut}</Button>
      </div>
    </div>
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

// ------------------------------------------------------------------ water sources

export function SourcesPage() {
  const api = useApi();
  const errorText = useErrorText();
  const { vid, detail, reload } = useVillage();
  const [name, setName] = useState('');
  const [kind, setKind] = useState<WaterPointKind>('PIPED');
  const [hamlet, setHamlet] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const points = (detail.water_points ?? []).filter((p) => p.active);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setMsg(null);
    try {
      await api.saveWaterPoint(vid, { name: name.trim(), kind, hamlet: hamlet.trim() || null });
      setName('');
      setHamlet('');
      setMsg({ ok: true, text: m.saved });
      reload();
    } catch (err) {
      setMsg({ ok: false, text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <BackToMore />
      <PageTitle title={m.sources} />
      <Card>
        {points.length === 0 ? (
          <p className="muted">{m.noSources}</p>
        ) : (
          <ul className="rows">
            {points.map((p) => (
              <li key={p.id} className="row">
                <span className="row-main">
                  <span>{p.name}</span>
                  <span className="row-sub">{[WATER_POINT_KIND[p.kind].en, p.hamlet].filter(Boolean).join(' · ')}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
        <Note>{m.sourcesNote}</Note>
      </Card>
      <Card title={m.addSource}>
        <form className="form" onSubmit={(e) => void submit(e)}>
          <Field label={m.name}>{(id) => <input id={id} value={name} onChange={(e) => setName(e.target.value)} required />}</Field>
          <Field label={m.kind}>
            {(id) => (
              <select id={id} value={kind} onChange={(e) => setKind(e.target.value as WaterPointKind)}>
                {WATER_POINT_KINDS.map((k) => (
                  <option key={k} value={k}>{WATER_POINT_KIND[k].en}</option>
                ))}
              </select>
            )}
          </Field>
          <Field label={m.hamlet}>{(id) => <input id={id} value={hamlet} onChange={(e) => setHamlet(e.target.value)} />}</Field>
          <div className="actions">
            <Button type="submit" variant="primary" busy={busy} disabled={!name.trim()}>{m.save}</Button>
          </div>
          {msg && <p className={msg.ok ? 'ok-box' : 'warn-box'} role="status">{msg.text}</p>}
        </form>
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ team

const TEAM: Array<{ role: TeamRole; op: Operator['role']; label: string; sub: string }> = [
  { role: 'operator', op: 'NAL_JAL_MITRA', label: m.operator, sub: m.operatorSub },
  { role: 'sarpanch', op: 'SARPANCH', label: m.sarpanch, sub: m.sarpanchSub },
  { role: 'secretary', op: 'PANCHAYAT_SECRETARY', label: m.secretary, sub: m.secretarySub },
];

export function TeamPage() {
  const api = useApi();
  const { vid, reload: reloadVillage } = useVillage();
  const team = useAsync(() => api.getTeam(vid), `team:${vid}`);
  const [editing, setEditing] = useState<TeamRole | null>(null);

  return (
    <div className="page">
      <BackToMore />
      <PageTitle title={m.team} />
      {team.error && !team.data ? (
        <ErrorBox error={team.error} onRetry={team.reload} />
      ) : !team.data ? (
        <Loading />
      ) : (
        <Card>
          <ul className="rows">
            {TEAM.map((slot) => {
              const person = team.data?.find((o) => o.role === slot.op);
              return (
                <li key={slot.role}>
                  <div className="row">
                    <span className="row-main">
                      <span><b>{slot.label}</b> · {person ? [person.display_name, shortMasked(person.phone_e164)].filter(Boolean).join(' · ') : m.notSet}</span>
                      <span className="row-sub">{slot.sub}</span>
                    </span>
                    {editing !== slot.role && (
                      <Button onClick={() => setEditing(slot.role)}>{person ? m.change : m.add}</Button>
                    )}
                  </div>
                  {editing === slot.role && (
                    <PersonForm
                      initialName={person?.display_name ?? ''}
                      onCancel={() => setEditing(null)}
                      onSave={async (name, phone) => {
                        await api.saveTeamMember(vid, slot.role, { name, phone });
                        setEditing(null);
                        team.reload();
                        reloadVillage();
                      }}
                    />
                  )}
                </li>
              );
            })}
          </ul>
          <Note>{m.teamNote}</Note>
        </Card>
      )}
    </div>
  );
}

function PersonForm({
  initialName,
  onSave,
  onCancel,
}: {
  initialName: string;
  onSave: (name: string, phone: string) => Promise<void>;
  onCancel: () => void;
}) {
  const errorText = useErrorText();
  const [name, setName] = useState(initialName);
  const [phone, setPhone] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!normaliseMobile(phone)) {
      setError(m.badMobile);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSave(name.trim(), phone);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <form className="form" style={{ paddingBottom: 16 }} onSubmit={(e) => void submit(e)}>
      <Field label={m.name}>{(id) => <input id={id} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
      <Field label={m.mobile}>
        {(id) => <input id={id} value={phone} inputMode="tel" autoComplete="off" onChange={(e) => setPhone(e.target.value)} required />}
      </Field>
      {error && <p className="warn-box" role="alert">{error}</p>}
      <div className="actions">
        <Button type="submit" variant="primary" busy={busy}>{m.save}</Button>
        <Button onClick={onCancel}>{m.cancel}</Button>
      </div>
    </form>
  );
}

// ------------------------------------------------------------------ help

const help = defineMessages({
  title: 'How JalSakshi works',
  s1: 'Every evening at 7 pm, JalSakshi calls the families who agreed and asks one question: did tap water come today?',
  s2: 'Families answer by pressing a key on their phone. No smartphone or internet is needed.',
  s3: 'When enough families say there was no water or dirty water, a complaint opens and the pump operator gets a call.',
  s4: 'When the operator says it is fixed, JalSakshi calls the same families again to check.',
  s5: 'A complaint closes only when families confirm water is back; nobody can close it by hand.',
  s6: 'These answers become the record for the Gram Sabha: how many days water came, and how fast repairs happened.',
  keys: 'What families press',
  k1: 'water came',
  k2: 'no water',
  k3: 'some water',
  join: 'To join: press 1 on the first call, or give a missed call to',
  hours: 'The daily call goes at 7 pm. A missed call is called back at any hour.',
});

export function HelpPage() {
  return (
    <div className="page">
      <BackToMore />
      <PageTitle title={help.title} />
      <Card>
        {[help.s1, help.s2, help.s3, help.s4, help.s5, help.s6].map((s, i) => (
          <p key={i}>{s}</p>
        ))}
      </Card>
      <Card title={help.keys}>
        <ul className="legend">
          <li><b>1</b> {help.k1}</li>
          <li><b>2</b> {help.k2}</li>
          <li><b>3</b> {help.k3}</li>
        </ul>
        <p>{help.join} <b>{MISSED_CALL}</b>.</p>
        <Note>{help.hours}</Note>
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ all villages (admin)

export function AllVillagesPage() {
  const { villages } = useVillage();
  return (
    <div className="page">
      <BackToMore />
      <PageTitle title={m.allVillages}>
        <Link className="btn btn-primary" to="/setup">{m.newVillage}</Link>
      </PageTitle>
      <Card>
        <ul className="rows">
          {villages.map((v) => (
            <li key={v.village.id}>
              <Link className="row" to={`/villages/${encodeURIComponent(v.village.id)}`}>
                <span className="row-main">
                  <span>{villageName(v.village)}</span>
                  <span className="row-sub">{[v.village.gram_panchayat, v.village.block, v.village.district].filter((x) => x && x !== '-').join(' · ')}</span>
                </span>
                <span className="row-end">
                  {m.today}: {WATER_WORD[v.today?.status ?? 'NONE'].en}
                  <br />
                  {(v.open_tickets ?? []).length} {m.openComplaints}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
