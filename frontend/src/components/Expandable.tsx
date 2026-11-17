import { useState } from "react";

// A long value, shown short.
//
// The rule it keeps: **a view can abbreviate, it can never truncate.** All
// measured data stays one click away. A "+46 more" that does not open hides
// data that the record holds. A sourced record exists to prevent this.

const DEFAULT_ITEMS = 8;

export type Entry = [string, unknown];

/** Entries of a map or list value, longest-first for numbers. */
export function entriesOf(value: unknown): Entry[] {
  if (Array.isArray(value)) return value.map((item, i) => [String(i), item]);
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    const numeric = entries.every(([, v]) => typeof v === "number");
    return numeric
      ? entries.sort((a, b) => (b[1] as number) - (a[1] as number))
      : entries;
  }
  return [];
}

export function ExpandableValue({
  value,
  limit = DEFAULT_ITEMS,
  mono = false,
}: {
  value: unknown;
  limit?: number;
  mono?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const entries = entriesOf(value);

  if (!entries.length) {
    return <span className={mono ? "font-mono" : ""}>{String(value ?? "")}</span>;
  }

  const isList = Array.isArray(value);
  const shown = open ? entries : entries.slice(0, limit);
  const hidden = entries.length - shown.length;

  return (
    <span className={mono ? "font-mono" : ""}>
      {shown
        .map(([key, item]) => (isList ? String(item) : `${key} ${item}`))
        .join(", ")}
      {hidden > 0 && (
        <>
          {", "}
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="font-sans text-[12px] text-azure-deep transition-colors hover:underline"
          >
            +{hidden} more
          </button>
        </>
      )}
      {open && entries.length > limit && (
        <>
          {" "}
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="font-sans text-[12px] text-slate transition-colors hover:underline"
          >
            show fewer
          </button>
        </>
      )}
    </span>
  );
}
