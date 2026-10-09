import { useMemo } from 'react';
import { encode } from 'uqr';

/**
 * Module path of a QR code: one `h1v1h-1z` square per dark module, offset by the quiet zone.
 * Pure, so it is tested without rendering.
 */
export function qrPath(data: ReadonlyArray<ReadonlyArray<boolean>>, offset = 0): string {
  const parts: string[] = [];
  data.forEach((row, y) => {
    row.forEach((dark, x) => {
      if (dark) parts.push(`M${x + offset},${y + offset}h1v1h-1z`);
    });
  });
  return parts.join('');
}

export interface QrCodeProps {
  /** The text to encode (an absolute URL). */
  value: string;
  /** Accessible name ("QR code for the residents' page"). */
  label: string;
  className?: string;
}

/**
 * A QR code drawn as inline SVG from `uqr` (loaded lazily: only the poster pays for it). Dark
 * modules use `currentColor` on a transparent ground, so it prints black on white paper and
 * stays black-and-white safe; medium error correction survives a creased poster.
 */
export default function QrCode({ value, label, className }: QrCodeProps) {
  const { size, path } = useMemo(() => {
    const qr = encode(value, { ecc: 'M', border: 0 });
    const quiet = 2;
    return { size: qr.size + quiet * 2, path: qrPath(qr.data, quiet) };
  }, [value]);
  return (
    <svg
      className={className}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={label}
      shapeRendering="crispEdges"
      focusable="false"
    >
      <path d={path} fill="currentColor" />
    </svg>
  );
}
