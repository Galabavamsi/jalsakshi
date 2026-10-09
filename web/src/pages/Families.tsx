/** Families: who agreed, who is waiting, by area (mohalla/para); adding more; the consent record. */

import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useApi } from '../api/context';
import { defineMessages, msgFn } from '../lib/text';
import { consentCsvName, consentLedgerCsv, downloadText } from '../lib/csv';
import { NO_AREA, NO_NAME, areaList, areaOf, groupByArea, languageName } from '../lib/households';
import { shortMasked } from '../lib/phones';
import { FAMILY_STATUS, familyCounts, familyStatus } from '../lib/summary';
import { istDate } from '../lib/time';
import { useVillage } from '../shell';
import { Button, Card, Field, Note, PageTitle, useErrorText } from '../ui';
import { BulkAdd } from './BulkAdd';

const m = defineMessages({
  title: 'Families',
  summary: msgFn<{ a: number; w: number; n: number }>(({ a, w, n }) => `Agreed ${a} · Waiting for their call ${w} · Said no ${n}`),
  add: 'Add families',
  hide: 'Close',
  none: 'No families yet. Add their mobile numbers above.',
  csv: 'Download consent record (CSV)',
  note: 'Only families who pressed 1 to agree get the daily call. Numbers are hidden except the last four digits.',
  noSource: 'Water source not set',
  areaFilter: 'Area',
  allAreas: 'All areas',
  callAgain: 'Call again',
  calling: 'Calling…',
  called: 'Call placed',
});

const NO_AREA_KEY = '__none__';

const WORD_CLASS = { AGREED: 'word-good', WAITING: 'word-warn', SAID_NO: 'word-NONE' } as const;

export function FamiliesPage() {
  const api = useApi();
  const errorText = useErrorText();
  const { vid, detail, reload } = useVillage();
  const [params, setParams] = useSearchParams();
  const adding = params.get('add') === '1';
  const [csvError, setCsvError] = useState<string | null>(null);
  const [calls, setCalls] = useState<Record<string, string>>({});
  const counts = familyCounts(detail.households);
  const families = detail.households.filter((h) => h.active);
  const areas = areaList(families);
  const [area, setArea] = useState('');
  const shown = area === '' ? families : families.filter((h) => (areaOf(h) ?? NO_AREA_KEY) === area);
  const groups = groupByArea(shown);

  function setAdding(on: boolean) {
    setParams(on ? { add: '1' } : {}, { replace: true });
  }

  async function callAgain(hid: string) {
    setCalls((c) => ({ ...c, [hid]: m.calling }));
    try {
      await api.callAgain(vid, hid);
      setCalls((c) => ({ ...c, [hid]: m.called }));
    } catch (err) {
      setCalls((c) => ({ ...c, [hid]: errorText(err) }));
    }
  }

  async function downloadCsv() {
    setCsvError(null);
    try {
      const ledger = await api.getConsents(vid);
      downloadText(consentCsvName(vid, istDate(new Date())), consentLedgerCsv(ledger));
    } catch (err) {
      setCsvError(errorText(err));
    }
  }

  return (
    <div className="page">
      <PageTitle title={m.title}>
        {!adding && (
          <Button variant="primary" onClick={() => setAdding(true)}>
            {m.add}
          </Button>
        )}
      </PageTitle>
      <p className="big">{m.summary({ a: counts.agreed, w: counts.waiting, n: counts.saidNo })}</p>

      {adding && (
        <Card title={m.add} footer={<Button variant="link" onClick={() => setAdding(false)}>{m.hide}</Button>}>
          <BulkAdd vid={vid} onAdded={reload} />
        </Card>
      )}

      <Card>
        {families.length === 0 ? (
          <p className="muted">{m.none}</p>
        ) : (
          <>
            {areas.length > 0 && (
              <Field label={m.areaFilter}>
                {(id) => (
                  <select id={id} value={area} onChange={(e) => setArea(e.target.value)}>
                    <option value="">{m.allAreas}</option>
                    {areas.map((a) => (
                      <option key={a} value={a}>{a}</option>
                    ))}
                    <option value={NO_AREA_KEY}>{NO_AREA}</option>
                  </select>
                )}
              </Field>
            )}
            {groups.map((g) => (
              <section key={g.area ?? NO_AREA_KEY} className="group">
                {areas.length > 0 && (
                  <h2 className="group-title">
                    {g.area ?? NO_AREA} <span className="muted">· {g.items.length}</span>
                  </h2>
                )}
                <ul className="rows">
                  {g.items.map((h) => {
                    const status = familyStatus(h);
                    const point = detail.water_points?.find((p) => p.id === h.water_point_id);
                    const sub = [
                      languageName(h.language),
                      point ? point.name : (detail.water_points?.length ?? 0) > 1 ? m.noSource : null,
                    ].filter(Boolean);
                    return (
                      <li key={h.id} className="row">
                        <span className="row-main">
                          <span>
                            {h.display_name || <span className="muted">{NO_NAME}</span>} · {shortMasked(h.phone_masked)}
                          </span>
                          <span className="row-sub">{sub.join(' · ')}</span>
                        </span>
                        <span className="row-actions">
                          {status === 'WAITING' &&
                            (calls[h.id] ? (
                              <span className="muted">{calls[h.id]}</span>
                            ) : (
                              <Button variant="link" onClick={() => void callAgain(h.id)}>
                                {m.callAgain}
                              </Button>
                            ))}
                          <span className={`word ${WORD_CLASS[status]}`}>{FAMILY_STATUS[status].en}</span>
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
          </>
        )}
        <Note>{m.note}</Note>
      </Card>
      <div>
        <Button variant="link" onClick={() => void downloadCsv()}>
          {m.csv}
        </Button>
        {csvError && <p className="warn-box">{csvError}</p>}
      </div>
    </div>
  );
}
