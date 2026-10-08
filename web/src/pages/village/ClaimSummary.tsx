import type { DayStatus, IsoDate, Village } from '../../api/types';
import { isMock } from '../../appConfig';
import { RegisterSlip } from '../../components/RegisterSlip';
import { SourceBadge } from '../../components/SourceBadge';
import { Verdict } from '../../components/Verdict';
import { useT } from '../../i18n/locale';
import { checkinSource } from '../../lib/sources';
import { observedFromDays, verdictOf } from '../../lib/verdict';
import styles from './VillageDetail.module.css';

/**
 * The village's story in one row: the verdict on the last seven days (households against the
 * record), with its source, beside the state's record slip.
 */
export function ClaimSummary({
  village,
  days,
  today,
}: {
  village: Village;
  /** Day statuses for at least the last seven days; undefined while loading. */
  days: DayStatus[] | undefined;
  today: IsoDate;
}) {
  const t = useT();
  const observed = days ? observedFromDays(days, today) : null;
  const latest = (days ?? []).reduce<DayStatus | undefined>(
    (best, d) => (!best || d.computed_at > best.computed_at ? d : best),
    undefined,
  );
  return (
    <div className={styles.summary}>
      <div className={styles.summaryVerdict}>
        {observed ? (
          <>
            <Verdict verdict={verdictOf(village, observed)} checkinTime={village.checkin_local_time} />
            {latest && <SourceBadge source={checkinSource(latest.computed_at, isMock)} />}
          </>
        ) : (
          <p className="meta">{t({ en: 'Loading the last 7 days', hi: 'पिछले 7 दिन के आँकड़े आ रहे हैं' })}</p>
        )}
      </div>
      <RegisterSlip
        village={village}
        compact
        gloss
        deckle={false}
        headingLevel={2}
        className={styles.summarySlip}
      />
    </div>
  );
}
