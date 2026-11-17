"""The loop: an orchestrator picks moves, a tool agent runs them.

The design comes from Betelgeuse, an earlier project. Here it answers an
arbitrary question, not a summary of one gene:

    orchestrator  reads the notes, restates the plan, picks one move
          │
          ▼
    tool agent    runs it, condenses the output into a note
          │
          └───────▶ back to the orchestrator, until it says DONE
                              │
                              ▼
                    writer    answers the question from the notes
                              │
                              ▼
                    verifier  checks each citation, in code

The orchestrator is stateless. All its knowledge comes in its prompt, from
the plan and the notes. The loop can thus run as long as the question needs,
and the context does not grow past what was learned. This also makes a
rollback sound: the notes hold all that the next step needs.

The gene report does not go through here. `spica.build` builds the report,
and the report is deterministic. This module answers questions, and an
answer is synthesised. The loop has the record as one tool among several.
That is not the same as a report written by a model.
"""

from __future__ import annotations

import random
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterator

from spica.agents.run import Note, Run, State
from spica.agents.tools import Tool, catalogue, is_placeholder, parse_call
from spica.agents.verify import verify_answer

#: The loop is bounded at both ends: enough moves that a question is not
#: answered from one lookup, few enough that a model which will not stop is
#: stopped for it.
MIN_CYCLES = 1
MAX_CYCLES = 8

NOTE_TOKENS = 1100
MOVE_TOKENS = 1600
ANSWER_TOKENS = 3000

#: Reasoning is capped, in tokens: a small model left alone spends its
#: trace re-reading its instructions and second-guessing a decision it
#: has already made. Past the cap the trace is closed and it must act.
MOVE_THINKING = 320
WRITE_THINKING = 700

#: A tool's own output shorter than this is the note: it is already short,
#: factual and cited, and condensing it would only add a model call and a
#: chance to drop or alter a value.
PASS_THROUGH = 2400

#: Calls of one move run side by side, up to this many at a time.
PARALLEL = 6

#: What fits in a local model's context, in characters (about 3.5 to a
#: token, for an 8,192-token window): a tool's raw output for the condenser,
#: the notes the orchestrator rereads, and the notes the writer answers from.
#: Each prompt keeps room for its own instructions and its reply.
RAW_CHARS = 14_000
MEMORY_CHARS = 12_000
WRITER_CHARS = 13_000

#: The genes the orchestrator's example names. A call naming one of them
#: when the question does not is the example copied, not a move.
EXAMPLE_GENES = ("TP53",)

#: A move runs at most this many calls. A small model asked for "one or
#: more" can loop on the same line sixty times; the rest are dropped, and
#: the step says so.
MAX_CALLS = 6

#: Small models circle instead of concluding. The penalty discourages
#: returning to ground already covered without capping how long the model
#: may take. Betelgeuse's value, for its reason.
THINKING_PENALTY = 0.5

NOTHING = "NOTHING USEFUL"


class Cancelled(Exception):
    """The run was stopped from the interface."""


class Truncated(Exception):
    """The model spent its whole budget thinking and never answered."""


# -- prompts ----------------------------------------------------------------

ORCHESTRATOR = """You answer a question by gathering evidence, one step at a time.

The calls there are, to be written exactly as shown:
{catalogue}

Reply with a PLAN line, then one or more TOOL lines, and nothing else:

  PLAN: what is still to establish, separated by semicolons
{example}

That is the shape; choose the calls your question needs.
Every TOOL line of one reply runs at the same time, so ask in one reply for
everything you already know you need. Never repeat a call that is in the
notes. {done_option}
Think briefly: what is still missing, and which calls get it. Do not
restate these instructions.

The question: {question}

The plan so far:
{plan}

The notes so far:
{memory}"""

DONE_ALLOWED = """Reply DONE alone once the notes answer the question, or show that it cannot
be answered from what is here.
"""

