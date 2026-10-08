/**
 * Inline SVG icons (24px grid, 2px strokes). Decorative: always aria-hidden, the text beside
 * them carries the meaning. Status icons differ by shape, not only by colour.
 */

import type { ReactNode, SVGProps } from 'react';
import type { DayStatusValue } from '../api/types';

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Svg({ size = 24, children, ...rest }: IconProps & { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

const DROP = 'M12 2.8C8.2 7.6 6 11.2 6 14.2a6 6 0 0 0 12 0c0-3-2.2-6.6-6-11.4z';

export const IconDrop = (p: IconProps) => (
  <Svg {...p}>
    <path d={DROP} />
  </Svg>
);

export const IconSupplied = (p: IconProps) => (
  <Svg {...p}>
    <path d={DROP} fill="currentColor" />
    <path d="M9.2 14.4l2 2 3.8-4.2" stroke="#fff" strokeWidth={2.2} />
  </Svg>
);

export const IconPartial = (p: IconProps) => (
  <Svg {...p}>
    <path d={DROP} />
    <path d="M6.2 14.6h11.6a6 6 0 0 1-11.6 0z" fill="currentColor" stroke="none" />
  </Svg>
);

export const IconNoSupply = (p: IconProps) => (
  <Svg {...p}>
    <path d={DROP} />
    <path d="M4 4l16 16" />
  </Svg>
);

export const IconDirty = (p: IconProps) => (
  <Svg {...p}>
    <path d={DROP} />
    <circle cx="10" cy="14" r="1" fill="currentColor" />
    <circle cx="14" cy="15.5" r="1" fill="currentColor" />
    <circle cx="12" cy="11" r="1" fill="currentColor" />
  </Svg>
);

export const IconUnverified = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" strokeDasharray="3 3" />
    <path d="M9.6 9.6a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.4" />
    <circle cx="12" cy="16.8" r="0.6" fill="currentColor" />
  </Svg>
);

const STATUS_ICON: Record<DayStatusValue, (p: IconProps) => ReactNode> = {
  SUPPLIED: IconSupplied,
  PARTIAL: IconPartial,
  NO_SUPPLY: IconNoSupply,
  DIRTY: IconDirty,
  UNVERIFIED: IconUnverified,
};

export function StatusIcon({ status, ...p }: IconProps & { status: DayStatusValue }) {
  const Icon = STATUS_ICON[status];
  return <Icon {...p} />;
}

/** The JalSakshi mark: a village tap with a drop. */
export const IconTap = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 8h9a4 4 0 0 1 4 4v1" />
    <path d="M3 5v6" />
    <path d="M8 8V5h3" />
    <path d="M16 16.5c-1.2 1.5-1.8 2.5-1.8 3.3a1.8 1.8 0 0 0 3.6 0c0-.8-.6-1.8-1.8-3.3z" />
  </Svg>
);

export const IconVillage = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 11l6-5 6 5" />
    <path d="M5 10v9h8v-9" />
    <path d="M15 19h6v-6l-3-2.5" />
    <path d="M8 19v-4h2v4" />
  </Svg>
);

export const IconPulse = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 12h4l2.5-6 4 12 2.5-6H21" />
  </Svg>
);

export const IconPhone = (p: IconProps) => (
  <Svg {...p}>
    <rect x="7" y="2.5" width="10" height="19" rx="2" />
    <path d="M9.5 6h5" />
    <path d="M9.5 11h1M13.5 11h1M9.5 14h1M13.5 14h1M9.5 17h1M13.5 17h1" />
  </Svg>
);

export const IconCall = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 4h3.5l1.8 4.5-2.3 1.4a11 11 0 0 0 6.1 6.1l1.4-2.3L20 15.5V19a1.5 1.5 0 0 1-1.6 1.5C10.6 20 4 13.4 3.5 5.6A1.5 1.5 0 0 1 5 4z" />
  </Svg>
);

export const IconHangup = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 14.5c4.8-4.7 12.2-4.7 17 0l-2 2.5-3.2-1.3v-2.2a10 10 0 0 0-6.6 0v2.2L5.5 17z" />
  </Svg>
);

export const IconTicket = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 6h16v4a2 2 0 0 0 0 4v4H4v-4a2 2 0 0 0 0-4z" />
    <path d="M14 6v12" strokeDasharray="2 2.5" />
  </Svg>
);

export const IconBack = (p: IconProps) => (
  <Svg {...p}>
    <path d="M15 5l-7 7 7 7" />
  </Svg>
);

export const IconForward = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 5l7 7-7 7" />
  </Svg>
);

export const IconPrint = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7 9V3h10v6" />
    <rect x="3.5" y="9" width="17" height="8" rx="1.5" />
    <path d="M7 14h10v7H7z" />
  </Svg>
);

export const IconPlay = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7 4.5v15l12-7.5z" />
  </Svg>
);

export const IconShield = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3l7.5 3v5.5c0 4.5-3.2 8-7.5 9.5-4.3-1.5-7.5-5-7.5-9.5V6z" />
    <path d="M9.5 9.5l5 5M14.5 9.5l-5 5" />
  </Svg>
);

export const IconCheck = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Svg>
);

export const IconWrench = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14.5 4a4.5 4.5 0 0 0-4.2 6.1L4 16.4 7.6 20l6.3-6.3A4.5 4.5 0 0 0 20 9.5l-2.8 2.8-3-1-1-3L16 5.5A4.5 4.5 0 0 0 14.5 4z" />
  </Svg>
);

export const IconRain = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7 15a4 4 0 0 1-.5-8A5.5 5.5 0 0 1 17 6.5a3.5 3.5 0 0 1 .5 7H7z" />
    <path d="M8 18l-1 2.5M12 18l-1 2.5M16 18l-1 2.5" />
  </Svg>
);

export const IconGround = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 8h18M3 13h18" />
    <path d="M12 3v14" />
    <path d="M9.5 15l2.5 3 2.5-3" />
    <path d="M3 19h18" strokeDasharray="2 2" />
  </Svg>
);

export const IconFlag = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 21V4" />
    <path d="M5 4h12l-2.5 4L17 12H5" />
  </Svg>
);

export const IconSpeaker = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 9.5h3.5L12 5v14l-4.5-4.5H4z" />
    <path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" />
  </Svg>
);

export const IconDoc = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 3h8l4 4v14H6z" />
    <path d="M14 3v4h4M9 12h6M9 16h6" />
  </Svg>
);

export const IconRefresh = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 12a8 8 0 1 1-2.4-5.7" />
    <path d="M20 4v5h-5" />
  </Svg>
);

export const IconUser = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21c1-4 4.2-6 8-6s7 2 8 6" />
  </Svg>
);

export const IconMic = (p: IconProps) => (
  <Svg {...p}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" />
  </Svg>
);
