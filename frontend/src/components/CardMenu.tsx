import { useEffect, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Columns3,
  Database,
  FileText,
  FlaskConical,
  Globe,
  LayoutGrid,
  ListOrdered,
  MessagesSquare,
  Newspaper,
  Plus,
  Radar,
  Settings as SettingsIcon,
  type LucideIcon,
} from "lucide-react";
import { SpicaLockup } from "./SpicaLogo";
import type { ViewId } from "./Sidebar";
import type { AppStatus } from "../report";

// Card menu (Settings, Appearance, Main menu). One card at a time, large;
// the previous and next cards show at the edges, turned away and shaded.
// The options of the card in front unfold when it arrives. Arrows, wheel,
// keys (left, right, 1 to 9, Enter, first letters) and the edge cards move
// the selection.

type Item = { label: string; meta?: string; mono?: boolean; go: () => void };
type Card = { id: ViewId; title: string; description: string; icon: LucideIcon; figure?: string; items: Item[] };

export function CardMenu({
  status,
  onSelect,
  onOpenReport,
  onCompare,
}: {
  status: AppStatus | null;
  onSelect: (id: ViewId) => void;
  onOpenReport: (symbol: string) => void;
  onCompare: (genes: string) => void;
}) {
  const recent = status?.recent ?? [];
  const local = status?.local.length ?? 0;
  const total = status?.sources ?? 0;
  const [gene, setGene] = useState("");

  const cards: Card[] = [
    {
      id: "new", title: "New report", icon: Plus, description: "Gene record from all local sources.",
      figure: recent.length ? `${recent.length} recent` : undefined,
      items: [
        ...recent.slice(0, 5).map((r) => ({ label: r.symbol, meta: r.date, mono: true, go: () => onOpenReport(r.symbol) })),
        ...(recent.length > 5 ? [{ label: `All ${recent.length} reports`, go: () => onSelect("reports") }] : []),
      ],
    },
    {
      id: "compare", title: "Compare", icon: Columns3, description: "Two to six genes, side by side.",
      items: recent.length >= 2
        ? [{ label: `${recent[0].symbol}, ${recent[1].symbol}`, meta: "last two reports", mono: true, go: () => onCompare(`${recent[0].symbol}, ${recent[1].symbol}`) }]
        : [],
    },
    { id: "ask", title: "Ask", icon: MessagesSquare, description: "Questions on documents and records. Citations checked in code.", items: [] },
    { id: "intel", title: "Intelligence", icon: Radar, description: "Papers, patents and clinical trials by topic.", items: [] },
    { id: "digest", title: "Digest", icon: Newspaper, description: "Podcast transcripts, trials and papers.", items: [] },
    { id: "datasets", title: "Datasets", icon: FlaskConical, description: "GEO series: samples, tracks, gene values.", items: [] },
    { id: "reports", title: "Reports", icon: FileText, description: "Exported and built reports.", items: [] },
    { id: "candidates", title: "Candidates", icon: ListOrdered, description: "Ranked target lists.", items: [] },
    {
      id: "databases", title: "Databases", icon: Database, description: "Local mirror, by source.",
      figure: total ? `${local} of ${total} sources local` : undefined, items: [],
    },
  ];
  const n = cards.length;
  const [at, setAt] = useState(0);
  const wheelAt = useRef(0);

  const go = (step: number) => setAt((i) => (i + step + n) % n);

  const typed = useRef({ text: "", time: 0 });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "ArrowLeft") go(-1);
      else if (e.key === "ArrowRight") go(1);
      else if (e.key === "Enter" && !(e.target instanceof HTMLButtonElement)) onSelect(cards[atRef.current].id);
      else if (/^[1-9]$/.test(e.key) && Number(e.key) <= n) setAt(Number(e.key) - 1);
      else if (/^[a-z]$/i.test(e.key)) {
        const now = performance.now();
        typed.current = { text: (now - typed.current.time < 900 ? typed.current.text : "") + e.key.toLowerCase(), time: now };
        const match = cards.findIndex((card) => card.title.toLowerCase().startsWith(typed.current.text));
        if (match >= 0) setAt(match);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [n]);
  const atRef = useRef(at);
  atRef.current = at;

  const offset = (i: number) => {
    let d = i - at;
    if (d > n / 2) d -= n;
    if (d < -n / 2) d += n;
    return d;
  };

  return (
    <div className="flex min-h-full flex-col">
      <header className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 px-8 pt-5">
        <StatusPill status={status} />
        <SpicaLockup className="h-14 w-auto" />
        <button
          type="button"
          onClick={() => onSelect("settings")}
          aria-label="Settings"
          className="justify-self-end grid size-11 place-items-center rounded-full border border-line bg-surface text-ink transition-colors hover:border-azure hover:text-azure-deep"
        >
          <SettingsIcon size={18} strokeWidth={1.75} aria-hidden="true" />
        </button>
      </header>

      <div
        className="relative mx-auto mt-4 h-[470px] w-full max-w-[1280px] overflow-hidden [perspective:1600px]"
        onWheel={(e) => {
          const now = performance.now();
          if (now - wheelAt.current < 420 || Math.abs(e.deltaX) + Math.abs(e.deltaY) < 12) return;
          wheelAt.current = now;
          go((Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY) > 0 ? 1 : -1);
        }}
      >
        {cards.map((card, i) => {
          const d = offset(i);
          const side = Math.abs(d) === 1;
          const shown = d === 0 || side;
          const Icon = card.icon;
          return (
            <div
              key={card.id}
              aria-hidden={d !== 0}
              className="absolute left-1/2 top-1/2 h-[420px] w-[min(600px,78%)] transition-[transform,opacity] duration-500 [transition-timing-function:cubic-bezier(0.2,0.8,0.2,1)]"
              style={{
                // Neighbours turn their outer edge away, so only a sliver of each shows.
                transform: `translate(-50%, -50%) translateX(${d * 84}%) rotateY(${d * 30}deg) scale(${d === 0 ? 1 : 0.8})`,
                opacity: d === 0 ? 1 : side ? 0.75 : 0,
                zIndex: d === 0 ? 3 : side ? 2 : 1,
                pointerEvents: shown ? "auto" : "none",
              }}
            >
              <div
                className={`relative flex h-full flex-col overflow-hidden rounded-[18px] border bg-surface p-8 ${d === 0 ? "menu-bob border-azure" : "border-line"}`}
              >
                <div className="flex items-start gap-4">
                  <span className="grid size-12 shrink-0 place-items-center rounded-[13px] bg-mist text-azure-deep">
                    <Icon size={24} strokeWidth={1.75} aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <h2 className="text-[26px] font-bold leading-tight tracking-[-0.02em] text-ink">{card.title}</h2>
                    <p className="mt-1.5 text-[14px] text-slate">{card.description}</p>
                  </div>
                  {card.figure && <span className="font-mono text-[13px] text-azure-deep">{card.figure}</span>}
                </div>

                {d === 0 && (
                  <div key={`${card.id}-${at}`} className="mt-6 flex min-h-0 flex-1 flex-col gap-2">
                    {card.id === "new" && (
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          if (gene.trim()) onOpenReport(gene.trim());
                        }}
                        className="menu-unfold flex items-center gap-2"
                        style={{ animationDelay: "120ms" }}
                      >
                        <input
                          value={gene}
                          onChange={(e) => setGene(e.target.value)}
                          aria-label="Gene"
                          className="h-11 min-w-0 flex-1 rounded-full border border-line bg-frost px-4 font-mono text-[14px] text-ink outline-none focus:border-azure"
                        />
                        <button type="submit" className="h-11 rounded-full border border-line px-5 text-[14px] text-azure-deep hover:border-azure">
                          Build
                        </button>
                      </form>
                    )}
                    <div className="flex min-h-0 flex-col gap-1.5 overflow-y-auto">
                      {card.items.map((item, index) => (
                        <button
                          key={item.label}
                          type="button"
                          onClick={item.go}
                          className="menu-unfold flex w-full items-center gap-3 rounded-[10px] border border-line px-4 py-2.5 text-left text-ink transition-colors hover:border-azure hover:bg-mist"
                          style={{ animationDelay: `${180 + index * 60}ms` }}
                        >
                          <span className={`flex-1 text-[14px] ${item.mono ? "font-mono" : ""}`}>{item.label}</span>
                          {item.meta && <span className="font-mono text-[12px] text-slate">{item.meta}</span>}
                        </button>
                      ))}
                    </div>
                    <button
                      type="button"
                      onClick={() => onSelect(card.id)}
                      className="menu-unfold mt-auto self-end rounded-full bg-azure-deep px-6 py-2.5 text-[14px] font-semibold text-on-accent hover:bg-azure-hover"
                      style={{ animationDelay: `${180 + card.items.length * 60}ms` }}
                    >
                      Open
                    </button>
                  </div>
                )}

                {d !== 0 && (
                  <button
                    type="button"
                    onClick={() => setAt(i)}
                    aria-label={card.title}
                    className="absolute inset-0 rounded-[18px] bg-ink/10 transition-colors hover:bg-ink/5"
                    tabIndex={-1}
                  />
                )}
              </div>
            </div>
          );
        })}

        <RoundButton label="Previous" side="left" onClick={() => go(-1)}>
          <ChevronLeft size={20} aria-hidden="true" />
        </RoundButton>
        <RoundButton label="Next" side="right" onClick={() => go(1)}>
          <ChevronRight size={20} aria-hidden="true" />
        </RoundButton>
      </div>

      <nav aria-label="Screens" className="flex items-center justify-center gap-2 py-6">
        {cards.map((card, i) => (
          <button
            key={card.id}
            type="button"
            onClick={() => setAt(i)}
            aria-label={card.title}
            aria-current={i === at}
            title={`${card.title} (${i + 1})`}
            className={`h-2 rounded-full transition-all duration-300 ${i === at ? "w-7 bg-azure-deep" : "w-2 bg-line hover:bg-azure"}`}
          />
        ))}
      </nav>
    </div>
  );
}

