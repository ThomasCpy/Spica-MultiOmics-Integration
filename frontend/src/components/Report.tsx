import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, ChevronRight, Loader2, Search } from "lucide-react";
import type { FieldSpec, FieldValue, GeneRecord, Schema, SourceStamp } from "../bridge";
import {
  buildReport,
  STATE_LABEL,
  type Dogma,
  type Glance as GlanceData,
  type Locations,
} from "../report";
import { TissueChart } from "./TissueChart";
import { DogmaChart } from "./DogmaChart";
import { decades, ScaleStrip, type Band } from "./ScaleStrip";
import { GenomeView } from "./GenomeView";
import { TfAnalysis } from "./TfAnalysis";
import { PanelBoundary } from "./PanelBoundary";
import { takeLocusTracks } from "../geo";
import { SourceAgreement } from "./SourceAgreement";
import { Druggability } from "./Druggability";
import { CellMap } from "./CellMap";
import { DiseaseGenetics } from "./DiseaseGenetics";
import { InteractionPartners } from "./InteractionPartners";
import { ExportReport } from "./ExportReport";
import { Orthologs } from "./Orthologs";
import { EffectDistribution } from "./EffectDistribution";
import { StructurePlot } from "./StructurePlot";
import { IsoformHeatmap } from "./IsoformHeatmap";
import { CoexpressionList } from "./CoexpressionList";
import { ExpandableValue } from "./Expandable";
import { Glance } from "./Glance";

// The per-tissue profiles get a chart in addition to a row. A 54-tissue map
// is unreadable as a line of text, and its shape is the point.
const CHARTED: Record<
  string,
  { caption: string; unit: string; noun?: string; scales?: boolean }
> = {
  gtex_tissue_tpm: { caption: "RNA across GTEx tissues", unit: "median TPM" },
  gtex_microdissected_tpm: {
    caption: "RNA in GTEx microdissected samples",
    unit: "median TPM",
    noun: "samples",
  },
  hpa_rna_tissue_ntpm: { caption: "RNA across HPA tissues", unit: "nTPM" },
  hpa_brain_region_ntpm: { caption: "RNA across brain regions, HPA", unit: "nTPM", noun: "regions" },
  hpa_protein_tissue_intensity: {
    caption: "Protein by mass spectrometry, HPA",
    unit: "intensity",
  },
  hpa_single_cell_enriched: {
    caption: "Single-cell RNA, HPA enriched cell types",
    unit: "nCPM",
    noun: "cell types",
  },
  clinvar_classifications: {
    caption: "ClinVar records by classification",
    unit: "records",
    noun: "classes",
  },
  // Shares run 0 to 100, and a lineage of three lines says so in its name.
  depmap_lineage_dependency: {
    caption: "Dependent lines by lineage, DepMap",
    unit: "% of lines",
    noun: "lineages",
    scales: false,
  },
  gwas_traits: {
    caption: "GWAS traits, strongest association",
    unit: "-log10 p",
    noun: "traits",
  },
  // Scores run 0 to 1, so a log view would only distort them.
  disease_associations: {
    caption: "Disease association, Open Targets",
    unit: "score, 0 to 1",
    noun: "diseases",
    scales: false,
  },
};

// The record of one gene, as the data layer built it. No model touches this
// screen. Each value shows its source, release and date. Each gap shows
// which kind of gap it is.