DONE_BLOCKED = """DONE is not available yet: gather some evidence first.
"""

TOOL_AGENT = """You turn raw output into short factual notes.

The question being worked on: {question}

Where this came from: {move}

Raw output:
---
{raw}
---

Write the few lines worth remembering.
- Keep names, numbers and units exactly as given.
- Keep the citation attached to each fact, in brackets, exactly as it
  appears above: a document and page, or a record field.
- Lead with whatever bears on the question; drop the rest.
- No preamble, no advice, nothing that was not in the output.

If none of it bears on the question, reply with exactly:
{nothing}"""

WRITER = """You answer a question from notes gathered by a research agent.

The question: {question}

Notes:
---
{notes}
---

Write the answer in Markdown.
- Answer the question first, directly, then support it.
- Every factual claim carries the citation it came from, in brackets,
  exactly as the notes write it.
- Quote values and units exactly as the notes give them.
- Say plainly what the notes do not cover. Never fill a gap by guessing.
- No em dashes. Use a comma, a colon or a full stop instead.

No preamble, no mention of being a model."""


# -- the move ---------------------------------------------------------------


class Move:
    """What the orchestrator decided: run one or more calls, or stop."""

    def __init__(self, kind: str, tool: str = "", argument: str = "",
                 plan: list[str] | None = None, reply: str = "",
                 calls: list[tuple[str, str]] | None = None) -> None:
        self.kind = kind  # "run" | "done" | "unreadable" | "repeat" | "placeholder"
        self.calls = calls if calls is not None else ([(tool, argument)] if tool else [])
        self.tool = self.calls[0][0] if self.calls else tool
        self.argument = self.calls[0][1] if self.calls else argument
        self.plan = plan
        self.reply = reply
        self.dropped = 0  # calls past MAX_CALLS, said on the step

    @property
    def call(self) -> str:
        return "; ".join(f'{tool}("{argument}")' for tool, argument in self.calls) or \
            f'{self.tool}("{self.argument}")'


def parse_move(reply: str, allowed: set[str]) -> Move:
    """Read the orchestrator's reply: an optional PLAN line, then the move:
    any number of TOOL lines, or DONE.

    Moves are looked for on every line rather than assumed to be the first,
    so a restated plan above them costs nothing. A call that cannot be run
    is dropped when others in the same reply can be; alone, it is the
    move's problem, as before."""
    plan = None
    calls: list[tuple[str, str]] = []
    problem: Move | None = None
    done = False
    listing = False  # after a bare "TOOL:" line, numbered calls follow
    for raw in (reply or "").splitlines():
        line = raw.strip().strip("`").strip("*").lstrip("-").strip()
        upper = line.upper()
        if upper.startswith("PLAN:"):
            plan = split_plan(line.split(":", 1)[1])
            listing = False
        elif upper.startswith("DONE"):
            done = True
        elif upper.startswith("TOOL:") or (listing and parse_call(line) is not None):
            body = line.split(":", 1)[1] if upper.startswith("TOOL:") else line
            if not body.strip():
                listing = True
                continue
            call = parse_call(body)
            if call is None:
                problem = problem or Move("unreadable", argument=body.strip())
                continue
            name, argument = call
            if name not in allowed:
                problem = problem or Move("unreadable", tool=name, argument=argument)
            elif is_placeholder(argument):
                problem = problem or Move("placeholder", tool=name, argument=argument)
            elif (name, argument) not in calls:
                calls.append((name, argument))
    if calls:
        move = Move("run", plan=plan, reply=reply, calls=calls[:MAX_CALLS])
        move.dropped = max(0, len(calls) - MAX_CALLS)
        return move
    if done:
        return Move("done", plan=plan, reply=reply)
    if problem is not None:
        problem.plan, problem.reply = plan, reply
        return problem
    return Move("unreadable", plan=plan, reply=reply)


