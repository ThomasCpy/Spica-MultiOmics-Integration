import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { Glance as GlanceData, GlanceBlock, GlanceWord } from "../report";

// The gene at a glance: the words its GO terms and its disease associations
// keep returning to, before any section is opened.
//
// A word map, kept honest. Size is the one encoding: the count of GO terms
// using a word, or the summed squared association score. The strongest
// words are also set in deep azure, a second cue rather than a second
// meaning. Placement means nothing: words are packed on a spiral from the
// centre, heaviest first, so the same gene always draws the same picture.
// Every figure is one hover away, every word opens the terms it came from,
// and the list view holds every word with its number.

const MIN_SIZE = 12;
const MAX_SIZE = 30;
// Wide gaps between words, so neighbours never read as one phrase; the
// joined phrases (spica/glance.py) are the only multi-word items.
const PAD_X = 8;
const PAD_Y = 1;
const HEIGHT = 200;
// The cloud is a summary; the list carries every word.
const CLOUD_WORDS = 60;
// Words under this share of the heaviest are left to the list: a word
// weighing a twenty-fifth of the top one adds clutter, not impression.
const CLOUD_FLOOR = 0.04;
const STEP = 50;

type View = "cloud" | "list";

export function Glance({ glance }: { glance: GlanceData }) {
  const [view, setView] = useState<View>("cloud");
  return (
    <section className="mb-5 rounded-[14px] border border-line bg-surface">
      <h2 className="flex items-center gap-2 border-b border-line px-5 py-3">
        <span className="text-[15px] font-semibold text-ink">At a glance</span>
        <span className="ml-auto flex items-center gap-1">
          <Toggle active={view === "cloud"} onClick={() => setView("cloud")}>
            words
          </Toggle>
          <Toggle active={view === "list"} onClick={() => setView("list")}>
            list
          </Toggle>
        </span>
      </h2>
      <div className="divide-y divide-line">
        <Block
          title="Function"
          block={glance.function}
          basis={(b) => count(b.terms, "GO term")}
          unit="GO terms"
          noun={["GO term uses", "GO terms use"]}
          view={view}
          describe={(w) => `${w.count} of ${glance.function.terms} GO terms`}
          sizeNote="Size: GO terms with the word."
        />
        <Block
          title="Disease"
          block={glance.disease}
          basis={(b) =>
            count(b.terms, "disease association") +
            (b.measurements ? `, ${count(b.measurements, "measurement")} left out` : "")
          }
          unit="score"
          noun={["disease uses", "diseases use"]}
          view={view}
          describe={(w) =>
            `${w.count.toLocaleString("en-US")} ${w.count === 1 ? "disease" : "diseases"}, strongest ${strongest(w)}`
          }
          sizeNote="Size: sum of squared association scores of diseases with the word."
        />
      </div>
    </section>
  );
}

function count(n: number, noun: string): string {
  return `${n.toLocaleString("en-US")} ${noun}${n === 1 ? "" : "s"}`;
}

function strongest(word: GlanceWord): string {
  const first = word.from[0];
  return Array.isArray(first) ? first[1].toFixed(2) : "";
}

