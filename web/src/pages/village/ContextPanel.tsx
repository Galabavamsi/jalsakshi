import type { ReactNode } from 'react';
import type { VillageContext } from '../../api/types';
import { Bi } from '../../components/Bi';
import { IconFlag, IconGround, IconRain } from '../../components/Icons';
import { SourceBadge } from '../../components/SourceBadge';
import { useT } from '../../i18n/locale';
import { cx } from '../../lib/cx';
import type { Bilingual } from '../../lib/format';
import { num } from '../../lib/format';
import styles from './VillageDetail.module.css';

const GW_CATEGORY: Record<string, Bilingual> = {
  safe: { en: 'Safe', hi: 'सुरक्षित' },
  'semi-critical': { en: 'Semi-critical', hi: 'अर्ध-गंभीर' },
  critical: { en: 'Critical', hi: 'गंभीर' },
  'over-exploited': { en: 'Over-exploited', hi: 'अति-दोहित' },
  saline: { en: 'Saline', hi: 'खारा' },
};

function category(raw: string): Bilingual {
  return GW_CATEGORY[raw.trim().toLowerCase()] ?? { en: raw, hi: raw };
}

/** Context is printed record: each item a register slip with its source and freshness. */
function Item({ icon, title, children }: { icon: ReactNode; title: Bilingual; children: ReactNode }) {
  return (
    <li className={cx('slip', styles.contextItem)}>
      <span className={styles.contextIcon} aria-hidden="true">
        {icon}
      </span>
      <div className={styles.contextBody}>
        <Bi t={title} as="h3" className={styles.contextTitle} />
        {children}
      </div>
    </li>
  );
}

function Missing() {
  return <Bi as="p" en="Not available" hi="उपलब्ध नहीं" className={styles.contextMissing} />;
}

/** Background the Gram Sabha may ask about: groundwater, rain and the state's own numbers. */
export function ContextPanel({ context }: { context: VillageContext }) {
  const t = useT();
  const { groundwater, rain_7d_mm: rain, state_hgj: hgj } = context;
  return (
    <ul className={styles.context}>
      <Item icon={<IconGround />} title={{ en: 'Groundwater stage, block', hi: 'भूजल स्तर, विकासखंड' }}>
        {groundwater ? (
          <>
            <p className={cx('slip-value', styles.contextValue)}>
              {groundwater.stage_pct !== null && <span className="num">{groundwater.stage_pct}% </span>}
              {t(category(groundwater.category))}
            </p>
            <SourceBadge source={groundwater.source} />
          </>
        ) : (
          <Missing />
        )}
      </Item>
      <Item icon={<IconRain />} title={{ en: 'Rain, last 7 days', hi: 'पिछले 7 दिन की बारिश' }}>
        {rain ? (
          <>
            <p className={cx('slip-value', styles.contextValue)}>
              <span className="num">{rain.value}</span> {t({ en: 'mm', hi: 'मिमी' })}
            </p>
            <SourceBadge source={rain.source} />
          </>
        ) : (
          <Missing />
        )}
      </Item>
      <Item icon={<IconFlag />} title={{ en: 'Har Ghar Jal in the state', hi: 'राज्य में हर घर जल' }}>
        {hgj ? (
          <>
            <p className={cx('slip-value', styles.contextValue)}>
              {t({
                en: `${num(hgj.reported)} villages declared, ${num(hgj.certified)} certified, of ${num(hgj.villages)}`,
                hi: `${num(hgj.villages)} में से ${num(hgj.reported)} गाँव घोषित, ${num(hgj.certified)} प्रमाणित`,
              })}
            </p>
            <SourceBadge source={hgj.source} />
          </>
        ) : (
          <Missing />
        )}
      </Item>
    </ul>
  );
}