def split_plan(text: str) -> list[str]:
    """Semicolon-separated goals into a list, without repeats.

    A small model can state the same goal three times. That is one goal.
    Three entries would make the panel look busier than the run is.
    """
    goals: list[str] = []
    for raw in text.split(";"):
        goal = raw.strip(" -*.")
        if goal and goal.casefold() not in {g.casefold() for g in goals}:
            goals.append(goal)
    return goals


def fit(text: str, limit: int, question: str = "") -> str:
    """`text` within `limit` characters, for a model whose context is finite.

    The first lines (a tool's header) stay; then the lines that name a word
    of the question; then the rest in order, while there is room. What is
    left out is counted on a last line, and the step keeps the whole text."""
    if len(text) <= limit:
        return text
    lines = text.splitlines()
    words = {w for w in re.findall(r"[A-Za-z0-9]{3,}", question.lower())} - {
        "the", "and", "which", "what", "where", "how", "does", "its", "with", "from", "for"}
    head, rest = lines[:2], lines[2:]
    ranked = sorted(range(len(rest)), key=lambda i: (
        0 if words & set(re.findall(r"[a-z0-9]{3,}", rest[i].lower())) else 1, i))
    kept, used = set(), sum(len(line) + 1 for line in head)
    for i in ranked:
        if used + len(rest[i]) + 1 > limit - 120:
            continue
        kept.add(i)
        used += len(rest[i]) + 1
    out = head + [rest[i] for i in sorted(kept)]
    left = len(rest) - len(kept)
    return "\n".join(out + [f"[{left} more lines left out to fit the model's context; the step keeps them all]"])


def render_memory(state: State, limit: int = MEMORY_CHARS) -> str:
    if not state.notes:
        return "(nothing gathered yet)"
    blocks = [f"[{index + 1}] {note.tool_label}: {note.argument}\n{note.text}"
              for index, note in enumerate(state.notes)]
    # The newest notes in full; older ones shortened to their first line
    # when the whole would not fit the model's context.
    while sum(len(b) + 2 for b in blocks) > limit:
        longest = next((i for i, b in enumerate(blocks) if "\n" in b), None)
        if longest is None:
            break
        first, _, _ = blocks[longest].partition("\n")
        blocks[longest] = first + " (shortened to fit; the step keeps the note)"
    return "\n\n".join(blocks)


def render_plan(state: State) -> str:
    if not state.plan:
        return ("(none yet: state what has to be established before this "
                "question can be answered)")
    return "\n".join(f"- {goal}" for goal in state.plan)


# -- the agents -------------------------------------------------------------


def _collect(stream: Iterator[tuple[str, str]], run: Run, stage: str) -> str:
    """Drain a model stream into the run, returning the answer text."""
    answer: list[str] = []
    thought = False
    for kind, text in stream:
        if run.cancelled:
            raise Cancelled()
        run.append(kind, text)
        if kind == "answer":
            answer.append(text)
        else:
            thought = True

    text = "".join(answer).strip()
    if not text and thought:
        raise Truncated(
            f"the model used its whole token budget thinking about the "
            f"{stage} step and never reached an answer"
        )
    return text


def _think_then_answer(backend, run, stage, prompt, temperature, seed, budget,
                       think: bool = True, think_budget: int = 0):
    """Ask with a reasoning trace, and if it never lands, ask without one.

    With thinking switched off for the run, or not wanted at this step, ask
    without one straight away. `think_budget` caps the trace."""
    if not (getattr(run, "thinking", True) and think):
        return _collect(
            backend.stream(prompt, temperature=temperature, thinking=False,
                           seed=seed, max_tokens=budget),
            run, stage,
        )
    try:
        return _collect(
            backend.stream(prompt, temperature=temperature, thinking=True,
                           seed=seed, max_tokens=budget,
                           presence_penalty=THINKING_PENALTY,
                           think_budget=think_budget),
            run, stage,
        )
    except Truncated:
        run.append(
            "reasoning",
            "\n\n[thought past its budget without concluding; "
            "asking again without a trace]\n",
        )
        return _collect(
            backend.stream(prompt, temperature=temperature, thinking=False,
                           seed=seed + 1, max_tokens=budget),
            run, stage,
        )


