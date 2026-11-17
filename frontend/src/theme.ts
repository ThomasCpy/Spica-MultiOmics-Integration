// Light, dark, or whatever Windows is set to. The choice is saved with the
// other settings (Python, settings.json); what applies is set on <html> as
// data-theme, which switches every colour token in index.css at once.
//
// Most of the interface needs nothing more: its colours are tokens. What
// computes colours in code (heatmap ramps, a canvas) calls useTheme(), so it
// draws again when the theme changes, without the view losing its state.

import { useEffect, useState } from "react";

export type ThemeChoice = "light" | "dark" | "system";
export type Theme = "light" | "dark";

const DARK = "(prefers-color-scheme: dark)";
let choice: ThemeChoice = "light";

function resolve(chosen: ThemeChoice): Theme {
  if (chosen !== "system") return chosen;
  return window.matchMedia?.(DARK).matches ? "dark" : "light";
}

/** Apply a choice now, and follow the system if that is the choice. */
export function applyTheme(chosen: ThemeChoice): void {
  choice = chosen;
  document.documentElement.dataset.theme = resolve(chosen);
}

// Windows switching between light and dark while Spica is open.
window.matchMedia?.(DARK).addEventListener?.("change", () => {
  if (choice === "system") applyTheme("system");
});

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

/** The theme in effect, re-rendering the caller when it changes. */
export function useTheme(): Theme {
  const [theme, setTheme] = useState<Theme>(currentTheme);
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(currentTheme()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return theme;
}

/** A colour token's value as the theme in effect sets it, for code that
 * cannot use var() (a canvas, interpolation). */
export function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(`--color-${name}`).trim();
}