export function Report({
  onCompare,
  open,
  onBuilt,
}: {
  onCompare: (genes: string) => void;
  open?: { symbol: string; nonce: number } | null;
  onBuilt?: () => void;
}) {
  const [text, setText] = useState("");
  const [record, setRecord] = useState<GeneRecord | null>(null);
  const [schema, setSchema] = useState<Schema | null>(null);
  const [summary, setSummary] = useState("");
  const [dogma, setDogma] = useState<Dogma | null>(null);
  const [bands, setBands] = useState<Band[]>([]);
  const [glance, setGlance] = useState<GlanceData | null>(null);
  const [locations, setLocations] = useState<Locations | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    input.current?.focus();
  }, []);

  // A gene picked from the sidebar's recent reports opens straight away.
  useEffect(() => {
    if (open?.symbol) {
      setText(open.symbol);
      run(open.symbol);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open?.nonce]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    run(text.trim());
  }

  async function run(target: string) {
    if (!target) {
      setProblem("No gene entered.");
      return;
    }
    setBusy(true);
    setProblem("");
    try {
      const result = await buildReport(target);
      if (result.status === "ok" && result.record) {
        setRecord(result.record);
        setSchema(result.schema ?? null);
        setSummary(result.message);
        setDogma(result.dogma ?? null);
        setBands(result.bands ?? []);
        setGlance(result.glance ?? null);
        setLocations(result.locations ?? null);
        onBuilt?.();
      } else {
        setProblem(result.message);
      }
    } catch (error) {
      setProblem(
        error instanceof Error && error.message
          ? error.message
          : "The backend didn't respond.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (record && schema) {
    return (
      <div className="mx-auto w-full max-w-[860px] px-8 py-10">
        <button
          type="button"
          onClick={() => setRecord(null)}
          className="mb-6 flex items-center gap-1.5 text-[13px] text-slate transition-colors hover:text-azure-deep"
        >
          <ArrowLeft size={15} aria-hidden="true" />
          New report
        </button>
        <Record
          record={record}
          schema={schema}
          summary={summary}
          dogma={dogma}
          bands={bands}
          glance={glance}
          locations={locations}
          onCompare={onCompare}
        />
      </div>
    );
  }

  return (
    <div className="m-auto w-full max-w-[680px] px-8 py-16">
      <h1 className="text-[34px] font-bold leading-[1.15] tracking-[-0.02em] text-balance text-ink">
        New report
      </h1>
      <p className="mt-3 max-w-[54ch] text-[15px] leading-relaxed text-slate">
        Gene record. Each value shows its source and release; each gap shows its cause.
      </p>

      <form onSubmit={submit} noValidate className="mt-8">
        <label htmlFor="report-gene" className="mb-1.5 block px-1 text-[12px] font-medium text-slate">
          Gene symbol, protein name or UniProt accession
        </label>
        <div className="flex h-14 items-center gap-3 rounded-full border border-line bg-surface pl-5 pr-1.5 transition-[border-color,box-shadow] focus-within:border-azure focus-within:shadow-[0_0_0_4px_rgb(0_178_255/0.18)]">
          <Search size={20} strokeWidth={1.75} className="shrink-0 text-slate" aria-hidden="true" />
          <input
            id="report-gene"
            ref={input}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              if (problem) setProblem("");
            }}
            autoComplete="off"
            spellCheck={false}
            aria-label="Target gene or protein"
            className="h-full min-w-0 flex-1 bg-transparent font-mono text-[15px] text-ink outline-none placeholder:font-sans placeholder:text-[14px] placeholder:text-slate/70"
          />
          <button
            type="submit"
            disabled={busy}
            className="flex h-11 shrink-0 items-center gap-2 rounded-full bg-azure-deep px-5 text-[14px] font-semibold text-on-accent transition-colors hover:bg-azure-hover disabled:opacity-70"
          >
            Build report
            {busy ? (
              <Loader2 size={18} className="animate-spin" aria-hidden="true" />
            ) : (
              <ArrowRight size={18} strokeWidth={2} aria-hidden="true" />
            )}
          </button>
        </div>
        <p
          role={problem ? "alert" : "status"}
          className={`mt-3 min-h-5 px-5 text-[13px] ${problem ? "text-error" : "text-slate"}`}
        >
          {problem}
        </p>
      </form>

    </div>
  );
}

