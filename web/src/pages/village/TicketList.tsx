import { Link } from 'react-router-dom';
import type { Ticket } from '../../api/types';
import { Bi } from '../../components/Bi';
import { IconForward, IconTicket } from '../../components/Icons';
import { Empty } from '../../components/PageState';
import { TicketStateBadge } from '../../components/TicketParts';
import { cx } from '../../lib/cx';
import { dateTime } from '../../lib/format';
import { REASON, isOpenState } from '../../lib/labels';
import styles from './VillageDetail.module.css';

/** Every ticket for the village, open ones first. */
export function TicketList({ tickets }: { tickets: Ticket[] }) {
  if (tickets.length === 0) {
    return <Empty text={{ hi: 'इस गाँव में कोई शिकायत नहीं।', en: 'No tickets for this village.' }} />;
  }
  const ordered = [...tickets].sort(
    (a, b) =>
      Number(isOpenState(b.state)) - Number(isOpenState(a.state)) ||
      b.opened_at.localeCompare(a.opened_at),
  );
  return (
    <ul className={styles.tickets}>
      {ordered.map((t) => {
        const opened = dateTime(t.opened_at);
        return (
          <li key={t.id}>
            <Link
              to={`/tickets/${encodeURIComponent(t.id)}`}
              className={cx(styles.ticketRow, isOpenState(t.state) && styles.ticketOpen)}
            >
              <IconTicket size={24} className={styles.ticketIcon} />
              <span className={styles.ticketMain}>
                <Bi t={REASON[t.reason]} className={styles.ticketReason} />
                <span className={styles.ticketDate}>
                  <span lang="hi">{opened.hi} को खुली</span> <span lang="en">(opened {opened.en})</span>
                </span>
              </span>
              <TicketStateBadge state={t.state} />
              <IconForward size={20} className={styles.chev} />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