#: A model that emits an unrunnable move gets one more go with a different
#: seed before the run stops. Weak models produce the literal template line
#: often enough that failing the whole run on the first one is too brittle;
#: twice is a pattern rather than a slip.
MOVE_ATTEMPTS = 2


def next_move(backend, run: Run, tools: dict[str, Tool], seed: int,
              allow_done: bool) -> Move:
    """Ask for a move, retrying once if what comes back cannot be run.

    The retry says what was wrong. A small model that repeats a move or
    copies the format line is usually one sentence of feedback away from a
    good move; asked again blind, it tends to do the same thing.
    """
    hint = ""
    for attempt in range(MOVE_ATTEMPTS):
        move = _ask_move(backend, run, tools, seed + attempt, allow_done, hint)
        if move.kind not in ("unreadable", "placeholder", "repeat"):
            return move
        hint = RETRY_HINTS[move.kind].format(call=f"{move.tool}({move.argument!r})")
        if attempt + 1 < MOVE_ATTEMPTS:
            run.append("reasoning",
                       "\n\n[that move could not be run; asking again]\n")
    return move


#: What the retry tells the model about its last reply.
RETRY_HINTS = {
    "repeat": ("\nYour last reply was {call}, which is already in the notes and would "
               "return the same thing. Choose a different move."),
    "placeholder": ("\nYour last reply, {call}, copied the format line or the example instead of "
                    "calling for your own question. Write real calls from the list, with the genes "
                    "and terms of the question."),
    "unreadable": ("\nYour last reply could not be read as a move. Reply with exactly a PLAN "
                   "line and a TOOL line."),
}


#: Capitals that look like gene symbols but are words of a question.
NOT_GENES = {"DNA", "RNA", "MRNA", "TF", "TFS", "PCR", "QPCR", "SPR", "CRISPR", "KO", "ADC",
             "CAR", "AI", "AND", "OR", "THE", "WHAT", "WHERE", "WHICH", "HOW", "GTEX", "HPA",
             "ENCODE", "GEO", "PDB", "GO", "OMIM", "FDA", "EMA", "USA", "UK", "EU"}


def example_gene(question: str) -> str:
    """The gene the orchestrator's example names: the question's own when it
    names one, so a small model that copies the example still makes a
    useful move; else TP53, which a copy-check then catches."""
    for token in re.findall(r"\b[A-Z][A-Z0-9]{1,9}(?:-[A-Z0-9]+)?\b", question or ""):
        if token not in NOT_GENES and any(c.isdigit() for c in token) or (
                token not in NOT_GENES and len(token) >= 4):
            return token
    return "TP53"


#: Calls the example may show, best first: each takes a gene.
EXAMPLE_TOOLS = ("record", "promoter", "genetics", "organs", "interactions", "regulators",
                 "structure", "isoforms", "coexpressed", "genome", "datasets", "intel", "digest")


def example_calls(question: str, tools: dict, notes: list) -> str:
    """Two TOOL lines for the example: the question's gene with calls the
    notes do not hold yet, since a small model copies whatever it is shown."""
    gene = example_gene(question)
    done = {(note.tool, note.argument.upper()) for note in notes}
    names = [t for t in EXAMPLE_TOOLS if t in tools and (t, gene.upper()) not in done]
    if len(names) < 2:
        names = [t for t in tools if (t, gene.upper()) not in done][:2] or ["record", "genetics"]
    return "\n".join(f'  TOOL: {name}("{gene}")' for name in names[:2])


def cycles_done(state: State) -> int:
    """Moves made so far: notes of one move share a batch number."""
    return max((note.batch or index + 1 for index, note in enumerate(state.notes)), default=0)


