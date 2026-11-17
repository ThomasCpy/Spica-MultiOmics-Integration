# The agents

AI mode: a local model answers an arbitrary question from the user's own indexed
documents and from tools. It is Betelgeuse's shape (an orchestrator and a
tool agent in a loop, then a writer) with a verifier added.

This is not how the gene report is made. A report is deterministic and no
model touches it; the record is available here as one tool among several,
which is a different thing.

```
    orchestrator ──▶ tool agent
          ▲              │          until the orchestrator says DONE
          └──────────────┘
                 │
                 ▼
              writer ──▶ verifier
```

**The tools** reach what the report reaches. A move is a tool and one
string argument, so there is no code to sandbox.

| Tool | What it returns | Citation |
| --- | --- | --- |
| `documents("...")` | Passages from the indexed documents | the document and page |
| `record("GENE")` | The whole record, empty fields with their reasons | the field name |
| `field("GENE name [words or 51-100]")` | One field whole, a page at a time, filterable | the field name |
| `compare("A, B, C, ...")` | Every comparable field side by side, for any number of genes | the field names |
| `organs("GENE")` | RNA and protein from every source on one organ axis | `organs:GENE` |
| `glance("GENE [function or disease]")` | The words behind the report's word map, with weights and terms | `glance:GENE` |
| `structure("GENE")` | PDB entries and coverage, AlphaFold confidence and AlphaMissense stretches | `structure:GENE` |
| `isoforms("GENE")` | Every GTEx transcript and the leading one per tissue | `isoforms:GENE` |
| `coexpressed("GENE [51-100]")` | Genes whose GTEx profile moves with this one | `coexpressed:GENE` |
| `interactions("GENE [51-100]")` | Partners in HPA's experiments beside OmniPath's curation: datasets, papers, who acts on whom | `interactions:GENE` |
| `digest("query; gene ERBB2; kind podcast; since 2026-01-01")` | Passages from transcribed scientific podcasts, show notes, trials and papers, ranked, each with source, date, minute and link; `digest("latest")` for what arrived | `digest:<passage>` |
| `genelist("A, B, C" or "saved" or a list's name)` | How each entry maps to a gene, the saved lists, one list's genes | `genelist:...` |
| `candidates("A, B, C; preset antibody; for lung cancer")` | The ranked table, each criterion's score and the value behind it; `candidates("criteria")` lists the criteria and presets | `candidates:...` |
| `benchmark("antibody")` | The newest benchmark kept: AUC, positives at the top, each criterion alone | `benchmark:...` |
| `regulators("A[, B]")` | One gene's regulators and targets; for several, those they share and direct links | `regulators:A,B` |
| `genome("GENE [tracks, atlas ..., encode ...]")` | The locus, its tracks, the regulation atlas, ENCODE experiments | `genome:GENE` |
| `intel("topic")` | The latest check of a watched topic: papers, preprints, patents | `intel:topic` |

Nothing is cut silently: a long answer comes a page at a time and says how
to ask for the next. Every view the app serves has its tool, and
`tests/test_agent_views.py` fails when one is added without (`APP_VIEWS` in
`spica/agents/views.py`).

**The verifier** is code rather than a model, and for an answer it checks
two things. Every citation must be one a tool returned: a model
that writes a plausible page number has invented a source, and that is the
failure it exists to catch. And every number in a cited sentence must be
one the cited tools returned, allowing for rounding: a real source can still
be misquoted, which is flagged as a warning.

## The loop

**The orchestrator** sees the moves available (each source, how many of
its fields have values for this gene, and which it has already read), plus
the plan and every note so far. It restates the plan and picks one move:

```
PLAN: where is it expressed; where does the protein sit
READ: gtex
```

It is stateless. Everything it knows arrives in its prompt, from the notes
and the plan, which is what lets the loop run as long as it needs without
the context growing past what was learned. The plan is restated
whole each cycle rather than edited, so what it leaves out is what it
considers settled.

**The tool agent** reads that one source and writes a few factual lines,
each ending with the field it came from in brackets: `[gtex_max_tissue]`.
This is transcription, not judgement, so it is asked not to deliberate and
is sampled narrowly: copying a number out of a record does not improve with
reasoning.

The loop runs until the orchestrator chooses DONE. It cannot stop before it
has read two sources, and it is stopped for it after six: a model that
will not conclude should not be able to run forever.

**The writer** turns the notes into the assessment, every claim carrying
its field.

**The verifier** is `spica/agents/verify.py`, and it is ordinary code. A
second model asked "is this supported?" is not a check. It is another
thing that can be wrong in the same direction as the first. The rules:

1. A cited field must exist in the schema.
2. A cited field must have a value in this record. Citing something the
   record marks `not_found` is the worst failure, because it reads as
   sourced and is not.
3. A sentence stating a number must cite something.
4. A draft of prose that cites nothing at all has failed, whatever it says.
5. A number should appear in one of the fields its sentence cites: a
   warning rather than a failure, since "three of five sources" is a fair
   thing to say about the record itself.

Rule 4 exists because of the typical failure of a weak model: it writes a
fluent, plausible assessment and omits every bracket. Checking only the
citations that are there then reports a clean verdict on a page of
unsourced prose.

### Several calls in one move

