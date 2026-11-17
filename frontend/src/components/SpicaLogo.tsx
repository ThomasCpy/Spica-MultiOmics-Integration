import { useId } from "react";

// Logo from Thomas's sketch, read as a neuron: three equal short branches
// (dendrites), one long ray (the axon) that runs under the word, and a white
// Gaussian core in the middle (the nucleus). Spica also means "ear of grain",
// and the long ray doubles as the stalk. The mark alone is the app icon.

type LogoProps = { className?: string };

const MARK_STAR =
  "M11 6C10.3 11 6 15.3 1 16C6 16.7 10.3 21 11 26C11.7 21 14.6 16.9 18 16.55L31 16L18 15.45C14.6 15.1 11.7 11 11 6Z";
const LOCKUP_STAR =
  "M12 13C11.2 18.5 6.5 23.2 1 24C6.5 24.8 11.2 29.5 12 35C12.8 29.5 16.5 25 20 24.6L98 24L20 23.4C16.5 23 12.8 18.5 12 13Z";

// Gaussian falloff exp(-r² / 2σ²), sampled at 9 stops. The gradient radius
// is 3σ, so the white fades out well inside the body of the star.
const GAUSSIAN_STOPS = [0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1].map((x) => ({
  offset: x,
  opacity: x === 1 ? 0 : Math.round(Math.exp(-4.5 * x * x) * 1000) / 1000,
}));

function Nucleus({ id, cx, cy, r }: { id: string; cx: number; cy: number; r: number }) {
  return (
    <radialGradient id={id} cx={cx} cy={cy} r={r} gradientUnits="userSpaceOnUse">
      {GAUSSIAN_STOPS.map((s) => (
        <stop key={s.offset} offset={s.offset} stopColor="#ffffff" stopOpacity={s.opacity} />
      ))}
    </radialGradient>
  );
}

/** Star only: collapsed sidebar, app icon, report stamp. */
export function SpicaMark({ className }: LogoProps) {
  const id = useId();
  return (
    <svg viewBox="0 0 32 32" className={className} role="img" aria-label="Spica">
      <defs>
        <Nucleus id={id} cx={11} cy={16} r={4.2} />
      </defs>
      <path fill="var(--color-azure)" d={MARK_STAR} />
      {/* Same shape filled with the gradient, so the core never spills outside the star. */}
      <path fill={`url(#${id})`} d={MARK_STAR} />
    </svg>
  );
}

/** Star plus wordmark: the star's long ray becomes the baseline of SPICA. */
export function SpicaLockup({ className }: LogoProps) {
  const id = useId();
  return (
    <svg viewBox="0 0 100 37" className={className} role="img" aria-label="Spica">
      <defs>
        <Nucleus id={id} cx={12} cy={24} r={4.6} />
      </defs>
      <path fill="var(--color-azure)" d={LOCKUP_STAR} />
      <path fill={`url(#${id})`} d={LOCKUP_STAR} />
      <text
        x="25"
        y="20.4"
        fill="var(--color-ink)"
        fontFamily="Sora, ui-sans-serif, system-ui, sans-serif"
        fontSize="14.5"
        fontWeight="600"
        letterSpacing="3"
      >
        SPICA
      </text>
    </svg>
  );
}
