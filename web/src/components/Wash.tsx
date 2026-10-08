/**
 * Decorative watercolour wash (Tyler Hobbs' layered polygon deformation), seeded so a village
 * always gets the same shape. Vector only: no live SVG filter, no canvas, no dependency.
 * Texture comes from two static noise images used as a CSS mask (.wash in styles/watercolour.css).
 *
 * Always decorative: aria-hidden, never carries meaning on its own (status is in the chip text).
 */
import { memo, useMemo } from 'react';
import type { DayStatusValue } from '../api/types';

type Rand = () => number;

function mulberry32(seed: number): Rand {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function hashSeed(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

function gauss(rand: Rand): number {
  let u = 0;
  while (u === 0) u = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rand());
}

interface Pt {
  x: number;
  y: number;
  /** "Wetness": edges between wet points bleed further. */
  w: number;
}

function deform(poly: Pt[], depth: number, variance: number, rand: Rand): Pt[] {
  let pts = poly;
  for (let d = 0; d < depth; d++) {
    const next: Pt[] = [];
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i]!;
      const b = pts[(i + 1) % pts.length]!;
      const len = Math.hypot(b.x - a.x, b.y - a.y);
      const v = variance * ((a.w + b.w) / 2) * len;
      next.push(a, {
        x: (a.x + b.x) / 2 + gauss(rand) * v,
        y: (a.y + b.y) / 2 + gauss(rand) * v,
        w: Math.max(0.1, (a.w + b.w) / 2 + gauss(rand) * 0.15),
      });
    }
    pts = next;
  }
  return pts;
}

const r1 = (n: number) => Math.round(n * 10) / 10;
const toPath = (pts: Pt[]) => 'M' + pts.map((p) => `${r1(p.x)} ${r1(p.y)}`).join('L') + 'Z';

/**
 * Layer outlines for one wash. `spread` is the base polygon's radius as a share of the box:
 * 0.36 leaves a blot with margins (decor), ~0.44 paints most of the box (panels under text).
 */
export function washPaths(seed: number, layers = 24, w = 400, h = 240, spread = 0.36): string[] {
  const rand = mulberry32(seed);
  const sides = 7;
  const base0: Pt[] = Array.from({ length: sides }, (_, i) => {
    const t = (i / sides) * Math.PI * 2;
    return {
      x: w / 2 + Math.cos(t) * w * spread,
      y: h / 2 + Math.sin(t) * h * (spread - 0.02),
      w: 0.4 + rand() * 0.8,
    };
  });
  const base = deform(base0, 2, 0.1, rand);
  return Array.from({ length: layers }, () => toPath(deform(base, 2, 0.2, rand)));
}

export type WashTone = 'jal' | 'supplied' | 'partial' | 'no' | 'dirty' | 'unverified' | 'stamp';

const STATUS_TONE: Record<DayStatusValue, WashTone> = {
  SUPPLIED: 'supplied',
  PARTIAL: 'partial',
  NO_SUPPLY: 'no',
  DIRTY: 'dirty',
  UNVERIFIED: 'unverified',
};

/** The wash tone for a day status: the status ink itself, so paint never invents a meaning. */
export function toneFor(status: DayStatusValue): WashTone {
  return STATUS_TONE[status];
}

interface WashProps {
  /** Stable id, e.g. the village id, so the shape never changes between renders. */
  seed: string;
  tone: WashTone;
  className?: string;
  /** Let the paint run a little past the box (bands); off for panels with a crisp edge. */
  bleed?: boolean;
  /**
   * 'stretch' (default) shapes the wash to its box, so a wide band is painted along its length;
   * 'slice' keeps the blot's own proportions (the stamp halo, the sign-in backdrop).
   */
  fit?: 'stretch' | 'slice';
  /**
   * 'under-text': core opacity <= 0.26 (12 x 0.024), keeps --ink >= 10:1 and --ink-2 >= 5:1 on any tone.
   * 'decor': core opacity ~0.67 (24 x 0.045), only where no text sits on top.
   */
  strength?: 'under-text' | 'decor';
}

const STRENGTH = {
  'under-text': { layers: 12, opacity: 0.024, spread: 0.44 },
  decor: { layers: 24, opacity: 0.045, spread: 0.36 },
} as const;

export const Wash = memo(function Wash({
  seed,
  tone,
  className,
  bleed = false,
  fit = 'stretch',
  strength = 'under-text',
}: WashProps) {
  const { layers, opacity, spread } = STRENGTH[strength];
  const paths = useMemo(() => washPaths(hashSeed(seed), layers, 400, 240, spread), [seed, layers, spread]);
  return (
    <svg
      className={['wash', bleed && 'wash-bleed', className].filter(Boolean).join(' ')}
      viewBox="0 0 400 240"
      preserveAspectRatio={fit === 'slice' ? 'xMidYMid slice' : 'none'}
      aria-hidden="true"
      focusable="false"
      style={{ color: `var(--wash-${tone})` }}
    >
      {paths.map((d, i) => (
        <path key={i} d={d} fill="currentColor" fillOpacity={opacity} />
      ))}
    </svg>
  );
});