The orchestrator may write any number of TOOL lines in one reply. They run
side by side (the tools are code reading local data or a service, so there
is nothing to wait for between them) and come back as one package, one
note per call, all with the same move number. A tool's output short enough
to keep as it is becomes the note unchanged: it is already factual and
cited, and condensing it would only spend a model call and risk dropping a
value. Long output is condensed as before. A call already in the notes is
dropped from the move; a move made only of repeats is asked again once, and
if it repeats again the gathering closes and the answer is written from the
notes there are: a model that can only repeat itself has nothing new to
fetch. A move runs
at most six calls (a small model asked for "one or more" once wrote sixty);
the step says how many were left out. Calls are read whatever their case
and numbering (`1. Record("PCSK9")`).

Everything a model rereads is fitted to its context (8,192 tokens for the
bundled model): a long tool output given to the condenser keeps its header
and the lines that name the question's genes and terms first; older notes
shorten to their first line before newer ones do; the writer's notes are
fitted the same way. The step always keeps the whole text.

The orchestrator's example names the question's own gene when it has one,
with two calls the notes do not hold yet (`record("PCSK9")` and
`promoter("PCSK9")` first, then the next two): a small model copies the
example whatever it is told, and a copy should at least be a useful move.
Without a gene the example says TP53, and a call naming TP53 when the
question does not is caught as a copy and asked again.

### Thinking, and its cost

The Ask screen switches thinking on or off (`settings.thinking`, on by
default; each run records which). On, the orchestrator reasons when it
plans the first move and when a move could not be run; on the moves
between, the notes say what is missing and it acts. The writer reasons once.
Every trace is capped (320 tokens for a move, 700 for the answer): a small
model left alone spends its trace re-reading its instructions and second-
guessing a decision it has made. At the cap the trace is closed where it
stands and the model answers with it in front of it, instead of the trace
being thrown away. The orchestrator's prompt puts everything that never
changes (the calls, the instructions) before the plan and the notes, so the
local model reuses its processed copy of it from one cycle to the next.

## Nothing is fetched by a model

No agent can look anything up on its own: it names a tool, and the tool is
the same deterministic code the report runs. The roadmap's rule ("The LLM
only reads the record. It never fetches") holds. What a tool reads follows
the user's setting, as the screens do: with online access off (the default)
it reads the mirror and answers cached earlier, and a view that needs an
API says so; with it on, those views fetch and cache exactly as the report
would. This is also what makes the next part work.

## Going back

Every step stores the state the loop was in *before* it ran. Rolling back
to a step restores that checkpoint and discards what came after, and
because the record is fixed, what happens next is well defined: the loop
asks the state what is missing rather than following a script.

The move the orchestrator chose is part of that state, so the two rewinds
mean different things, the distinction needed when a run goes
wrong:

- Rewind a **tool** step and the same source is read again.
- Rewind the **orchestrator** step before it and the move itself is chosen
  again, which is how to get off a bad line of enquiry.
- Rewind the orchestrator's **DONE** and the loop reopens, so a run that
  stopped too early can go round once more.

**Rewind** stops the run if it is going, restores the state that step began
with, and pauses. **Resume** carries on from wherever the state now stands,
with fresh seeds, so a retried step is a new attempt rather than a repeat
of the one that went wrong. Rolled-back steps are moved to the run's
`history` rather than deleted: a run that went down a bad path still shows
that it did.

Every step is written to `data/runs/<id>.json` as it happens, and the
thinking is flushed every half second, so a run that is interrupted,
cancelled or killed leaves everything it had on disk.

## The model

Put a `.gguf` file in `data/models/` and Spica uses the largest one it
finds. `SPICA_MODEL` overrides that with a path, which is how to point at a
model kept on another drive rather than copying tens of gigabytes in.

The runtime is optional:

```bash
./run.sh --agents      # adds llama-cpp-python, prebuilt, no compiler
```

Without it, or with no model file, the agent panel still works, driven by
a scripted stand-in, and the backend chip in the run header says so. That
is deliberate: the pipeline, the thoughts, the schematic and the rollback
are all exercisable on a machine with no weights on it at all, and every
test runs that way.

Reasoning is visible because the backend separates it: Qwen emits its trace
and then `</think>` and then the answer, and `spica/agents/llm.py` labels
each streamed chunk `reasoning` or `answer`. The tag is held back across
chunk boundaries, so a half-tag can never leak into an answer.

### What a small model does

Worth knowing before judging the output. A 0.8B model will circle a simple
instruction for a thousand tokens instead of concluding, so two defences
are in place: a mild presence penalty, which discourages returning to
ground already covered, and a fallback that asks the step again without a
trace when the budget runs out thinking. The trace that was produced stays
on the step, with a line saying why there are two attempts.

The orchestrator is checked three ways, because a weak one fails in three
ways and none of them should pass silently:

- A move naming something that is not a source of this record is refused.
- A move re-reading a source it has already read, while others are unread,
  is refused: it is told what is still unread on every cycle, and choosing
  a spent one anyway is a failure to orchestrate rather than a cycle worth
  burning.
- DONE is not offered at all until enough has been read, so an agreeable
  model cannot end a run having looked at nothing.

Each of those stops the run with a message saying to rewind that step and
try again, which is exactly what the rewind is for.

## Reading a run outside the app

```bash
python -m spica.cli PCSK9        # the record the agents would read
```

The run files are plain JSON: the steps, the thinking, the checkpoints and
the verdict are all in `data/runs/`.
