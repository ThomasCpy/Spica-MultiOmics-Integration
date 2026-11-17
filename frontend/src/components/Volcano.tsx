import { useEffect, useMemo, useRef, useState } from "react";
import type { DePoint } from "../geo";
import { token, useTheme } from "../theme";

// Volcano plot: log2 fold change across, -log10 p up. Tens of thousands of
// genes, so the points go on a canvas; axes, thresholds and gene names are
// SVG over it. Orange up, azure down, slate not significant. Colour never
// carries meaning alone: the legend counts each call, the strongest genes
// carry their names, and the table under the plot lists them.

const HEIGHT = 420;
const M = { top: 14, right: 18, bottom: 42, left: 54 };
/** Hover grid cell, and the farthest a point may be from the pointer, in px. */
const CELL = 12;
const LABELS_PER_SIDE = 5;

export type Call = "up" | "down" | "ns";

export function callOf(p: DePoint, alpha: number, fold: number): Call {
  if (p[4] === null || p[4] > alpha || Math.abs(p[3]) < fold) return "ns";
  return p[3] > 0 ? "up" : "down";
}

/** -log10 p; a p reported as 0 sits at the top of the scale. */
const height = (p: number) => -Math.log10(Math.max(p, 1e-300));

function ticks(max: number, count: number): number[] {
  const raw = max / count;
  const step = [1, 2, 5, 10, 20, 50, 100].find((s) => s >= raw) ?? Math.ceil(raw / 100) * 100;
  const out = [];
  for (let v = 0; v <= max + 1e-9; v += step) out.push(v);
  return out;
}

