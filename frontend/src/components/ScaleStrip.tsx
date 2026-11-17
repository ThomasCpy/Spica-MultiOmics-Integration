// One value on its scale.
//
// A tau of 0.992 has little meaning without 0.15 and 0.85 beside it. A fold
// of 1,172 has little meaning without 1 and 10. This draws the scale, the
// named bands of the measure, and the value as a marker with its figure. It
// is a meter, not a chart: one value, so no axis title and no legend.
//
// Bands are pale track segments with a surface gap between them. The band
// of the value takes the low azure step, so its label and its shade both
// carry the reading in grayscale.

export type Band = { from: number; to: number; label: string };

export function ScaleStrip({
  caption,
  value,
  display,
  domain,
  log = false,
  bands = [],
  ticks = [],
  note,
}: {
  caption: string;
  value: number;
  display: string;
  domain: [number, number];
  log?: boolean;
  bands?: Band[];
  ticks?: { at: number; label: string }[];
  note?: string;
}) {
  const [low, high] = domain;
  const scale = (x: number) => {
    const clamped = Math.min(Math.max(x, low), high);
    const raw = log
      ? (Math.log10(clamped) - Math.log10(low)) / (Math.log10(high) - Math.log10(low))
      : (clamped - low) / (high - low);
    return Math.min(100, Math.max(0, raw * 100));
  };
  const at = scale(value);
  const active = bands.find((band) => value >= band.from && value < band.to) ??
    (bands.length && value >= bands[bands.length - 1].to ? bands[bands.length - 1] : undefined);
  // Keep the figure inside the strip at either end.
  const anchor = at < 6 ? "translate-x-0" : at > 94 ? "-translate-x-full" : "-translate-x-1/2";

  return (
    <figure className="m-0">
      <figcaption className="mb-1 text-[12px] text-slate">{caption}</figcaption>
      <div className="relative pt-6">
        <span
          className={`absolute top-0 ${anchor} font-mono text-[13px] font-medium tabular-nums text-ink`}
          style={{ left: `${at}%` }}
        >
          {display}
        </span>
        <div className="relative h-[10px]">
          {bands.length ? (
            bands.map((band) => {
              const left = scale(band.from);
              const right = scale(band.to);
              return (
                <span
                  key={band.label}
                  className={`absolute top-0 h-full rounded-[3px] ${
                    band === active ? "bg-seq-1" : "bg-mist"
                  }`}
                  // The 2px surface gap between segments, as on any stack.
                  style={{ left: `calc(${left}% + 1px)`, width: `calc(${right - left}% - 2px)` }}
                />
              );
            })
          ) : (
            <span className="absolute inset-0 rounded-full bg-mist" />
          )}
          <span
            className="absolute top-1/2 size-[14px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface bg-azure-deep"
            style={{ left: `${at}%` }}
            title={`${caption}: ${display}`}
          />
        </div>
        {bands.length > 0 && (
          // Each label stays inside the width of its band and wraps there.
          // When a band is too narrow for its longest word, the labels go on
          // two staggered rows, centred on their bands, so neighbours never
          // overlap.
          <div className="relative mt-1.5 h-[30px] text-[11px] leading-tight">
            {(() => {
              const narrow = bands.some((band) => {
                const width = scale(band.to) - scale(band.from);
                const longest = Math.max(...band.label.split(" ").map((w) => w.length));
                return width < longest * 1.25;
              });
              return bands.map((band, index) => {
                const left = scale(band.from);
                const right = scale(band.to);
                const tone = band === active ? "text-ink" : "text-slate";
                return narrow ? (
                  <span
                    key={band.label}
                    className={`absolute -translate-x-1/2 whitespace-nowrap ${tone}`}
                    style={{ left: `${(left + right) / 2}%`, top: index % 2 ? 15 : 0 }}
                  >
                    {band.label}
                  </span>
                ) : (
                  <span
                    key={band.label}
                    className={`absolute px-0.5 text-center ${tone}`}
                    style={{ left: `${left}%`, width: `${right - left}%` }}
                  >
                    {band.label}
                  </span>
                );
              });
            })()}
          </div>
        )}
        {ticks.length > 0 && (
          <div className="relative mt-1.5 h-4 font-mono text-[11px] text-slate">
            {ticks.map((tick, index) => (
              <span
                key={tick.label}
                className={`absolute whitespace-nowrap ${
                  index === 0 ? "" : index === ticks.length - 1 ? "-translate-x-full" : "-translate-x-1/2"
                }`}
                style={{ left: `${scale(tick.at)}%` }}
              >
                {tick.label}
              </span>
            ))}
          </div>
        )}
      </div>
      {note && <p className="mt-2 text-[11px] leading-relaxed text-slate">{note}</p>}
    </figure>
  );
}

/** Powers of ten from 1 up to the first one at or above `value`, at least 10,000. */
export function decades(value: number): { domain: [number, number]; ticks: { at: number; label: string }[] } {
  const top = Math.max(4, Math.ceil(Math.log10(Math.max(value, 1)) + 0.15));
  const ticks = Array.from({ length: top + 1 }, (_, power) => {
    const at = 10 ** power;
    return { at, label: `${at.toLocaleString("en-US")}×` };
  });
  return { domain: [1, 10 ** top], ticks };
}