function RoundButton({
  label,
  side,
  onClick,
  children,
}: {
  label: string;
  side: "left" | "right";
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={`absolute top-1/2 z-10 grid size-11 -translate-y-1/2 place-items-center rounded-full border border-line bg-surface text-ink hover:border-azure hover:text-azure-deep ${
        side === "left" ? "left-4" : "right-4"
      }`}
    >
      {children}
    </button>
  );
}

function StatusPill({ status }: { status: AppStatus | null }) {
  if (!status) return <span />;
  return (
    <span className="justify-self-start inline-flex h-9 items-center gap-2 rounded-full border border-line bg-surface px-3.5 text-[12.5px] text-slate">
      <Globe size={15} strokeWidth={1.75} aria-hidden="true" />
      {status.online ? "Online" : "Offline"}, <span className="font-mono">{status.local.length}/{status.sources}</span> local
    </span>
  );
}

/** Screen bar in card mode: Menu, logo, status, Settings. */
export function MenuBar({
  status,
  onMenu,
  onSettings,
}: {
  status: AppStatus | null;
  onMenu: () => void;
  onSettings: () => void;
}) {
  return (
    <header className="grid h-[64px] shrink-0 grid-cols-[1fr_auto_1fr] items-center gap-3 border-b border-line bg-surface px-5">
      <button
        type="button"
        onClick={onMenu}
        className="justify-self-start flex h-10 items-center gap-2 rounded-full border border-line px-3.5 text-[13px] text-ink hover:border-azure hover:text-azure-deep"
      >
        <LayoutGrid size={16} strokeWidth={1.75} aria-hidden="true" />
        Menu
      </button>
      <button type="button" onClick={onMenu} aria-label="Menu" className="rounded-[10px]">
        <SpicaLockup className="h-11 w-auto" />
      </button>
      <div className="justify-self-end flex items-center gap-2">
        <StatusPill status={status} />
        <button
          type="button"
          onClick={onSettings}
          aria-label="Settings"
          className="grid size-10 place-items-center rounded-full border border-line text-ink hover:border-azure hover:text-azure-deep"
        >
          <SettingsIcon size={17} strokeWidth={1.75} aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}