def _ask_move(backend, run: Run, tools: dict[str, Tool], seed: int,
              allow_done: bool, hint: str = "") -> Move:
    prompt = ORCHESTRATOR.format(
        example=example_calls(run.question, tools, run.state.notes),
        question=run.question,
        # No "used already" marks: the list stays the same every cycle, so
        # the model's processed copy of everything above the notes is reused.
        catalogue=catalogue(tools),
        plan=render_plan(run.state),
        memory=render_memory(run.state),
        done_option=DONE_ALLOWED if allow_done else DONE_BLOCKED,
    ) + hint
    # Reason when planning the first move only. Between moves the notes say
    # what is missing; after a move that could not be run, a second trace
    # only re-reads the instructions, so the retry answers directly.
    think = not run.state.notes and not hint
    reply = _think_then_answer(
        backend, run, "orchestrator", prompt, 0.6, seed, MOVE_TOKENS,
        think=think, think_budget=MOVE_THINKING,
    )
    move = parse_move(reply, set(tools))

    # The prompt already says DONE is unavailable; this is the belt to that
    # braces, so an eager model cannot end a run having gathered nothing.
    if move.kind == "done" and not allow_done:
        move = Move("unreadable", plan=move.plan, reply=reply)

    # Repeating a call verbatim wastes it. A second search with a different
    # argument is fair; the same one twice is not. Repeats are dropped from
    # the move; a move made only of repeats is refused.
    if move.kind == "run":
        # A call naming the example's gene, when the question does not, is
        # the example copied: dropped, and alone it is asked again.
        copied = [call for call in move.calls
                  if any(g in call[1].upper() and g not in run.question.upper() for g in EXAMPLE_GENES)]
        if copied and len(copied) == len(move.calls):
            return Move("placeholder", tool=copied[0][0], argument=copied[0][1],
                        plan=move.plan, reply=reply)
        move.calls = [call for call in move.calls if call not in copied]
        before = {(note.tool, note.argument) for note in run.state.notes}
        fresh = [call for call in move.calls if call not in before]
        if not fresh:
            move = Move("repeat", tool=move.tool, argument=move.argument,
                        plan=move.plan, reply=reply)
        else:
            dropped = move.dropped
            move = Move("run", plan=move.plan, reply=reply, calls=fresh)
            move.dropped = dropped
    return move


def run_tool(backend, run: Run, tools: dict[str, Tool], move: Move,
             seed: int) -> Note:
    """Run the move, then condense what came back into notes.

    Condensing is where Betelgeuse's two-model split earns itself: this is
    transcription, not judgement, so it runs without a reasoning trace and
    is sampled narrowly. Whatever it leaves out is gone unless the tool is
    called again, which is why the raw output stays on the step.
    """
    tool = tools[move.tool]
    try:
        finding = tool.run(move.argument)
    except Exception as exc:
        return Note(tool=move.tool, tool_label=tool.label, argument=move.argument,
                    text=f"{tool.label} failed: {type(exc).__name__}: {exc}")

    if finding.problem or finding.empty:
        return Note(tool=move.tool, tool_label=tool.label, argument=move.argument,
                    text=finding.problem or "nothing came back")

    if finding.raw:
        run.append("answer", f"{finding.raw}\n")
    prompt = TOOL_AGENT.format(question=run.question, move=move.call,
                               raw=finding.text, nothing=NOTHING)
    condensed = _collect(
        backend.stream(prompt, temperature=0.2, thinking=False, seed=seed,
                       max_tokens=NOTE_TOKENS),
        run, "tool agent",
    )
    if not condensed or NOTHING in condensed.upper():
        return Note(tool=move.tool, tool_label=tool.label, argument=move.argument,
                    text=f"Nothing in {tool.label} bears on this.")

    # Keep the citations the tool vouched for, not the ones the model wrote:
    # a condenser that invents a page number would otherwise pass the check.
    kept = [c for c in finding.citations if c in condensed or c.strip("[]") in condensed]
    return Note(tool=move.tool, tool_label=tool.label, argument=move.argument,
                text=condensed, fields=kept or finding.citations[:3], sources=finding.text)


