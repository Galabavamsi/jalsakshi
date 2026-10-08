import type { ReactNode } from 'react';
import type { VillageContext } from '../../api/types';
import { Bi } from '../../components/Bi';
import { IconFlag, IconGround, IconRain } from '../../components/Icons';
import { SourceBadge } from '../../components/SourceBadge';
import type { Bilingual } from '../../lib/format';
import { num } from '../../lib/format';
import styles from './VillageDetail.module.css';

const GW_CATEGORY: Record<string, string> = {
  safe: 'सुरक्षित',
  'semi-critical': 'अर्ध-गंभीर',
  critical: 'गंभीर',
  'over-exploited': 'अति-दोहित',
  saline: 'खारा',
};

function categoryHi(category: string): string {
  return GW_CATEGORY[category.trim().toLowerCase()] ?? category;
}

function Item({ icon, title, children }: { icon: ReactNode; title: Bilingual; children: ReactNode }) {
  return (
    <li className={styles.contextItem}>
      <span className={styles.contextIcon} aria-hidden="true">
        {icon}
      </span>
      <div className={styles.contextBody}>
        <Bi t={title} className={styles.contextTitle} />
        {children}
      </div>
    </li>
  );
}

function Missing() {
  return <Bi hi="उपलब्ध नहीं" en="Not available" className={styles.contextMissing} />;
}

/** Background the Gram Sabha may ask about: groundwater, rain and the state's own numbers. */
export function ContextPanel({ context }: { context: VillageContext }) {
  const { groundwater, rain_7d_mm: rain, state_hgj: hgj } = context;
  return (
    <ul className={styles.context}>
      <Item icon={<IconGround />} title={{ hi: 'भूजल स्तर, विकासखंड', en: 'Groundwater stage, block' }}>
        {groundwater ? (
          <>
            <p className={styles.contextValue}>
              {groundwater.stage_pct !== null && (
                <>
                  <span className="num">{groundwater.stage_pct}%</span>{' '}
                </>
              )}
              <span lang="hi">{categoryHi(groundwater.category)}</span>{' '}
              <span lang="en" className={styles.contextEn}>
                ({groundwater.category})
              </span>
            </p>
            <SourceBadge source={groundwater.source} />
          </>
        ) : (
          <Missing />
        )}
      </Item>
      <Item icon={<IconRain />} title={{ hi: 'पिछले 7 दिन की बारिश', en: 'Rain, last 7 days' }}>
        {rain ? (
          <>
            <p className={styles.contextValue}>
              <span className="num">{rain.value}</span> <span lang="hi">मिमी</span>{' '}
              <span lang="en" className={styles.contextEn}>
                (mm)
              </span>
            </p>
            <SourceBadge source={rain.source} />
          </>
        ) : (
          <Missing />
        )}
      </Item>
      <Item icon={<IconFlag />} title={{ hi: 'राज्य में हर घर जल', en: 'Har Ghar Jal in the state' }}>
        {hgj ? (
          <>
            <p className={styles.contextValue}>
              <span className="num">{num(hgj.reported)}</span> <span lang="hi">गाँव घोषित,</span>{' '}
              <span className="num">{num(hgj.certified)}</span> <span lang="hi">प्रमाणित</span>
            </p>
            <p className={styles.contextEn} lang="en">
              {num(hgj.reported)} villages declared, {num(hgj.certified)} certified, of{' '}
              {num(hgj.villages)}
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
