/** Residents' page /v/:villageId — no login. Today's water, last 14 days, open complaints. */

import { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useApi } from '../api/context';
import { useAsync } from '../hooks/useAsync';
import { LocaleProvider, defineMessages, msgFn, resolveInitialLocale, useLocale, useT } from '../i18n/locale';
import { isSampleVillage } from '../lib/demo';
import { displayMissedCall } from '../lib/phones';
import { BROADCAST_KIND, REASON } from '../lib/labels';
import { COMPLAINT_WORD, WATER_WORD, clockText, howLong, whenText } from '../lib/summary';
import { addDays, istDate } from '../lib/time';
import { Card, ErrorBox, Loading, Note, SampleBanner } from '../ui';

const m = defineMessages({
  today: { en: "Today's water", hi: 'आज का पानी' },
  village: { en: 'Whole village', hi: 'पूरा गाँव' },
  days: msgFn<{ n: number; total: number }>({
    en: ({ n, total }) => `Water came on ${n} of the last ${total} days with answers`,
    hi: ({ n, total }) => `जवाब वाले पिछले ${total} दिनों में से ${n} दिन पानी आया`,
  }),
  complaints: { en: 'Open complaints', hi: 'खुली शिकायतें' },
  none: { en: 'No open complaints.', hi: 'कोई खुली शिकायत नहीं।' },
  families: msgFn<{ n: number }>({
    en: ({ n }) => (n === 1 ? '1 family reported' : `${n} families reported`),
    hi: ({ n }) => (n === 1 ? '1 परिवार ने बताया' : `${n} परिवारों ने बताया`),
  }),
  openFor: msgFn<{ d: string }>({ en: ({ d }) => `open ${d}`, hi: ({ d }) => `${d} से खुली` }),
  news: { en: 'Announcements', hi: 'घोषणाएँ' },
  join: { en: 'Join JalSakshi', hi: 'जल साक्षी से जुड़ें' },
  joinText: { en: 'Give a missed call to this number. We call you back; press 1 to join.', hi: 'इस नंबर पर मिस्ड कॉल दें। हम वापस कॉल करेंगे; जुड़ने के लिए 1 दबाएँ।' },
  source: msgFn<{ n: number; at: string }>({
    en: ({ n, at }) => `From ${n} families' phone answers · updated ${at}`,
    hi: ({ n, at }) => `${n} परिवारों के फ़ोन जवाबों से · ${at} पर अपडेट`,
  }),
  notFound: { en: 'This village page was not found.', hi: 'इस गाँव का पेज नहीं मिला।' },
});

/** The residents' page is the one bilingual screen: villagers can switch to Hindi. */
export function PublicPage() {
  return (
    <LocaleProvider initial={resolveInitialLocale()}>
      <PublicView />
    </LocaleProvider>
  );
}

function placeName(v: { name: string; name_hi?: string | null }, locale: 'en' | 'hi'): string {
  return locale === 'hi' && v.name_hi ? v.name_hi : v.name;
}

function LanguageToggle() {
  const { locale, setLocale } = useLocale();
  return (
    <div className="lang" role="group" aria-label="Language / भाषा">
      <button type="button" aria-pressed={locale === 'en'} onClick={() => setLocale('en')}>
        EN
      </button>
      <button type="button" aria-pressed={locale === 'hi'} onClick={() => setLocale('hi')} lang="hi">
        हिन्दी
      </button>
    </div>
  );
}

function PublicView() {
  const t = useT();
  const { locale } = useLocale();
  const api = useApi();
  const { villageId = '' } = useParams();
  const view = useAsync(() => api.getPublicVillage(villageId), `public:${villageId}`);
  const now = new Date();
  const today = istDate(now);

  useEffect(() => {
    if (view.data) document.title = `${placeName(view.data.village, locale)} · JalSakshi`;
  }, [view.data, locale]);

  return (
    <div className="app" style={{ paddingBottom: 32 }}>
      <header className="topbar">
        <div className="wrap topbar-inner">
          <span className="brand">JalSakshi</span>
          <span className="village-name">{view.data ? placeName(view.data.village, locale) : ''}</span>
          <LanguageToggle />
        </div>
      </header>
      <main className="wrap page">
        {isSampleVillage(villageId) && <SampleBanner />}
        {view.error && !view.data ? (
          <ErrorBox error={view.error} onRetry={view.reload} />
        ) : !view.data ? (
          <Loading />
        ) : (
          (() => {
            const v = view.data;
            const todayRow = v.days.find((d) => d.date === today);
            const recent = v.days.filter((d) => d.date >= addDays(today, -13) && d.status !== 'UNVERIFIED');
            const points = v.water_points;
            return (
              <>
                <Card title={t(m.today)}>
                  <ul className="rows">
                    {points.length === 0 ? (
                      <li className="row">
                        <span>{t(m.village)}</span>
                        <span className={`word word-${todayRow?.status ?? 'NONE'}`}>{t(WATER_WORD[todayRow?.status ?? 'NONE'])}</span>
                      </li>
                    ) : (
                      points.map((p) => {
                        const s = todayRow?.points.find((x) => x.water_point_id === p.id)?.status ?? 'NONE';
                        return (
                          <li key={p.id} className="row">
                            <span>{locale === 'hi' && p.name_hi ? p.name_hi : p.name}</span>
                            <span className={`word word-${s}`}>{t(WATER_WORD[s])}</span>
                          </li>
                        );
                      })
                    )}
                  </ul>
                  <p className="muted">{t(m.days, { n: recent.filter((d) => d.status === 'SUPPLIED').length, total: recent.length })}</p>
                  <Note>{t(m.source, { n: v.families_reporting, at: clockText(v.generated_at) })}</Note>
                </Card>

                <Card title={t(m.complaints)}>
                  {v.open_complaints.length === 0 ? (
                    <p className="muted">{t(m.none)}</p>
                  ) : (
                    <ul className="rows">
                      {v.open_complaints.map((c, i) => (
                        <li key={i} className="row">
                          <span className="row-main">
                            <span>{c.number != null ? `#${c.number} ` : ''}{t(REASON[c.reason])}</span>
                            <span className="row-sub">
                              {(locale === 'hi' ? c.water_point_hi || c.water_point : c.water_point) ?? ''}
                              {c.water_point ? ' · ' : ''}
                              {c.families > 0 ? `${t(m.families, { n: c.families })} · ` : ''}
                              {t(m.openFor, { d: howLong(c.opened_at, now)[locale] })}
                            </span>
                          </span>
                          <span className="row-end">{t(COMPLAINT_WORD[c.state])}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>

                {v.announcements.length > 0 && (
                  <Card title={t(m.news)}>
                    <ul className="rows">
                      {v.announcements.slice(0, 3).map((a, i) => (
                        <li key={i} className="row-main" style={{ padding: '8px 0' }}>
                          <span className="row-sub">{t(BROADCAST_KIND[a.kind])} · {whenText(a.sent_at, now)[locale]}</span>
                          <span lang="hi">{a.text_hi}</span>
                        </li>
                      ))}
                    </ul>
                  </Card>
                )}

                <Card title={t(m.join)}>
                  <p className="big">{displayMissedCall(v.missed_call_number)}</p>
                  <p>{t(m.joinText)}</p>
                </Card>
              </>
            );
          })()
        )}
      </main>
    </div>
  );
}
