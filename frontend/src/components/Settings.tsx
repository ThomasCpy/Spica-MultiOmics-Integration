import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import { licenceDocuments, type LicenceDocuments } from "../licence";
import { MirrorPanel } from "./MirrorPanel";
import { networkSettings, setMenuStyle, setOnline, setThemeChoice, type NetworkSettings } from "../mirror";
import { applyTheme, type ThemeChoice } from "../theme";

// Settings: appearance, network use, the local data and its updates, the
// licence, and the third-party notices.

export function Settings({
  onNetwork,
  onMenu,
}: {
  onNetwork?: () => void;
  onMenu?: (style: "sidebar" | "cards") => void;
}) {
  return (
    <div className="mx-auto w-full max-w-[880px] px-8 py-10">
      <h1 className="text-[30px] font-bold leading-[1.15] tracking-[-0.02em] text-ink">Settings</h1>

      <Appearance onMenu={onMenu} />
      <Network onChange={onNetwork} />
      <div className="mt-6">
        <MirrorPanel />
      </div>

      <div className="mt-8 space-y-6">
        <Document which="licence" title="Licence: PolyForm Strict 1.0.0" />
        <Document which="notices" title="Third-party notices" />
      </div>
    </div>
  );
}

/** Light, dark, or as Windows is set. Applied at once, kept for next time. */
function Appearance({ onMenu }: { onMenu?: (style: "sidebar" | "cards") => void }) {
  const [choice, setChoice] = useState<ThemeChoice | null>(null);
  const [menu, setMenu] = useState<"sidebar" | "cards">("sidebar");

  useEffect(() => {
    networkSettings()
      .then((saved) => {
        setChoice(saved.theme ?? "light");
        setMenu(saved.menu ?? "sidebar");
      })
      .catch(() => undefined);
  }, []);

  async function chooseMenu(next: "sidebar" | "cards") {
    setMenu(next);
    onMenu?.(next);
    try {
      await setMenuStyle(next);
    } catch {
      /* not saved: it still applies for this session */
    }
  }

  async function choose(next: ThemeChoice) {
    setChoice(next);
    applyTheme(next);
    try {
      await setThemeChoice(next);
    } catch {
      /* not saved: it still applies for this session */
    }
  }

  if (!choice) return null;
  const options: [ThemeChoice, string][] = [["light", "Light"], ["dark", "Dark"], ["system", "As Windows"]];
  const menus: ["sidebar" | "cards", string][] = [["sidebar", "Sidebar"], ["cards", "Floating cards"]];
  return (
    <section className="mt-8 rounded-[14px] border border-line bg-surface px-6 py-4">
    <div className="flex flex-wrap items-center gap-4">
      <h2 className="text-[15px] font-semibold text-ink">Appearance</h2>
      <div role="radiogroup" aria-label="Appearance" className="ml-auto flex rounded-full border border-line p-0.5">
        {options.map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={choice === value}
            onClick={() => choose(value)}
            className={`rounded-full px-3.5 py-1 text-[13px] transition-colors ${
              choice === value ? "bg-mist text-azure-deep" : "text-slate hover:text-ink"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
    <div className="mt-3 flex flex-wrap items-center gap-4 border-t border-line pt-3">
      <div>
        <h3 className="text-[14px] font-medium text-ink">Main menu</h3>
        <p className="text-[12px] text-slate">
          Sidebar, or one card per screen on a home screen.
        </p>
      </div>
      <div role="radiogroup" aria-label="Main menu" className="ml-auto flex rounded-full border border-line p-0.5">
        {menus.map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={menu === value}
            onClick={() => chooseMenu(value)}
            className={`rounded-full px-3.5 py-1 text-[13px] transition-colors ${
              menu === value ? "bg-mist text-azure-deep" : "text-slate hover:text-ink"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
    </section>
  );
}

/** Whether Spica may use the network on its own. Off unless switched on. */
function Network({ onChange }: { onChange?: () => void }) {
  const [network, setNetwork] = useState<NetworkSettings | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    networkSettings()
      .then(setNetwork)
      .catch(() => undefined);
  }, []);

  async function flip() {
    if (!network) return;
    setBusy(true);
    try {
      setNetwork(await setOnline(!network.online));
      onChange?.();
    } finally {
      setBusy(false);
    }
  }

  if (!network) return null;
  const on = network.online;
  return (
    <section className="mt-6 rounded-[14px] border border-line bg-surface px-6 py-5">
      <div className="flex items-start gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold text-ink">Online access</h2>
          <p className="mt-1.5 max-w-[68ch] text-[13px] leading-relaxed text-slate">
            {on
              ? "On. Local data first; gaps filled from public APIs and cached. Applies to genome tracks, per-residue structure, isoforms, regulators, sources not built locally, intelligence, digest feeds and GEO."
              : "Off. Local data and cached answers only. No network use."}
          </p>
          {network.forced_by && (
            <p className="mt-2 text-[12px] text-warn-ink">
              {network.forced_by}=1 set at start: online access {network.online_effective ? "on" : "off"}, switch overridden.
            </p>
          )}
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-label="Online access"
          onClick={flip}
          disabled={busy || !!network.forced_by}
          className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-60 ${
            on ? "bg-azure-deep" : "bg-line"
          }`}
        >
          <span
            className={`absolute top-0.5 block size-5 rounded-full bg-surface transition-[left] ${
              on ? "left-[22px]" : "left-0.5"
            }`}
          />
        </button>
      </div>
    </section>
  );
}

let documents: Promise<LicenceDocuments> | null = null;

/** One of the shipped documents, folded until asked for. */
export function Document({ which, title }: { which: keyof LicenceDocuments; title: string }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");

  useEffect(() => {
    if (!open || text) return;
    documents ??= licenceDocuments();
    documents.then((all) => setText(all[which] || "File not found."));
  }, [open, text, which]);

  return (
    <section className="rounded-[14px] border border-line bg-surface">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between px-6 py-3 text-left text-[15px] font-semibold text-ink"
      >
        {title}
        <ChevronDown
          size={18}
          className={`text-slate transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>
      {open && (
        <pre className="max-h-[420px] overflow-y-auto whitespace-pre-wrap border-t border-line px-6 py-4 font-sans text-[13px] leading-relaxed text-ink">
          {text || "Loading"}
        </pre>
      )}
    </section>
  );
}