function Record({
  record,
  schema,
  summary,
  dogma,
  bands,
  glance,
  locations,
  onCompare,
}: {
  record: GeneRecord;
  schema: Schema;
  summary: string;
  dogma: Dogma | null;
  bands: Band[];
  glance: GlanceData | null;
  locations: Locations | null;
  onCompare: (genes: string) => void;
}) {
  const symbol = record.resolution.symbol || record.query;
  const sections = Object.entries(schema.sections);
  // Tracks another panel (the TF scan) or another screen (Datasets) asked
  // the genome view to show; the latter open Genomics on arrival.
  const [geoArrived] = useState(() => takeLocusTracks(symbol));
  const [genomeRequest, setGenomeRequest] = useState<{ ids: string[]; nonce: number } | null>(
    geoArrived.length ? { ids: geoArrived, nonce: Date.now() } : null,
  );

  return (
    <>
      <header className="mb-7">
        <h1 className="font-mono text-[28px] font-semibold tracking-[-0.01em] text-ink">
          {symbol}
        </h1>
        <p className="mt-1 text-[14px] leading-relaxed text-slate">{summary}</p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {record.sources.map((source) => (
            <Stamp key={source.key} source={source} />
          ))}
          <div className="ml-auto" />
          <ExportReport genes={[symbol]} />
          <button
            type="button"
            onClick={() => onCompare(symbol)}
            className="rounded-full border border-line bg-surface px-3.5 py-1.5 text-[13px] text-ink transition-colors hover:border-azure hover:text-azure-deep"
          >
            Compare
          </button>
        </div>
      </header>

      {glance && <Glance glance={glance} />}

      <div className="space-y-5">
        {sections.map(([key, label]) => {
          const specs = schema.fields.filter((spec) => spec.section === key);
          if (!specs.length) return null;
          const filled = specs.filter((spec) => !record.fields[spec.name]?.state).length;
          const card = (
            <Section title={label} note={`${filled} of ${specs.length} filled`} startOpen={key === "genomics" && geoArrived.length > 0}>
              <dl className="divide-y divide-line">
                {specs.map((spec) => (
                  <Field key={spec.name} spec={spec} value={record.fields[spec.name]} />
                ))}
              </dl>
              {specs
                .filter((spec) => CHARTED[spec.name] && !record.fields[spec.name]?.state)
                .map((spec) => (
                  <div key={`${spec.name}-chart`} className="border-t border-line px-5 py-4">
                    <TissueChart
                      values={record.fields[spec.name].value as Record<string, number>}
                      caption={CHARTED[spec.name].caption}
                      unit={CHARTED[spec.name].unit}
                      noun={CHARTED[spec.name].noun}
                      scales={CHARTED[spec.name].scales}
                      highlight={record.fields.gtex_max_tissue?.value as string}
                    />
                  </div>
                ))}
              {key === "insights" && <Placement record={record} bands={bands} />}
              {key === "clinical" && <Druggability record={record} />}
              {key === "clinical" && typeof record.fields.ensembl_gene_id?.value === "string" && (
                <DiseaseGenetics symbol={symbol} ensemblId={record.fields.ensembl_gene_id.value} />
              )}
              {key === "proteomics" && locations && <CellMap locations={locations} />}
              {key === "proteomics" && typeof record.fields.ensembl_gene_id?.value === "string" && (
                <InteractionPartners symbol={symbol} ensemblId={record.fields.ensembl_gene_id.value} />
              )}
              {key === "proteomics" && typeof record.fields.uniprot_accession?.value === "string" && (
                <StructurePlot accession={record.fields.uniprot_accession.value} />
              )}
              {key === "transcriptomics" && typeof record.fields.ensembl_gene_id?.value === "string" && (
                <>
                  <IsoformHeatmap symbol={symbol} ensemblId={record.fields.ensembl_gene_id.value} />
                  <CoexpressionList symbol={symbol} ensemblId={record.fields.ensembl_gene_id.value} />
                </>
              )}
              {key === "genomics" && <Orthologs record={record} />}
              {key === "essentiality" && <EffectDistribution record={record} />}
              {key === "genomics" && typeof record.fields.ensembl_gene_id?.value === "string" && (
                <TfAnalysis
                  symbol={symbol}
                  ensemblId={record.fields.ensembl_gene_id.value}
                  onShowInGenome={() => setGenomeRequest({ ids: ["tf_scan"], nonce: Date.now() })}
                />
              )}
              {key === "genomics" && typeof record.fields.ensembl_gene_id?.value === "string" && (
                // Mounted only while the section is open: igv.js and its
                // tracks load when someone asks to see the locus.
                <PanelBoundary name="genome view">
                  <GenomeView
                    symbol={symbol}
                    ensemblId={record.fields.ensembl_gene_id.value}
                    topTissue={String(record.fields.gtex_max_tissue?.value ?? "")}
                    request={genomeRequest}
                  />
                </PanelBoundary>
              )}
            </Section>
          );
          // The dogma view sits where it reads: straight after the protein
          // section, because it is the two sections above it put on one axis.
          if (key !== "proteomics" || !dogma) return <div key={key}>{card}</div>;
          return (
            <div key={key} className="space-y-5">
              {card}
              <Section
                title="RNA and protein by organ"
                note={`${dogma.organs} organs`}
              >
                <div className="px-5 py-4">
                  <DogmaChart dogma={dogma} />
                </div>
                <SourceAgreement dogma={dogma} />
              </Section>
            </div>
          );
        })}
      </div>

      <p className="mt-6 font-mono text-[11px] text-slate">
        fingerprint {record.fingerprint.slice(0, 16)}
      </p>
    </>
  );
}

