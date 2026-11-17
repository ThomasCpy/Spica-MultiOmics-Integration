import { Columns3, MessagesSquare, Database, FileText, ListOrdered, PanelLeftClose, PanelLeftOpen, Plus, Radar, Settings, ShieldCheck, type LucideIcon, Newspaper } from "lucide-react";
import { FlaskConical, Globe } from "lucide-react";
import { SpicaLockup, SpicaMark } from "./SpicaLogo";
import type { AppStatus } from "../report";

export type ViewId =
  | "home"
  | "new"
  | "compare"
  | "ask"
  | "intel"
  | "reports"
  | "candidates"
  | "digest"
  | "datasets"
  | "databases"
  | "settings";

type NavItem = { id: ViewId; label: string; icon: LucideIcon; badge?: string };

const NAV: NavItem[] = [
  { id: "new", label: "New report", icon: Plus },
  { id: "compare", label: "Compare", icon: Columns3 },
  { id: "ask", label: "Ask", icon: MessagesSquare },
  { id: "intel", label: "Intelligence", icon: Radar },
  { id: "digest", label: "Digest", icon: Newspaper },
  { id: "datasets", label: "Datasets", icon: FlaskConical },
  { id: "reports", label: "Reports", icon: FileText },
  { id: "candidates", label: "Candidates", icon: ListOrdered },
  { id: "databases", label: "Databases", icon: Database },
];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const short = (iso: string) => {
  const [, m, d] = iso.split("-");
  return m && d ? `${Number(d)} ${MONTHS[Number(m) - 1]}` : iso;
};

type SidebarProps = {
  expanded: boolean;
  onToggle: () => void;
  active: ViewId;
  onSelect: (id: ViewId) => void;
  shortcut: string;
  status: AppStatus | null;
  onOpenReport: (symbol: string) => void;
};

