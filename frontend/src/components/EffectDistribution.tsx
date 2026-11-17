import type { GeneRecord } from "../bridge";

// The DepMap gene effect across all screened cell lines, as a histogram.
// 0 is no effect; -1 is the median of the common essential genes. The chart
// draws and names the two reference lines, so the shape reads with no
// legend: a peak near 0 is a dispensable gene, a peak past -1 a needed one.

const WIDTH = 640;
const HEIGHT = 150;
const PAD = { left: 36, right: 12, top: 18, bottom: 28 };
const LOW = -3;
const HIGH = 1;

export function EffectDistribution({ record }: { record: GeneRecord }) {
  const field = record.fields.depmap_effect_distribution;
  if (!field || field.state || typeof field.value !== "object" || !field.value) return null;
  const bins = Object.entries(field.value as Record<string, number>)
    .map(([edge, count]) => ({ edge: Number(edge), count }))
    .sort((a, b) => a.edge - b.edge);
  const top = Math.max(...bins.map((bin) => bin.count), 1);
  const total = bins.reduce((sum, bin) => sum + bin.count, 0);
  const plotW = WIDTH - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const x = (value: number) => PAD.left + ((value - LOW) / (HIGH - LOW)) * plotW;
  const barW = plotW / bins.length;
  const mean = record.fields.depmap_mean_effect;

  return (
    <div className="border-t border-line px-5 py-4">
      <p className="mb-2 text-[12px] text-slate">
        Gene effect, {total.toLocaleString("en-US")} cell lines, DepMap. Bar: lines per 0.1 band; end bands
        include values beyond -3 and 1.
        {!mean?.state && typeof mean?.value === "number" && (
          <>
            {" "}
            Mean <span className="font-mono text-ink">{mean.value.toFixed(2)}</span>.
          </>
        )}
      </p>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full max-w-[680px]" role="img"
        aria-label={`Histogram of gene effect over ${total} lines`}>
        <line x1={PAD.left} x2={WIDTH - PAD.right} y1={HEIGHT - PAD.bottom} y2={HEIGHT - PAD.bottom}
          stroke="var(--color-line)" />
        {bins.map((bin) => {
          const h = (bin.count / top) * plotH;
          return (
            <rect key={bin.edge} x={x(bin.edge) + 1} y={HEIGHT - PAD.bottom - h} width={Math.max(barW - 2, 1)}
              height={h} rx={h > 4 ? 2 : 0} fill="var(--color-azure)">
              <title>{`${bin.edge.toFixed(1)} to ${(bin.edge + 0.1).toFixed(1)}: ${bin.count} lines`}</title>
            </rect>
          );
        })}
        {[
          { at: 0, label: "no effect" },
          { at: -1, label: "common essential median" },
        ].map((mark) => (
          <g key={mark.at}>
            <line x1={x(mark.at)} x2={x(mark.at)} y1={PAD.top - 6} y2={HEIGHT - PAD.bottom}
              stroke="var(--color-slate)" strokeDasharray="3 3" />
            <text x={x(mark.at) + 4} y={PAD.top - 8} fontSize="10" fill="var(--color-slate)">{mark.label}</text>
          </g>
        ))}
        {[-3, -2, -1, 0, 1].map((tick) => (
          <text key={tick} x={x(tick)} y={HEIGHT - 10} fontSize="10" textAnchor="middle"
            fill="var(--color-slate)" fontFamily="JetBrains Mono, monospace">{tick}</text>
        ))}
        <text x={PAD.left - 6} y={PAD.top + 4} fontSize="10" textAnchor="end" fill="var(--color-slate)"
          fontFamily="JetBrains Mono, monospace">{top}</text>
      </svg>
    </div>
  );
}