def run_tools(backend, run: Run, tools: dict[str, Tool], calls: list[tuple[str, str]],
              seed: int, batch: int) -> list[Note]:
    """Every call of one move, run side by side, each leaving a note.

    The tools are deterministic code reading local data or a service, so
    they run at once; their outputs come back as one package. Short output
    is the note as it stands. Long output is condensed by the model, one
    call after another, since the model runs one thing at a time."""
    def attempt(call: tuple[str, str]):
        name, argument = call
        try:
            return tools[name].run(argument), None
        except Exception as exc:
            return None, exc

    with ThreadPoolExecutor(max_workers=max(1, min(PARALLEL, len(calls)))) as pool:
        results = list(pool.map(attempt, calls))

    notes = []
    for (name, argument), (finding, error) in zip(calls, results):
        if run.cancelled:
            raise Cancelled()
        tool = tools[name]
        base = dict(tool=name, tool_label=tool.label, argument=argument, batch=batch)
        if error is not None:
            notes.append(Note(**base, text=f"{tool.label} failed: {type(error).__name__}: {error}"))
            continue
        if finding.problem or finding.empty:
            notes.append(Note(**base, text=finding.problem or "nothing came back"))
            continue
        if finding.raw:
            run.append("answer", f"{finding.raw}\n")
        if len(finding.text) <= PASS_THROUGH:
            notes.append(Note(**base, text=finding.text.strip(), fields=list(finding.citations),
                              sources=finding.text))
            continue
        prompt = TOOL_AGENT.format(question=run.question, move=f'{name}("{argument}")',
                                   raw=fit(finding.text, RAW_CHARS, run.question), nothing=NOTHING)
        condensed = _collect(
            backend.stream(prompt, temperature=0.2, thinking=False, seed=seed,
                           max_tokens=NOTE_TOKENS),
            run, "tool agent",
        )
        if not condensed or NOTHING in condensed.upper():
            notes.append(Note(**base, text=f"Nothing in {tool.label} bears on this."))
            continue
        kept = [c for c in finding.citations if c in condensed or c.strip("[]") in condensed]
        notes.append(Note(**base, text=condensed, fields=kept or finding.citations[:3],
                          sources=finding.text))
    return notes


def run_write(backend, run: Run, seed: int) -> str:
    notes = fit("\n\n".join(
        f"[{index + 1}] {note.tool_label}: {note.argument}\n{note.text}"
        for index, note in enumerate(run.state.notes) if note.text
    ), WRITER_CHARS, run.question)
    prompt = WRITER.format(question=run.question, notes=notes or "(none)")
    return _think_then_answer(backend, run, "writer", prompt, 0.4, seed,
                              ANSWER_TOKENS, think_budget=WRITE_THINKING)


# -- what runs next ---------------------------------------------------------


def next_stage(state: State) -> str:
    """The stage to run now, from the state alone.

    Derived rather than scripted, so resuming after a rollback needs no
    special case: ask the state what is missing and do that.
    """
    if state.draft and state.verdict is None:
        return "verify"
    if state.draft:
        return ""
    if state.pending:  # a move was chosen and has not been run yet
        return "tool"
    if state.closed:
        return "write"
    return "orchestrate"


# -- the loop ---------------------------------------------------------------


