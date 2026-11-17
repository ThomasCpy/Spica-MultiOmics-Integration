// Colour scales for heatmaps, from the art direction's tokens.
//
// Sequential: one hue for magnitudes (expression, signal), from the zero
// step (frost: "measured, nothing") through the four azure steps. On light
// more is darker and the top still contrasts on white; the dark theme
// re-steps the same tokens so more is brighter.
//
// Diverging: orange up, azure down, a neutral grey at zero, as the art
// direction sets for signed values. Never red against green.
//
// The steps are read from the tokens (index.css), so both themes come from
// one definition. A component that calls these also calls useTheme(), so it
// draws again when the theme changes.

import { currentTheme, token } from "./theme";

type RGB = [number, number, number];

const cache: Partial<Record<string, { seq: RGB[]; neutral: RGB; up: RGB; down: RGB }>> = {};

function rgb(hex: string, fallback = "#f5faff"): RGB {
  // The build minifies #0077cc to #07c, so both lengths are read; a token
  // the stylesheet lacks falls back rather than becoming NaN, which would
  // be no colour at all and white text on white.
  let h = (hex || fallback).trim().replace("#", "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const out = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return (out.some(Number.isNaN) ? rgb(fallback) : out) as RGB;
}

function steps() {
  const theme = currentTheme();
  cache[theme] ??= {
    seq: [0, 1, 2, 3, 4].map((i) => rgb(token(`seq-${i}`))),
    neutral: rgb(token("neutral")),
    up: rgb(token("up")),
    down: rgb(token("down")),
  };
  return cache[theme]!;
}

function mix(a: RGB, b: RGB, t: number): RGB {
  return [0, 1, 2].map((i) => Math.round(a[i] + (b[i] - a[i]) * t)) as RGB;
}

const css = ([r, g, b]: RGB) => `rgb(${r},${g},${b})`;

/** 0 to 1 onto the sequential ramp. */
export function sequential(t: number): string {
  const seq = steps().seq;
  const x = Math.min(1, Math.max(0, t)) * (seq.length - 1);
  const i = Math.min(seq.length - 2, Math.floor(x));
  return css(mix(seq[i], seq[i + 1], x - i));
}

/** -1 to 1 onto the diverging ramp. */
export function diverging(t: number): string {
  const { neutral, up, down } = steps();
  const x = Math.min(1, Math.max(-1, t));
  return css(x >= 0 ? mix(neutral, up, x) : mix(neutral, down, -x));
}

/** The text colour that reads on a sequential cell. */
export function textOn(t: number): string {
  const step = Math.min(4, Math.max(1, Math.round(Math.min(1, Math.max(0, t)) * 4)));
  return token(`on-seq-${step}`) || (t > 0.62 ? "#ffffff" : "#0b1b2b");
}