export function Sidebar({
  expanded,
  onToggle,
  active,
  onSelect,
  shortcut,
  status,
  onOpenReport,
}: SidebarProps) {
  // What the footer says is what is true: how many sources are local, and
  // whether the rest are being fetched. It used to be a fixed placeholder.
  const local = status?.local.length ?? 0;
  const total = status?.sources ?? 0;
  const allLocal = total > 0 && local === total;
  const title = !status ? "Status unknown" : status.online ? "Online" : "Offline";
  const detail = !status
    ? ""
    : allLocal
      ? `all ${total} sources local`
      : `${local} of ${total} sources local`;
  const explain = !status
    ? ""
    : status.online
      ? `Online access on. ${local} of ${total} sources local; gaps filled from public APIs and cached.`
      : `Online access off. ${local} of ${total} sources local; no network use.`;
  const recentReports = status?.recent ?? [];
  const toggleHint = `${expanded ? "Collapse" : "Expand"} sidebar (${shortcut})`;

  return (
    <aside
      aria-label="Main"
      className={`flex h-full shrink-0 flex-col overflow-hidden border-r border-line bg-surface transition-[width] duration-200 ease-out ${
        expanded ? "w-64" : "w-[68px]"
      }`}
    >
      <header className="flex h-16 shrink-0 items-center px-3">
        {expanded ? (
          <>
            <SpicaLockup className="ml-1 h-11 w-auto" />
            <button
              type="button"
              onClick={onToggle}
              aria-expanded="true"
              aria-label="Collapse sidebar"
              title={toggleHint}
              className="ml-auto grid size-9 place-items-center rounded-[10px] text-slate transition-colors hover:bg-frost hover:text-ink"
            >
              <PanelLeftClose size={20} strokeWidth={1.75} />
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={onToggle}
            aria-expanded="false"
            aria-label="Expand sidebar"
            title={toggleHint}
            className="group relative mx-auto grid size-11 place-items-center rounded-[12px] transition-colors hover:bg-frost"
          >
            <SpicaMark className="size-8 transition-opacity group-hover:opacity-0 group-focus-visible:opacity-0" />
            <PanelLeftOpen
              size={20}
              strokeWidth={1.75}
              aria-hidden="true"
              className="absolute text-slate opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
            />
          </button>
        )}
      </header>

      <nav aria-label="Sections" className="flex shrink-0 flex-col gap-1 px-3 pt-2">
        {NAV.map((item) => (
          <NavButton
            key={item.id}
            item={item}
            expanded={expanded}
            active={active === item.id}
            onSelect={onSelect}
          />
        ))}
      </nav>

      {expanded ? (
        <section aria-labelledby="recent-heading" className="mt-7 min-h-0 flex-1 overflow-y-auto px-3">
          <h2 id="recent-heading" className="px-2.5 pb-2 text-[12px] font-medium text-slate">
            Recent reports
          </h2>
          {recentReports.length === 0 && (
            <p className="px-2.5 text-[12px] text-slate">No report.</p>
          )}
          <ul className="flex flex-col gap-0.5">
            {recentReports.slice(0, 12).map((r) => (
              <li key={r.symbol}>
                <button
                  type="button"
                  onClick={() => onOpenReport(r.symbol)}
                  className="flex h-9 w-full items-center gap-3 rounded-[10px] px-2.5 text-left transition-colors hover:bg-frost"
                >
                  <span className="font-mono text-[13px] font-medium text-ink">{r.symbol}</span>
                  <span className="ml-auto text-[12px] tabular-nums text-slate">{short(r.date)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <div className="flex-1" />
      )}

      <footer className="flex shrink-0 flex-col gap-1 border-t border-line p-3">
        <button
          type="button"
          title={explain}
          onClick={() => onSelect("settings")}
          className={`flex h-12 items-center gap-3 rounded-[10px] text-left transition-colors hover:bg-frost ${expanded ? "px-2.5" : "justify-center"}`}
        >
          {status?.online ? (
            <Globe size={20} strokeWidth={1.75} className="shrink-0 text-azure-deep" aria-hidden="true" />
          ) : (
            <ShieldCheck size={20} strokeWidth={1.75} className="shrink-0 text-azure-deep" aria-hidden="true" />
          )}
          {expanded ? (
            <div className="min-w-0 leading-tight">
              <p className="text-[13px] font-semibold text-ink">{title}</p>
              <p className="text-[12px] text-slate">{detail}</p>
            </div>
          ) : (
            <span className="sr-only">{title}, {detail}</span>
          )}
        </button>
        <NavButton
          item={{ id: "settings", label: "Settings", icon: Settings }}
          expanded={expanded}
          active={active === "settings"}
          onSelect={onSelect}
        />
      </footer>
    </aside>
  );
}

type NavButtonProps = {
  item: NavItem;
  expanded: boolean;
  active: boolean;
  onSelect: (id: ViewId) => void;
};

function NavButton({ item, expanded, active, onSelect }: NavButtonProps) {
  const Icon = item.icon;
  return (
    <button
      type="button"
      onClick={() => onSelect(item.id)}
      aria-current={active ? "page" : undefined}
      title={expanded ? undefined : item.label}
      className={`flex h-10 items-center gap-3 whitespace-nowrap rounded-[10px] text-[14px] transition-colors ${
        expanded ? "px-2.5" : "justify-center"
      } ${active ? "bg-mist font-semibold text-azure-deep" : "text-ink hover:bg-frost"}`}
    >
      <Icon size={20} strokeWidth={1.75} className="shrink-0" aria-hidden="true" />
      {expanded ? (
        <>
          <span className="truncate">{item.label}</span>
          {item.badge && (
            <span className="ml-auto rounded-full bg-frost px-2 py-0.5 text-[11px] font-medium text-slate">
              {item.badge}
            </span>
          )}
        </>
      ) : (
        <span className="sr-only">{item.label}</span>
      )}
    </button>
  );
}