def execute(
    run: Run,
    tools: dict[str, Tool] | None = None,
    backend=None,
    seeds: Callable[[], int] | None = None,
) -> None:
    """Run the loop to the end, or until it is cancelled or fails."""
    from spica.agents.tools import default_tools

    tools = default_tools() if tools is None else tools
    draw = seeds or (lambda: random.randrange(1, 2 ** 31 - 1))
    if not tools:
        run.fail("No tool available.")
        return

    try:
        while True:
            if run.cancelled:
                return

            stage = next_stage(run.state)
            if not stage:
                run.done()
                return

            if stage == "verify":
                # No model here: a checker that can hallucinate is not a check.
                run.begin("verify", "Check every citation", 0)
                verdict = verify_answer(run.state.draft, run.state.notes)
                run.state.verdict = verdict
                run.append("answer", verdict["summary"])
                run.finish(verdict["summary"])
                continue

            if stage == "write":
                seed = draw()
                run.begin("write", "Write the answer", seed)
                draft = run_write(backend, run, seed)
                if not draft:
                    run.fail("Writer output empty.")
                    return
                run.state.draft = draft
                run.finish(draft)
                continue

            cycle = cycles_done(run.state) + 1

            if stage == "tool":
                calls = [tuple(part.partition("\x00")[::2]) for part in run.state.pending.split("\x01")]
                missing = [name for name, _ in calls if name not in tools]
                labels = [tools[name].label if name in tools else name for name, _ in calls]
                title = (f"{labels[0]}: {calls[0][1]}" if len(calls) == 1
                         else f"{len(calls)} calls at once: " + "; ".join(
                             f"{label}: {argument}" for label, (_, argument) in zip(labels, calls)))
                seed = draw()
                run.begin("tool", title, seed, cycle=cycle,
                          tool=",".join(name for name, _ in calls), tool_label=", ".join(labels))
                if missing:
                    run.fail(f"{missing[0]} is not a tool that exists.")
                    return
                notes = run_tools(backend, run, tools, calls, seed, batch=cycle)
                run.state.notes.extend(notes)
                run.state.pending = ""
                run.finish("\n\n".join(note.text for note in notes))
                continue

            # The orchestrator: read the notes, restate the plan, pick a move.
            if cycle > MAX_CYCLES and run.state.notes:
                run.state.closed = True  # out of cycles: answer from what there is
                continue

            seed = draw()
            run.begin("orchestrate", f"Move {cycle}", seed, cycle=cycle)
            move = next_move(backend, run, tools, seed,
                             allow_done=len(run.state.notes) >= MIN_CYCLES)
            if move.plan is not None:
                run.state.plan = move.plan

            if move.kind in ("unreadable", "placeholder") and run.state.notes:
                # Evidence exists, and the planner can no longer make a move.
                # (The prompt of a small model grows with its notes until it
                # loses the thread.) The writer answers from the notes, and
                # the step gives the reason the gathering stopped.
                run.state.closed = True
                run.finish("No move could be read after a retry: answering from the notes gathered so far.")
                continue

            if move.kind == "unreadable":
                named = move.tool or move.argument
                run.fail(
                    f"Orchestrator move not runnable"
                    f"{': ' + named if named else ''}."
                )
                return

            if move.kind == "placeholder":
                run.fail(f"Orchestrator move copied from the example: {move.call}.")
                return

            if move.kind == "repeat":
                # Asked again and still only calls already made: it has
                # nothing new to fetch, so the gathering closes and the
                # answer is written from the notes there are.
                run.state.closed = True
                run.finish(f"Only calls already made ({move.call}): answering from the notes.")
                continue

            if move.kind == "done":
                run.state.closed = True
                run.finish("DONE: the notes answer the question.")
                continue

            run.state.pending = "\x01".join(f"{tool}\x00{argument}" for tool, argument in move.calls)
            run.finish("\n".join(f'TOOL: {tool}("{argument}")' for tool, argument in move.calls)
                       + (f"\n[{move.dropped} more calls left out: a move runs at most {MAX_CALLS}]"
                          if move.dropped else ""))

    except Cancelled:
        return
    except Truncated as exc:
        run.fail(str(exc))
        return
    except Exception as exc:  # a failed run remains a run that can be rolled back
        run.fail(f"{type(exc).__name__}: {exc}")