export function Volcano({
  points,
  alpha,
  fold,
  highlight,
  pLabel,
  onPick,
}: {
  points: DePoint[];
  alpha: number;
  fold: number;
  highlight: string;
  pLabel: string;
  onPick?: (label: string) => void;
}) {
  const theme = useTheme(); // the canvas does not follow tokens: draw again
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const grid = useRef<Map<string, number[]>>(new Map());
  const [width, setWidth] = useState(760);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const node = wrap.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(320, Math.floor(entry.contentRect.width))));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const scale = useMemo(() => {
    const ys = points.map((p) => (p[4] === null ? NaN : height(p[4])));
    const top = Math.max(height(alpha) + 1, ...ys.filter((y) => Number.isFinite(y)));
    const yMax = ticks(top * 1.04, 5).at(-1) ?? top;
    const abs = points.map((p) => Math.abs(p[3])).sort((a, b) => a - b);
    // A few low-count genes reach |log2FC| 20 and would flatten the rest:
    // the axis stops at the 99.9th percentile, and those genes sit on its edge.
    const q = abs.length ? abs[Math.min(abs.length - 1, Math.floor(abs.length * 0.999))] : 1;
    const xLim = Math.max(Math.ceil(fold) + 1, Math.ceil(q * 1.05));
    const clipped = abs.filter((a) => a > xLim).length;
    return { ys, yMax, xLim, clipped };
  }, [points, alpha, fold]);

  const plotW = width - M.left - M.right;
  const plotH = HEIGHT - M.top - M.bottom;
  const sx = (v: number) => M.left + ((Math.max(-scale.xLim, Math.min(scale.xLim, v)) + scale.xLim) / (2 * scale.xLim)) * plotW;
  const sy = (v: number) => M.top + (1 - Math.min(v, scale.yMax) / scale.yMax) * plotH;

  const calls = useMemo(() => points.map((p) => callOf(p, alpha, fold)), [points, alpha, fold]);

  useEffect(() => {
    const node = canvas.current;
    if (!node) return;
    const ratio = window.devicePixelRatio || 1;
    node.width = Math.round(width * ratio);
    node.height = Math.round(HEIGHT * ratio);
    const ctx = node.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, HEIGHT);
    const colour: Record<Call, string> = { ns: token("slate"), up: token("up"), down: token("down") };
    const index = new Map<string, number[]>();
    // Not significant first, so the calls draw on top.
    for (const pass of ["ns", "sig"] as const) {
      ctx.globalAlpha = pass === "ns" ? 0.3 : 0.9;
      for (let i = 0; i < points.length; i++) {
        const y = scale.ys[i];
        if (!Number.isFinite(y) && !(points[i][4] === 0)) continue;
        const c = calls[i];
        if ((pass === "ns") !== (c === "ns")) continue;
        const px = sx(points[i][3]);
        const py = sy(Number.isFinite(y) ? y : scale.yMax);
        ctx.fillStyle = colour[c];
        ctx.beginPath();
        if (Math.abs(points[i][3]) > scale.xLim) {
          // Beyond the axis: a triangle on the edge, pointing out.
          const s = points[i][3] > 0 ? 1 : -1;
          ctx.moveTo(px + s * 4, py);
          ctx.lineTo(px - s * 2, py - 3.5);
          ctx.lineTo(px - s * 2, py + 3.5);
          ctx.closePath();
        } else ctx.arc(px, py, c === "ns" ? 1.6 : 2.4, 0, Math.PI * 2);
        ctx.fill();
        const key = `${Math.floor(px / CELL)},${Math.floor(py / CELL)}`;
        const bucket = index.get(key);
        if (bucket) bucket.push(i);
        else index.set(key, [i]);
      }
    }
    ctx.globalAlpha = 1;
    grid.current = index;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, scale, calls, width, theme]);

  const labels = useMemo(() => {
    const order = (side: Call) =>
      points
        .map((p, i) => [p, i] as const)
        .filter(([, i]) => calls[i] === side)
        .sort((a, b) => (a[0][4] ?? 1) - (b[0][4] ?? 1) || Math.abs(b[0][3]) - Math.abs(a[0][3]))
        .slice(0, LABELS_PER_SIDE)
        .map(([, i]) => i);
    const wanted = highlight.trim().toUpperCase();
    const marked = wanted ? points.findIndex((p) => p[0].toUpperCase() === wanted || p[1].toUpperCase() === wanted) : -1;
    const chosen = [...(marked >= 0 ? [marked] : []), ...order("up"), ...order("down")].filter(
      (i, k, all) => all.indexOf(i) === k,
    );
    const at = (i: number) => {
      const y = scale.ys[i];
      return [sx(points[i][3]), sy(Number.isFinite(y) ? y : scale.yMax)] as const;
    };
    // Every chosen gene's ring is an obstacle for the other genes' names.
    const rings = chosen.map((i) => {
      const [px, py] = at(i);
      return { i, x: px - 6, y: py, w: 12 };
    });
    const boxes: { i: number; x: number; y: number; w: number }[] = [];
    const out: { i: number; x: number; y: number; anchor: "start" | "end"; marked: boolean }[] = [];
    for (const i of chosen) {
      const [px, py] = at(i);
      const w = points[i][0].length * 6.2 + 4;
      for (const anchor of px > M.left + plotW - w - 10 ? (["end", "start"] as const) : (["start", "end"] as const)) {
        const x0 = anchor === "start" ? px + 5 : px - 5 - w;
        const clash = [...boxes, ...rings].some(
          (b) => b.i !== i && Math.abs(b.y - py) < 12 && x0 < b.x + b.w && x0 + w > b.x,
        );
        if (!clash && x0 > M.left && x0 + w < width - 2) {
          boxes.push({ i, x: x0, y: py, w });
          out.push({ i, x: anchor === "start" ? px + 5 : px - 5, y: py, anchor, marked: i === marked });
          break;
        }
      }
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, calls, scale, width, highlight]);

  const nearest = (mx: number, my: number): number | null => {
    const gx = Math.floor(mx / CELL);
    const gy = Math.floor(my / CELL);
    let best: number | null = null;
    let bestD = CELL * CELL;
    for (let dx = -1; dx <= 1; dx++)
      for (let dy = -1; dy <= 1; dy++)
        for (const i of grid.current.get(`${gx + dx},${gy + dy}`) ?? []) {
          const y = scale.ys[i];
          const d = (sx(points[i][3]) - mx) ** 2 + (sy(Number.isFinite(y) ? y : scale.yMax) - my) ** 2;
          if (d < bestD) {
            bestD = d;
            best = i;
          }
        }
    return best;
  };

  const xTicks = ticks(scale.xLim, 4).flatMap((v) => (v === 0 ? [0] : [-v, v])).sort((a, b) => a - b);
  const yTicks = ticks(scale.yMax, 5);
  const threshold = height(alpha);
  const hovered = hover !== null ? points[hover] : null;
  const hx = hovered ? sx(hovered[3]) : 0;
  const hy = hovered ? sy(Number.isFinite(scale.ys[hover!]) ? scale.ys[hover!] : scale.yMax) : 0;

  return (
    <div ref={wrap} className="relative w-full">
      <canvas ref={canvas} className="pointer-events-none absolute left-0 top-0" style={{ width, height: HEIGHT }} />
      <svg
        width={width}
        height={HEIGHT}
        className="relative block"
        role="img"
        aria-label={`Volcano plot of ${points.length.toLocaleString("en-US")} genes: log2 fold change against -log10 ${pLabel}`}
        onPointerMove={(e) => {
          const box = e.currentTarget.getBoundingClientRect();
          setHover(nearest(e.clientX - box.left, e.clientY - box.top));
        }}
        onPointerLeave={() => setHover(null)}
        onClick={() => hovered && onPick?.(hovered[0])}
        style={{ cursor: hovered && onPick ? "pointer" : "default" }}
      >
        {yTicks.map((v) => (
          <g key={`y${v}`}>
            <line x1={M.left} x2={width - M.right} y1={sy(v)} y2={sy(v)} className="stroke-line" />
            <text x={M.left - 6} y={sy(v) + 3} textAnchor="end" className="fill-slate font-mono text-[10px]">
              {v}
            </text>
          </g>
        ))}
        {xTicks.map((v) => (
          <g key={`x${v}`}>
            <line x1={sx(v)} x2={sx(v)} y1={M.top} y2={M.top + plotH} className={v === 0 ? "stroke-edge" : "stroke-line"} />
            <text x={sx(v)} y={M.top + plotH + 14} textAnchor="middle" className="fill-slate font-mono text-[10px]">
              {v}
            </text>
          </g>
        ))}
        <line x1={M.left} x2={width - M.right} y1={sy(threshold)} y2={sy(threshold)} className="stroke-slate" strokeDasharray="3 3" />
        {fold > 0 &&
          [-fold, fold].map((v) => (
            <line key={`f${v}`} x1={sx(v)} x2={sx(v)} y1={M.top} y2={M.top + plotH} className="stroke-slate" strokeDasharray="3 3" />
          ))}
        <text x={M.left + plotW / 2} y={HEIGHT - 6} textAnchor="middle" className="fill-slate text-[11px]">
          log2 fold change
        </text>
        <text transform={`translate(13 ${M.top + plotH / 2}) rotate(-90)`} textAnchor="middle" className="fill-slate text-[11px]">
          -log10 {pLabel}
        </text>
        {labels.map((l) => (
          <g key={`l${l.i}`}>
            <circle cx={l.anchor === "start" ? l.x - 5 : l.x + 5} cy={l.y} r={l.marked ? 5 : 3.5} fill="none" className="stroke-ink" strokeWidth={l.marked ? 1.5 : 1} />
            <text x={l.x} y={l.y + 3.5} textAnchor={l.anchor} className={`fill-ink font-mono text-[10px] ${l.marked ? "font-semibold" : ""}`}>
              {points[l.i][0]}
            </text>
          </g>
        ))}
        {hovered && <circle cx={hx} cy={hy} r={6} fill="none" className="stroke-ink" strokeWidth={1.5} />}
      </svg>
      {hovered && (
        <div
          className="pointer-events-none absolute z-10 rounded-[10px] border border-line bg-surface px-3 py-2 text-[11px] shadow-[0_6px_18px_rgb(11_27_43/0.12)]"
          style={{ left: Math.min(hx + 12, width - 200), top: Math.max(0, hy - 64) }}
        >
          <p className="font-mono text-[12px] font-semibold text-ink">{hovered[0]}</p>
          {hovered[1] && hovered[1] !== hovered[0] && <p className="font-mono text-slate">{hovered[1]}</p>}
          <p className="text-slate">
            log2 fold change <span className="font-mono text-ink">{hovered[3]}</span>
          </p>
          <p className="text-slate">
            {pLabel} <span className="font-mono text-ink">{hovered[4] === 0 ? "< 1e-300" : hovered[4]}</span>
          </p>
          {hovered[2] !== null && (
            <p className="text-slate">
              mean <span className="font-mono text-ink">{hovered[2]}</span>
            </p>
          )}
        </div>
      )}
      {scale.clipped > 0 && (
        <p className="mt-1 text-[11px] text-slate">
          Triangles: {scale.clipped} {scale.clipped === 1 ? "gene" : "genes"} beyond ±{scale.xLim} log2 fold change, on the edge.
        </p>
      )}
    </div>
  );
}