function Block({
  title,
  block,
  basis,
  unit,
  noun,
  view,
  describe,
  sizeNote,
}: {
  title: string;
  block: GlanceBlock;
  basis: (b: GlanceBlock) => string;
  unit: string;
  noun: [string, string];
  view: View;
  describe: (w: GlanceWord) => string;
  sizeNote: string;
}) {
  const [selected, setSelected] = useState<GlanceWord | null>(null);
  useEffect(() => setSelected(null), [block]);

  return (
    <div className="px-5 py-4">
      <p className="flex flex-wrap items-baseline gap-x-2 text-[12px] text-slate">
        <span className="text-[13px] font-semibold text-ink">{title}</span>
        {block.words.length > 0 && <span>{basis(block)}</span>}
        {block.source && <span className="opacity-70">{block.source}</span>}
      </p>
      {block.words.length === 0 ? (
        <p className="mt-2 text-[13px] text-slate">{block.reason}</p>
      ) : view === "cloud" ? (
        <Cloud
          words={block.words}
          selected={selected}
          onSelect={(w) => setSelected(selected?.word === w.word ? null : w)}
          describe={describe}
          sizeNote={sizeNote}
        />
      ) : (
        <WordList
          words={block.words}
          unit={unit}
          onSelect={(w) => setSelected(selected?.word === w.word ? null : w)}
          selected={selected}
        />
      )}
      {selected && (
        <Evidence word={selected} noun={noun} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

// -- the cloud -------------------------------------------------------------

type Placed = {
  word: GlanceWord;
  x: number;
  y: number;
  w: number;
  h: number;
  size: number;
  tier: 0 | 1 | 2;
};

let canvas: HTMLCanvasElement | null = null;

function measure(text: string, size: number, weight: number): number {
  canvas ??= document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) return text.length * size * 0.6;
  ctx.font = `${weight} ${size}px Sora, ui-sans-serif, system-ui, sans-serif`;
  return ctx.measureText(text).width;
}

function tierOf(ratio: number): 0 | 1 | 2 {
  return ratio >= 0.5 ? 0 : ratio >= 0.2 ? 1 : 2;
}

/** Spiral packing, heaviest first. Deterministic: no random start, no
 * rotation, ties already broken by the backend's order. */
function pack(words: GlanceWord[], width: number, height: number): Placed[] {
  const max = words[0]?.weight || 1;
  const placed: Placed[] = [];
  const cx = width / 2;
  const cy = height / 2;
  const aspect = width / height;
  const overlaps = (a: Omit<Placed, "word" | "size" | "tier">) =>
    placed.some(
      (b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y,
    );
  for (const word of words.slice(0, CLOUD_WORDS)) {
    const ratio = word.weight / max;
    if (ratio < CLOUD_FLOOR) break;
    const tier = tierOf(ratio);
    const size = Math.round(MIN_SIZE + (MAX_SIZE - MIN_SIZE) * Math.sqrt(ratio));
    const w = measure(word.word, size, tier === 0 ? 600 : 400) + PAD_X * 2;
    const h = size * 1.08 + PAD_Y * 2;
    if (w > width) continue;
    for (let t = 0; t < 1400; t += 0.07) {
      const radius = 1.1 * t;
      const x = cx + radius * Math.cos(t) * Math.min(aspect, 3) * 0.55 - w / 2;
      const y = cy + radius * Math.sin(t) * 0.55 - h / 2;
      if (x < 0 || y < 0 || x + w > width || y + h > height) {
        if (radius > width) break;
        continue;
      }
      const box = { x, y, w, h };
      if (!overlaps(box)) {
        placed.push({ word, size, tier, ...box });
        break;
      }
    }
  }
  return placed;
}

const TIER_CLASS = ["fill-azure-deep", "fill-ink", "fill-slate"] as const;

function Cloud({
  words,
  selected,
  onSelect,
  describe,
  sizeNote,
}: {
  words: GlanceWord[];
  selected: GlanceWord | null;
  onSelect: (w: GlanceWord) => void;
  describe: (w: GlanceWord) => string;
  sizeNote: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [fontsReady, setFontsReady] = useState(false);
  const [hover, setHover] = useState<Placed | null>(null);

  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return;
    setWidth(element.clientWidth);
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  // Widths are measured in Sora; measured before it loads, they would be
  // the fallback font's and the words would overlap once it arrives.
  useEffect(() => {
    let live = true;
    document.fonts.ready.then(() => live && setFontsReady(true));
    return () => {
      live = false;
    };
  }, []);

  const placed = useMemo(
    () => (width && fontsReady ? pack(words, width, HEIGHT) : []),
    [words, width, fontsReady],
  );
  const hidden = words.length - placed.length;

  return (
    <figure className="m-0 mt-2">
      <div ref={box} className="relative" style={{ height: HEIGHT }}>
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={`Most frequent words: ${words
            .slice(0, 12)
            .map((w) => w.word)
            .join(", ")}`}
        >
          {placed.map((p) => {
            const active = selected?.word === p.word.word;
            return (
              <g
                key={p.word.word}
                className="cursor-pointer"
                onClick={() => onSelect(p.word)}
                onMouseEnter={() => setHover(p)}
                onMouseLeave={() => setHover(null)}
              >
                <rect
                  x={p.x}
                  y={p.y}
                  width={p.w}
                  height={p.h}
                  rx={6}
                  className={active ? "fill-mist" : "fill-transparent"}
                />
                <text
                  x={p.x + PAD_X}
                  y={p.y + p.h / 2}
                  dominantBaseline="central"
                  fontSize={p.size}
                  fontWeight={p.tier === 0 ? 600 : 400}
                  className={`${TIER_CLASS[p.tier]} select-none`}
                  textDecoration={hover?.word.word === p.word.word ? "underline" : undefined}
                >
                  {p.word.word}
                </text>
              </g>
            );
          })}
        </svg>
        {hover && (
          <div
            role="tooltip"
            className="pointer-events-none absolute z-10 whitespace-nowrap rounded-[8px] border border-line bg-surface px-2.5 py-1.5 text-[12px] text-ink"
            style={{
              left: Math.min(Math.max(hover.x, 0), Math.max(width - 260, 0)),
              top: hover.y + hover.h + 4 > HEIGHT - 30 ? hover.y - 32 : hover.y + hover.h + 4,
            }}
          >
            <span className="font-semibold">{hover.word.word}</span>
            <span className="ml-1.5 text-slate">{describe(hover.word)}</span>
          </div>
        )}
      </div>
      <figcaption className="mt-1 flex flex-wrap gap-x-3 text-[11px] text-slate">
        <span>{sizeNote}</span>
        {hidden > 0 && (
          <span>
            {placed.length} of {words.length.toLocaleString("en-US")} words drawn; all in the list.
          </span>
        )}
      </figcaption>
    </figure>
  );
}

// -- the list --------------------------------------------------------------

function WordList({
  words,
  unit,
  selected,
  onSelect,
}: {
  words: GlanceWord[];
  unit: string;
  selected: GlanceWord | null;
  onSelect: (w: GlanceWord) => void;
}) {
  const [count, setCount] = useState(STEP);
  const max = words[0]?.weight || 1;
  const weighted = Array.isArray(words[0]?.from[0]);
  // Disease words add a column for how many diseases use them.
  const cols = weighted
    ? "grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto_auto]"
    : "grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]";
  return (
    <div className="mt-2">
      <div className={`grid ${cols} gap-x-3 border-b border-line px-1 pb-1 text-[11px] text-slate`}>
        <span>Word</span>
        <span />
        <span className="w-[64px] text-right">{weighted ? "weight" : unit}</span>
        {weighted && <span className="w-[64px] text-right">diseases</span>}
      </div>
      <ul className="mt-1 space-y-[3px]">
        {words.slice(0, count).map((word) => (
          <li key={word.word}>
            <button
              type="button"
              onClick={() => onSelect(word)}
              className={`grid w-full ${cols} items-center gap-x-3 rounded-[6px] px-1 text-left text-[12px] transition-colors hover:bg-frost ${
                selected?.word === word.word ? "bg-mist" : ""
              }`}
            >
              <span className="truncate text-ink">{word.word}</span>
              <span className="block h-[7px] rounded-full bg-mist">
                <span
                  className="block h-full rounded-r-[4px] bg-azure"
                  style={{ width: `${Math.max(1, (word.weight / max) * 100)}%` }}
                />
              </span>
              <span className="w-[64px] text-right font-mono tabular-nums text-ink">
                {weighted ? word.weight.toFixed(3) : word.weight}
              </span>
              {weighted && (
                <span className="w-[64px] text-right font-mono tabular-nums text-slate">
                  {word.count}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-2 flex gap-4 text-[12px]">
        {words.length > count && (
          <button
            type="button"
            onClick={() => setCount(count + STEP)}
            className="text-azure-deep hover:underline"
          >
            Show {Math.min(STEP, words.length - count)} more (
            {(words.length - count).toLocaleString("en-US")} left)
          </button>
        )}
        {words.length > count && (
          <button
            type="button"
            onClick={() => setCount(words.length)}
            className="text-azure-deep hover:underline"
          >
            Show all {words.length.toLocaleString("en-US")}
          </button>
        )}
        {count > STEP && (
          <button
            type="button"
            onClick={() => setCount(STEP)}
            className="text-azure-deep hover:underline"
          >
            Show the first {STEP}
          </button>
        )}
      </div>
    </div>
  );
}

// -- what a word stands for ------------------------------------------------

function Evidence({
  word,
  noun,
  onClose,
}: {
  word: GlanceWord;
  noun: [string, string];
  onClose: () => void;
}) {
  const [count, setCount] = useState(STEP);
  const items = word.from;
  return (
    <div className="mt-3 rounded-[10px] bg-frost px-4 py-3">
      <p className="flex items-baseline gap-2 text-[12px] text-slate">
        <span>
          {items.length.toLocaleString("en-US")} {items.length === 1 ? noun[0] : noun[1]}{" "}
          <span className="font-semibold text-ink">{word.word}</span>
        </span>
        <button
          type="button"
          onClick={onClose}
          className="ml-auto text-azure-deep hover:underline"
        >
          Close
        </button>
      </p>
      <ul className="mt-2 space-y-[3px] text-[12px]">
        {items.slice(0, count).map((item) => {
          const [text, score] = Array.isArray(item) ? item : [item, null];
          return (
            <li key={text} className="flex items-baseline gap-3">
              <span className="min-w-0 flex-1 text-ink">{text}</span>
              {score !== null && (
                <span className="font-mono tabular-nums text-slate">{score.toFixed(3)}</span>
              )}
            </li>
          );
        })}
      </ul>
      {items.length > count && (
        <button
          type="button"
          onClick={() => setCount(items.length)}
          className="mt-2 text-[12px] text-azure-deep hover:underline"
        >
          Show all {items.length.toLocaleString("en-US")}
        </button>
      )}
    </div>
  );
}

function Toggle({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full px-2 py-0.5 text-[11px] transition-colors ${
        active ? "bg-mist text-azure-deep" : "text-slate hover:text-azure-deep"
      }`}
    >
      {children}
    </button>
  );
}