// The two specificity measures, each on its own scale. A number alone
// says nothing about where it sits; these say it at a glance.
function Placement({ record, bands }: { record: GeneRecord; bands: Band[] }) {
  const tau = record.fields.rna_specificity_tau;
  const fold = record.fields.rna_fold_over_median;
  const hasTau = tau && !tau.state && typeof tau.value === "number";
  const hasFold = fold && !fold.state && typeof fold.value === "number";
  if (!hasTau && !hasFold) return null;
  const foldValue = hasFold ? (fold.value as number) : 1;
  const scale = decades(foldValue);
  return (
    <div className="grid gap-x-10 gap-y-6 border-t border-line px-5 py-5 md:grid-cols-2">
      {hasTau && (
        <ScaleStrip
          caption="RNA specificity, tau (0 everywhere alike, 1 one tissue only)"
          value={tau.value as number}
          display={String(tau.value)}
          domain={[0, 1]}
          bands={bands}
        />
      )}
      {hasFold && (
        <ScaleStrip
          caption="Peak over the median tissue, log scale"
          value={foldValue}
          display={`${foldValue.toLocaleString("en-US", { maximumFractionDigits: 1 })}×`}
          domain={scale.domain}
          log
          ticks={scale.ticks}
        />
      )}
    </div>
  );
}

// Sections start closed: a record is forty fields and three charts, and the
// reader came for one part of it. The header still says how full each
// section is, so a closed section is a summary, not a hiding place.
function Section({
  title,
  note,
  children,
  startOpen = false,
}: {
  title: string;
  note: string;
  children: React.ReactNode;
  startOpen?: boolean;
}) {
  const [open, setOpen] = useState(startOpen);
  return (
    <section className="rounded-[14px] border border-line bg-surface">
      <h2>
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className={`flex w-full items-center gap-2 px-5 py-3 text-left transition-colors hover:bg-frost ${
            open ? "rounded-t-[14px] border-b border-line" : "rounded-[14px]"
          }`}
        >
          <ChevronRight
            size={16}
            aria-hidden="true"
            className={`shrink-0 text-slate transition-transform ${open ? "rotate-90" : ""}`}
          />
          <span className="text-[15px] font-semibold text-ink">{title}</span>
          <span className="ml-auto text-[12px] text-slate">{note}</span>
        </button>
      </h2>
      {open && children}
    </section>
  );
}

function Field({ spec, value }: { spec: FieldSpec; value: FieldValue }) {
  return (
    <div className="grid grid-cols-[minmax(0,180px)_1fr] gap-4 px-5 py-2.5">
      <dt className="text-[13px] text-slate" title={spec.description}>
        {spec.label}
        {spec.unit && <span className="ml-1 text-[11px] opacity-70">{spec.unit}</span>}
      </dt>
      <dd className="min-w-0 text-[13px]">
        {value?.state ? (
          <span className="text-slate">
            {STATE_LABEL[value.state] ?? value.state}
            <span className="ml-1.5 text-[12px] opacity-80">{value.reason}</span>
          </span>
        ) : (
          <>
            <span className="break-words text-ink">
              {isCollection(value?.value) ? (
                <ExpandableValue value={value?.value} mono={spec.mono} />
              ) : (
                <span className={spec.mono ? "font-mono" : ""}>
                  {String(value?.value ?? "")}
                </span>
              )}
            </span>
            {value?.provenance && (
              <span className="ml-2 whitespace-nowrap text-[11px] text-slate">
                {value.provenance.source} {value.provenance.version}
              </span>
            )}
          </>
        )}
      </dd>
    </div>
  );
}

function isCollection(value: unknown): boolean {
  return Array.isArray(value) || (!!value && typeof value === "object");
}


function Stamp({ source }: { source: SourceStamp }) {
  const live = source.status === "fetched" || source.status === "cached";
  const bad = source.status === "failed" || source.status === "unavailable";
  return (
    <span
      title={source.note || `${source.label} ${source.version}`}
      className={`rounded-full border px-2.5 py-1 text-[11px] ${
        bad
          ? "border-line bg-surface text-slate"
          : "border-azure/40 bg-mist text-azure-deep"
      }`}
    >
      <span className="font-mono">{source.label}</span>
      {/* "API" is already the version when a source has no release label;
          saying it twice reads as a stutter. */}
      {source.version && source.version !== "API" && (
        <span className="ml-1 opacity-70">{source.version}</span>
      )}
      {live && <span className="ml-1 opacity-70">· API</span>}
      {bad && <span className="ml-1 opacity-70">· {source.status}</span>}
    </span>
  );
}
