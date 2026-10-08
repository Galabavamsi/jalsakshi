import type { Village } from '../api/types';
import { useLocale } from '../i18n/locale';
import { devanagariVillage, romanVillage, villageLabel } from '../lib/places';

/**
 * A village's name: "Nayapara" with "नयापारा" beside it in English, Devanagari alone in Hindi.
 * A name with no known Latin spelling is shown as written.
 */
export function VillageName({ village }: { village: Pick<Village, 'id' | 'name'> }) {
  const { locale } = useLocale();
  const latin = romanVillage(village);
  if (locale === 'hi' || !latin) {
    return <span lang="hi">{villageLabel(village, 'hi')}</span>;
  }
  const deva = devanagariVillage(village);
  return (
    <>
      <span lang="en" translate="no">
        {latin}
      </span>
      {deva && (
        <span lang="hi" className="aside-script">
          {deva}
        </span>
      )}
    </>
  );
}
