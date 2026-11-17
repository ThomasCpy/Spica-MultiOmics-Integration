import { useCallback, useEffect, useRef, useState } from "react";
import { Sidebar, type ViewId } from "./components/Sidebar";
import { Report } from "./components/Report";
import { Comparison } from "./components/Comparison";
import { Ask } from "./components/Ask";
import { Intel } from "./components/Intel";
import { Settings } from "./components/Settings";
import { MirrorPanel } from "./components/MirrorPanel";
import { Candidates } from "./components/Candidates";
import { Reports } from "./components/Reports";
import { Digest } from "./components/Digest";
import { Datasets } from "./components/Datasets";
import { CardMenu, MenuBar } from "./components/CardMenu";
import { PanelBoundary } from "./components/PanelBoundary";
import { appStatus, type AppStatus } from "./report";
import { networkSettings } from "./mirror";
import { applyTheme } from "./theme";

const STORAGE_KEY = "spica.sidebarExpanded";
const isMac = typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);
const SHORTCUT = isMac ? "⌘B" : "Ctrl+B";

function readExpanded(): boolean {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === null ? true : stored === "1";
  } catch {
    return true;
  }
}

export default function App() {
  const [expanded, setExpanded] = useState(readExpanded);
  const [active, setActive] = useState<ViewId>("new");
  // Carried from a report into the comparison, so "compare with others"
  // arrives with the gene already filled in.
  const [seed, setSeed] = useState("");
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [open, setOpen] = useState<{ symbol: string; nonce: number } | null>(null);
  // The main menu: the sidebar, or floating cards on a home screen (Settings).
  const [menu, setMenu] = useState<"sidebar" | "cards">("sidebar");
  const refreshStatus = useCallback(() => {
    appStatus()
      .then((next) => next && setStatus(next))
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    // The bridge may attach after the first render; pywebview says when.
    const ready = () => {
      refreshStatus();
      networkSettings()
        .then((saved) => {
          applyTheme(saved.theme ?? "light");
          if (saved.menu === "cards") {
            setMenu("cards");
            setActive((current) => (current === "new" ? "home" : current));
          }
        })
        .catch(() => undefined);
    };
    ready();
    window.addEventListener("pywebviewready", ready);
    return () => window.removeEventListener("pywebviewready", ready);
  }, [refreshStatus]);

  const toggle = useCallback(() => setExpanded((v) => !v), []);
  // One scrolling pane for every view: without this, a new view opens at
  // whatever depth the last one was left at.
  const pane = useRef<HTMLElement>(null);
  useEffect(() => {
    pane.current?.scrollTo(0, 0);
  }, [active]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, expanded ? "1" : "0");
    } catch {
      /* storage unavailable: state not persisted */
    }
  }, [expanded]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        toggle();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);

  const openReport = (symbol: string) => {
    setActive("new");
    setOpen({ symbol, nonce: Date.now() });
  };
  const cards = menu === "cards";

  return (
    <div className={`flex h-full ${cards ? "flex-col" : ""}`}>
      {!cards && (
        <Sidebar
          expanded={expanded}
          onToggle={toggle}
          active={active === "home" ? "new" : active}
          onSelect={setActive}
          shortcut={SHORTCUT}
          status={status}
          onOpenReport={openReport}
        />
      )}
      {cards && active !== "home" && (
        <MenuBar status={status} onMenu={() => setActive("home")} onSettings={() => setActive("settings")} />
      )}
      <main ref={pane} className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        <PanelBoundary key={active} name="screen">
        {active === "home" &&
          (cards ? (
            <div className="menu-arrive min-h-full">
              <CardMenu
                status={status}
                onSelect={setActive}
                onOpenReport={openReport}
                onCompare={(genes) => {
                  setSeed(`${genes}, `);
                  setActive("compare");
                }}
              />
            </div>
          ) : (
            <Report open={open} onBuilt={refreshStatus} onCompare={(genes) => { setSeed(`${genes}, `); setActive("compare"); }} />
          ))}
        {active === "new" && (
          <Report
            open={open}
            onBuilt={refreshStatus}
            onCompare={(genes) => {
              setSeed(`${genes}, `);
              setActive("compare");
            }}
          />
        )}
        {active === "compare" && <Comparison key={seed} initial={seed} />}
        {active === "ask" && <Ask />}
        {active === "intel" && <Intel />}
        {active === "settings" && (
          <Settings
            onNetwork={refreshStatus}
            onMenu={setMenu}
          />
        )}
        {active === "databases" && <Databases />}
        {active === "datasets" && (
          <Datasets
            onOpenReport={(symbol) => {
              setActive("new");
              setOpen({ symbol, nonce: Date.now() });
            }}
          />
        )}
        {active === "digest" && (
          <Digest
            onOpenReport={(symbol) => {
              setActive("new");
              setOpen({ symbol, nonce: Date.now() });
            }}
          />
        )}
        {active === "reports" && (
          <Reports
            recent={status?.recent ?? []}
            onOpenReport={(symbol) => {
              setActive("new");
              setOpen({ symbol, nonce: Date.now() });
            }}
          />
        )}
        {active === "candidates" && (
          <Candidates
            onOpenReport={(symbol) => {
              setActive("new");
              setOpen({ symbol, nonce: Date.now() });
            }}
          />
        )}
        </PanelBoundary>
      </main>
    </div>
  );
}

function Databases() {
  return (
    <div className="mx-auto w-full max-w-[880px] px-8 py-10">
      <h1 className="text-[30px] font-bold leading-[1.15] tracking-[-0.02em] text-ink">
        Databases
      </h1>
      <p className="mt-3 max-w-[62ch] text-[15px] leading-relaxed text-slate">
        Local source releases. Each report reads these files; each value names its release.
      </p>
      <div className="mt-8">
        <MirrorPanel />
      </div>
    </div>
  );
}
