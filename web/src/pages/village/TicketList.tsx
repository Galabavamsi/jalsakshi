import { Link } from 'react-router-dom';
import type { Ticket } from '../../api/types';
import { Bi } from '../../components/Bi';
import { IconForward, IconTicket } from '../../components/Icons';
import { Empty } from '../../components/PageState';
import { TicketStateBadge } from '../../components/TicketParts';
import { useT } from '../../i18n/locale';
import { cx } from '../../lib/cx';
import { dateTime } from '../../lib/format';
import { REASON, isOpenState } from '../../lib/labels';
import styles from './VillageDetail.module.css';

/** Every ticket for the village, open ones first. */
export function TicketList({ tickets }: { tickets: Ticket[] }) {
  const t = useT();
  if (tickets.length === 0) {
    return (
      <Empty
        text={{
          en: 'No repair tickets for this village. A ticket opens on its own when households report no water or dirty water.',
          hi: 'इस गाँव में कोई शिकायत नहीं। घर पानी न आने या गंदे पानी की बात बताएँ, तो शिकायत अपने-आप खुलती है।',
        }}
      />
    );
  }
  const ordered = [...tickets].sort(
    (a, b) =>
      Number(isOpenState(b.state)) - Number(isOpenState(a.state)) ||
      b.opened_at.localeCompare(a.opened_at),
  );
  return (
    <ul className={styles.tickets}>
      {ordered.map((ticket) => {
        const opened = t(dateTime(ticket.opened_at));
        return (
          <li key={ticket.id}>
            <Link
              to={`/tickets/${encodeURIComponent(ticket.id)}`}
              className={cx(styles.ticketRow, isOpenState(ticket.state) && styles.ticketOpen)}
            >
              <IconTicket size={24} className={styles.ticketIcon} />
              <span className={styles.ticketMain}>
                <Bi t={REASON[ticket.reason]} className={styles.ticketReason} />
                <span className={styles.ticketDate}>
                  {t({ en: `Opened ${opened}`, hi: `${opened} को खुली` })}
                </span>
              </span>
              <TicketStateBadge state={ticket.state} />
              <IconForward size={20} className={styles.chev} />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
