"""The agent loop, against a scripted model and stub tools.

No test here loads a model or reads a real corpus: `Loop` replays moves,
and the tools are stubs. That is what makes the loop, the streaming split,
the checkpoints and the rewind testable in milliseconds. The one thing
that genuinely cannot be faked (the verifier) is code rather than a
model, so it is tested directly.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spica.agents import pipeline
from spica.agents.llm import Scripted, split_thinking_stream
from spica.agents.run import Note, Run, State
from spica.agents.session import Agents
from spica.agents.tools import Finding, catalogue, is_placeholder, parse_call
from spica.agents.verify import verify, verify_answer
from spica.build import build_record
from spica.live import Live
from spica.mirror import Mirror

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"

QUESTION = "where is PCSK9 expressed?"

MOVES = (
    'PLAN: what the documents say; what the record says\n'
    'TOOL: documents("PCSK9 expression")',
    'PLAN: what the record says\nTOOL: record("PCSK9")',
    "PLAN:\nDONE",
)

ANSWER = (
    "PCSK9 is liver-dominant [memo.pdf, p1].\n\n"
    "## Record\nThe record agrees [gtex_max_tissue]."
)


def record():
    return build_record("PCSK9", Mirror.load(FIXTURE), Live(FIXTURE, allowed=False))


class StubTool:
    """A tool that returns what it was told to, and counts its calls."""

    def __init__(self, key, label, finding=None, usage=None):
        self.key = key
        self.label = label
        self.usage = usage or f'{key}("<argument>") -> something'
        self._finding = finding or Finding(
            f"{label} says something [{key}.pdf, p1].",
            citations=[f"{key}.pdf, p1"], raw=f"{label} raw")
        self.calls: list[str] = []

    def status(self) -> str:
        return "ready"

    def run(self, argument: str) -> Finding:
        self.calls.append(argument)
        return self._finding


def stub_tools() -> dict:
    return {
        "documents": StubTool("documents", "Your documents",
                              Finding("Delivery is the bottleneck [memo.pdf, p1].",
                                      citations=["memo.pdf, p1"], raw="1 passage")),
        "record": StubTool("record", "Gene record",
                           Finding("Liver is highest [gtex_max_tissue].",
                                   citations=["[gtex_max_tissue]"], raw="20 fields")),
    }


class Loop(Scripted):
    """A scripted model whose orchestrator plays a fixed series of moves.

    The loop asks the orchestrator the same question in each cycle, and only
    the notes change. The moves thus come out in order; they do not depend
    on the prompt.
    """

    def __init__(self, moves=MOVES, note=None, answer=ANSWER):
        super().__init__(replies={
            "turn raw output into short factual notes":
                ("", note or "Delivery is the bottleneck [memo.pdf, p1]."),
            "answer a question from notes": ("composing", answer),
        })
        self.moves = list(moves)

    def stream(self, prompt, **kw):
        if "gathering evidence, one step at a time" in prompt:
            self.calls.append(prompt)
            reply = self.moves.pop(0) if self.moves else "DONE"
            yield "reasoning", "weighing it up"
            for piece in re.findall(r"\S+\s*", reply):
                yield "answer", piece
            return
        yield from super().stream(prompt, **kw)


def drive(run: Run, llm, tools=None) -> None:
    """Run the loop on this thread, so tests stay deterministic."""
    seeds = iter(range(1, 99))
    pipeline.execute(run, tools if tools is not None else stub_tools(), llm,
                     seeds=lambda: next(seeds))


class TestStreamSplit(unittest.TestCase):
    def test_reasoning_and_answer_are_separated(self):
        pieces = ["thinking ", "hard", "</think>", "the answer"]
        out = list(split_thinking_stream(iter(pieces), True))
        # How it is chunked is the splitter's business; which side each piece
        # lands on is not.
        self.assertEqual("".join(t for k, t in out if k == "reasoning"), "thinking hard")
        self.assertEqual("".join(t for k, t in out if k == "answer"), "the answer")

    def test_a_tag_split_across_chunks_never_leaks(self):
        # The failure this prevents: "</thi" shown as reasoning, "nk>" as answer.
        pieces = ["thinking", "</", "thi", "nk>", "answer"]
        out = list(split_thinking_stream(iter(pieces), True))
        self.assertNotIn("<", "".join(t for _, t in out))
        self.assertEqual("".join(t for k, t in out if k == "answer"), "answer")

    def test_an_opening_tag_from_the_model_is_dropped(self):
        out = list(split_thinking_stream(iter(["<think>", "why", "</think>", "so"]), True))
        self.assertEqual("".join(t for k, t in out if k == "reasoning"), "why")

    def test_without_thinking_everything_is_an_answer(self):
        out = list(split_thinking_stream(iter(["a", "b"]), False))
        self.assertEqual({k for k, _ in out}, {"answer"})


class TestCalls(unittest.TestCase):
    def test_a_quoted_argument(self):
        self.assertEqual(parse_call('documents("delivery to hepatocytes")'),
                         ("documents", "delivery to hepatocytes"))

    def test_quotes_are_optional_because_models_forget_them(self):
        self.assertEqual(parse_call("record(PCSK9)"), ("record", "PCSK9"))

    def test_single_quotes_too(self):
        self.assertEqual(parse_call("documents('a b')"), ("documents", "a b"))

    def test_an_empty_argument_is_still_a_call(self):
        self.assertEqual(parse_call("documents()"), ("documents", ""))

    def test_something_that_is_not_a_call(self):
        self.assertIsNone(parse_call("just go and look it up"))

    def test_the_catalogue_marks_what_has_been_used(self):
        rendered = catalogue(stub_tools(), used=["documents"])
        self.assertIn("(used already)", rendered)
        self.assertIn("record(", rendered)


class TestPlaceholders(unittest.TestCase):
    """A model that copies the prompt's example instead of filling it in.

    The word boundaries in this pattern were once written as backspace
    characters, so only the angle-bracket form was ever caught.
    """

    def test_copied_examples_are_caught(self):
        for text in ("GENE1, GENE2", "gene2", "your question", "The question", "<one call>"):
            self.assertTrue(is_placeholder(text), text)

    def test_real_arguments_pass(self):
        for text in ("PCSK9", "CLDN18, MSLN", "delivery to hepatocytes", "GENE10X"):
            self.assertFalse(is_placeholder(text), text)


class TestMoves(unittest.TestCase):
    ALLOWED = {"documents", "record"}

    def parse(self, reply: str):
        return pipeline.parse_move(reply, self.ALLOWED)

    def test_a_plan_and_a_move(self):
        move = self.parse('PLAN: one; two\nTOOL: documents("delivery")')
        self.assertEqual(move.kind, "run")
        self.assertEqual((move.tool, move.argument), ("documents", "delivery"))
        self.assertEqual(move.plan, ["one", "two"])

    def test_the_move_is_found_below_a_restated_plan(self):
        self.assertEqual(self.parse('PLAN: a\n\nTOOL: record("X")').tool, "record")

    def test_done(self):
        self.assertEqual(self.parse("PLAN:\nDONE").kind, "done")

    def test_a_tool_that_does_not_exist_is_refused(self):
        move = self.parse('TOOL: pubmed("cancer")')
        self.assertEqual(move.kind, "unreadable")
        self.assertEqual(move.tool, "pubmed")

    def test_something_that_is_not_a_call_is_refused(self):
        self.assertEqual(self.parse("TOOL: go and look").kind, "unreadable")

    def test_an_empty_reply_is_refused_rather_than_guessed(self):
        self.assertEqual(self.parse("").kind, "unreadable")

    def test_repeated_goals_collapse(self):
        self.assertEqual(pipeline.split_plan("a; A ; b; a"), ["a", "b"])


class TestLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Run(QUESTION, "scripted", root=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_alternates_orchestrator_and_tool_agent_then_closes(self):
        drive(self.run, Loop())
        self.assertEqual(self.run.status, "done", self.run.error)
        self.assertEqual(
            [step.stage for step in self.run.steps],
            ["orchestrate", "tool", "orchestrate", "tool",
             "orchestrate", "write", "verify"],
        )

    def test_the_run_is_bound_to_a_question_not_a_gene(self):
        llm = Loop()
        # Condensing only happens to long output; make every output long.
        with mock.patch.object(pipeline, "PASS_THROUGH", 0):
            drive(self.run, llm)
        self.assertEqual(self.run.question, QUESTION)
        # The question reaches every agent that has to know it.
        orchestrator = [c for c in llm.calls if "one step at a time" in c]
        condensers = [c for c in llm.calls if "short factual notes" in c]
        writer = [c for c in llm.calls if "answer a question from notes" in c]
        for prompts in (orchestrator, condensers, writer):
            self.assertTrue(prompts)
            self.assertIn(QUESTION, prompts[0])

    def test_each_cycle_records_the_move_it_made(self):
        drive(self.run, Loop())
        fired = [(s.cycle, s.tool) for s in self.run.steps if s.stage == "tool"]
        self.assertEqual(fired, [(1, "documents"), (2, "record")])
        self.assertEqual(self.run.state.notes[0].argument, "PCSK9 expression")

    def test_the_tool_is_called_with_the_argument_the_model_chose(self):
        tools = stub_tools()
        drive(self.run, Loop(), tools)
        self.assertEqual(tools["documents"].calls, ["PCSK9 expression"])
        self.assertEqual(tools["record"].calls, ["PCSK9"])

    def test_the_orchestrator_step_shows_the_call_it_chose(self):
        drive(self.run, Loop())
        self.assertEqual(self.run.steps[0].output, 'TOOL: documents("PCSK9 expression")')
        self.assertIn("DONE", self.run.steps[4].output)

    def test_thinking_switched_off_asks_every_agent_plainly(self):
        asked = []

        class Recording(Loop):
            def stream(self, prompt, **kw):
                asked.append(kw.get("thinking", True))
                yield from super().stream(prompt, **kw)

        self.run.thinking = False
        drive(self.run, Recording())
        self.assertEqual(self.run.status, "done", self.run.error)
        self.assertTrue(asked)
        self.assertNotIn(True, asked)
        self.assertFalse(self.run.snapshot()["thinking"])

    def test_the_thinking_lands_on_the_step_that_thought_it(self):
        drive(self.run, Loop())
        self.assertIn("weighing it up", self.run.steps[0].thought)
        # Condensing is transcription, so the tool agent does not deliberate.
        self.assertEqual(self.run.steps[1].thought, "")

    def test_a_note_keeps_only_citations_the_tool_vouched_for(self):
        # A condenser that invents a page number must not pass the check.
        llm = Loop(note="Delivery is hard [invented.pdf, p9].")
        with mock.patch.object(pipeline, "PASS_THROUGH", 0):
            drive(self.run, llm)
        self.assertEqual(self.run.state.notes[0].fields, ["memo.pdf, p1"])

    def test_short_tool_output_is_the_note_without_a_model_call(self):
        llm = Loop()
        drive(self.run, llm)
        self.assertFalse([c for c in llm.calls if "short factual notes" in c])
        self.assertEqual(self.run.state.notes[0].text, "Delivery is the bottleneck [memo.pdf, p1].")
        self.assertEqual(self.run.state.notes[0].fields, ["memo.pdf, p1"])

    def test_one_move_can_call_several_tools_at_once(self):
        tools = stub_tools()
        moves = ('PLAN: both at once\nTOOL: documents("PCSK9 expression")\nTOOL: record("PCSK9")',
                 "PLAN:\nDONE")
        drive(self.run, Loop(moves=moves), tools)
        self.assertEqual(self.run.status, "done", self.run.error)
        self.assertEqual([step.stage for step in self.run.steps],
                         ["orchestrate", "tool", "orchestrate", "write", "verify"])
        self.assertEqual(self.run.steps[1].tool, "documents,record")
        self.assertEqual([(n.tool, n.batch) for n in self.run.state.notes], [("documents", 1), ("record", 1)])
        self.assertEqual((tools["documents"].calls, tools["record"].calls), (["PCSK9 expression"], ["PCSK9"]))

    def test_a_small_models_numbered_capitalised_calls_are_read(self):
        reply = 'PLAN: expression; regulators\nTOOL:\n1. Record("PCSK9")\n2. promoter("PCSK9")\n'
        move = pipeline.parse_move(reply, {"record", "promoter"})
        self.assertEqual(move.kind, "run")
        self.assertEqual(move.calls, [("record", "PCSK9"), ("promoter", "PCSK9")])

    def test_long_text_is_fitted_keeping_what_names_the_question(self):
        text = "header\nsource line\n" + "\n".join(f"filler line {i} " + "x" * 60 for i in range(200)) \
            + "\nPCSK9 is highest in liver"
        fitted = pipeline.fit(text, 2000, "where is PCSK9 expressed?")
        self.assertLessEqual(len(fitted), 2000)
        self.assertTrue(fitted.startswith("header\nsource line"))
        self.assertIn("PCSK9 is highest in liver", fitted)
        self.assertIn("more lines left out", fitted)
        self.assertEqual(pipeline.fit("short", 2000), "short")

    def test_the_example_shows_calls_the_notes_do_not_hold(self):
        tools = {"record": None, "promoter": None, "genetics": None}
        first = pipeline.example_calls("Where is PCSK9 expressed?", tools, [])
        self.assertEqual(first, '  TOOL: record("PCSK9")\n  TOOL: promoter("PCSK9")')
        later = pipeline.example_calls("Where is PCSK9 expressed?", tools,
                                       [Note(tool="record", tool_label="Gene record", text="", argument="PCSK9")])
        self.assertEqual(later, '  TOOL: promoter("PCSK9")\n  TOOL: genetics("PCSK9")')

    def test_the_example_names_the_questions_own_gene(self):
        self.assertEqual(pipeline.example_gene("Where is PCSK9 expressed?"), "PCSK9")
        self.assertEqual(pipeline.example_gene("Compare CLDN18 and MSLN as ADC targets"), "CLDN18")
        self.assertEqual(pipeline.example_gene("Which of our assays used SPR?"), "TP53")

    def test_copying_the_examples_gene_is_asked_again(self):
        moves = ('PLAN: x\nTOOL: record("TP53")', 'PLAN: x\nTOOL: record("PCSK9")', "PLAN:\nDONE")
        tools = stub_tools()
        drive(self.run, Loop(moves=moves), tools)
        self.assertEqual(self.run.status, "done", self.run.error)
        self.assertEqual(tools["record"].calls, ["PCSK9"])

    def test_a_move_runs_at_most_max_calls_and_says_so(self):
        reply = "PLAN: x\n" + "\n".join(f'TOOL: record("G{i}")' for i in range(10))
        move = pipeline.parse_move(reply, {"record"})
        self.assertEqual(len(move.calls), pipeline.MAX_CALLS)
        self.assertEqual(move.dropped, 10 - pipeline.MAX_CALLS)

    def test_a_repeated_call_is_dropped_and_the_new_one_runs(self):
        tools = stub_tools()
        moves = ('PLAN: a\nTOOL: documents("PCSK9 expression")',
                 'PLAN: b\nTOOL: documents("PCSK9 expression")\nTOOL: record("PCSK9")',
                 "PLAN:\nDONE")
        drive(self.run, Loop(moves=moves), tools)
        self.assertEqual(self.run.status, "done", self.run.error)
        self.assertEqual(tools["documents"].calls, ["PCSK9 expression"])
        self.assertEqual(tools["record"].calls, ["PCSK9"])

    def test_the_orchestrator_reasons_when_planning_not_on_every_move(self):
        asked = []

        class Recording(Loop):
            def stream(self, prompt, **kw):
                if "one step at a time" in prompt:
                    asked.append((kw.get("thinking", True), kw.get("think_budget", 0)))
                yield from super().stream(prompt, **kw)

        drive(self.run, Recording())
        self.assertEqual(self.run.status, "done", self.run.error)
        self.assertEqual([thinking for thinking, _ in asked], [True, False, False])
        self.assertEqual(asked[0][1], pipeline.MOVE_THINKING)

    def test_a_thinking_budget_closes_the_trace_and_the_answer_still_comes(self):
        llm = Scripted(replies={"q": (" ".join(["mulling"] * 50), "the answer")})
        out = list(llm.stream("q", thinking=True, think_budget=5))
        reasoning = "".join(t for k, t in out if k == "reasoning")
        self.assertEqual(reasoning.count("mulling"), 5)
        self.assertIn("budget", reasoning)
        self.assertEqual("".join(t for k, t in out if k == "answer"), "the answer")

    def test_a_tool_that_raises_becomes_a_note_not_a_crash(self):
        class Broken(StubTool):
            def run(self, argument):
                raise RuntimeError("disk gone")

        tools = stub_tools()
        tools["documents"] = Broken("documents", "Your documents")
        drive(self.run, Loop(), tools)
        self.assertEqual(self.run.status, "done", self.run.error)
        self.assertIn("disk gone", self.run.state.notes[0].text)

    def test_a_tool_with_nothing_to_say_is_recorded_as_such(self):
        tools = stub_tools()
        tools["documents"] = StubTool("documents", "Your documents",
                                      Finding("", problem="no index yet"))
        drive(self.run, Loop(), tools)
        self.assertIn("no index yet", self.run.state.notes[0].text)

    def test_repeating_a_move_verbatim_closes_the_gathering(self):
        # The repeat is never run: asked again, a model that repeats once
        # more has nothing new to fetch, and the answer is written from the notes.
        tools = stub_tools()
        thrice = ('PLAN: a\nTOOL: documents("x")',) * 3
        drive(self.run, Loop(moves=thrice), tools)
        self.assertEqual(self.run.status, "done", self.run.error)
        self.assertEqual(tools["documents"].calls, ["x"])
        self.assertIn("answering from the notes", self.run.steps[2].output)

    def test_a_repeat_is_asked_again_with_what_was_wrong(self):
        moves = ('PLAN: a\nTOOL: documents("x")', 'PLAN: a\nTOOL: documents("x")',
                 'PLAN: a\nTOOL: documents("y")', "DONE")
        drive(self.run, Loop(moves=moves))
        self.assertEqual(self.run.status, "done", self.run.error)
        self.assertEqual([n.argument for n in self.run.state.notes], ["x", "y"])

    def test_the_same_tool_with_a_different_argument_is_fine(self):
        again = ('PLAN: a\nTOOL: documents("x")',
                 'PLAN: a\nTOOL: documents("y")', "DONE")
        drive(self.run, Loop(moves=again))
        self.assertEqual(self.run.status, "done", self.run.error)
        self.assertEqual([n.argument for n in self.run.state.notes], ["x", "y"])

    def test_copying_the_example_out_of_the_tool_list_is_refused(self):
        # Typical small-model failure: the placeholder run verbatim.
        # It gets one retry; a model that copies the example once copies it
        # twice, and that is the pattern the run should stop on.
        copied = ('PLAN: a\nTOOL: documents("<what to find>")',) * 2
        drive(self.run, Loop(moves=copied))
        self.assertEqual(self.run.status, "failed")
        self.assertIn("copied from the example", self.run.error)

    def test_a_move_that_cannot_be_run_stops_the_run_with_a_reason(self):
        drive(self.run, Loop(moves=('PLAN: a\nTOOL: pubmed("x")',) * 2))
        self.assertEqual(self.run.status, "failed")
        self.assertIn("move not runnable", self.run.error)
        self.assertIn("pubmed", self.run.error)

    def test_a_planner_that_loses_the_thread_after_evidence_still_answers(self):
        tools = stub_tools()
        moves = ('PLAN: a\nTOOL: documents("delivery")', "PLAN; SECIL; SECIL", "PLAN; SECIL; SECIL")
        drive(self.run, Loop(moves=moves), tools)
        self.assertEqual(self.run.status, "done", self.run.error)
        self.assertEqual([s.stage for s in self.run.steps][-2:], ["write", "verify"])
        self.assertIn("answering from the notes", self.run.steps[2].output)

    def test_an_unrunnable_move_is_retried_before_the_run_stops(self):
        tools = stub_tools()
        recovered = ('PLAN: a\nTOOL: pubmed("x")',
                     'PLAN: a\nTOOL: documents("delivery")', "DONE")
        drive(self.run, Loop(moves=recovered), tools)
        self.assertEqual(self.run.status, "done", self.run.error)
        self.assertEqual(tools["documents"].calls, ["delivery"])
        self.assertIn("asking again", self.run.steps[0].thought)

    def test_a_loop_that_will_not_stop_is_stopped_for_it(self):
        forever = tuple(f'PLAN: a\nTOOL: documents("{n}")' for n in range(20))
        drive(self.run, Loop(moves=forever))
        self.assertEqual(self.run.status, "done", self.run.error)
        self.assertEqual(len(self.run.state.notes), pipeline.MAX_CYCLES)
        self.assertTrue(self.run.state.draft)

    def test_every_step_is_written_to_disk_as_it_goes(self):
        drive(self.run, Loop())
        saved = json.loads(self.run.path.read_text(encoding="utf-8"))
        self.assertEqual(len(saved["steps"]), 7)
        self.assertEqual(saved["status"], "done")
        self.assertEqual(saved["question"], QUESTION)

    def test_a_model_that_only_thinks_is_asked_again_plainly(self):
        class OnlyThinks(Loop):
            def stream(self, prompt, *, thinking=True, **kw):
                if thinking and "one step at a time" in prompt and not self.calls:
                    self.calls.append(prompt)
                    yield "reasoning", "circling the point forever"
                    return
                yield from super().stream(prompt, thinking=thinking, **kw)

        drive(self.run, OnlyThinks())
        self.assertEqual(self.run.status, "done", self.run.error)
        self.assertIn("thought past its budget", self.run.steps[0].thought)


class TestRollback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Run(QUESTION, "scripted", root=Path(self.tmp.name))
        drive(self.run, Loop())

    def tearDown(self):
        self.tmp.cleanup()

    def test_rolling_back_restores_the_state_the_step_began_in(self):
        self.assertEqual(len(self.run.state.notes), 2)
        self.assertEqual(self.run.rollback_to(3), "")  # the second tool step
        self.assertEqual(len(self.run.state.notes), 1)
        self.assertEqual(self.run.state.draft, "")
        self.assertFalse(self.run.state.closed)
        self.assertIsNone(self.run.state.verdict)
        self.assertEqual(self.run.status, "paused")

    def test_nothing_is_thrown_away(self):
        self.run.rollback_to(3)
        self.assertEqual(len(self.run.steps), 3)
        self.assertEqual(len(self.run.history), 4)

    def test_rewinding_a_tool_step_re_runs_that_move(self):
        # Not "choose again": the move is part of the state, so the same
        # call is made a second time.
        self.run.rollback_to(3)
        self.assertEqual(self.run.state.pending, "record\x00PCSK9")
        self.assertEqual(pipeline.next_stage(self.run.state), "tool")
        self.run.resuming()
        drive(self.run, Loop(moves=("PLAN:\nDONE",)))
        self.assertEqual(self.run.status, "done", self.run.error)
        self.assertEqual(self.run.steps[3].tool, "record")

    def test_rolling_back_to_the_start_empties_everything(self):
        self.run.rollback_to(0)
        self.assertEqual(self.run.state.plan, [])
        self.assertEqual(self.run.state.notes, [])
        self.assertEqual(pipeline.next_stage(self.run.state), "orchestrate")

    def test_rolling_back_past_done_reopens_the_loop(self):
        self.run.rollback_to(4)
        self.assertFalse(self.run.state.closed)
        self.assertEqual(pipeline.next_stage(self.run.state), "orchestrate")

    def test_a_step_that_is_not_there_is_refused(self):
        self.assertIn("No step", self.run.rollback_to(99))

    def test_a_running_run_is_not_rolled_back_underneath_itself(self):
        self.run.status = "running"
        self.assertIn("still going", self.run.rollback_to(1))


class TestAnswerVerifier(unittest.TestCase):
    """AI mode: a citation has to be one a tool returned."""

    def notes(self):
        return [Note("documents", "Your documents", "Delivery is hard.",
                     argument="delivery", fields=["memo.pdf, p1"])]

    def test_a_citation_a_tool_returned_holds(self):
        verdict = verify_answer("Delivery is the bottleneck [memo.pdf, p1].",
                                self.notes())
        self.assertTrue(verdict["ok"], verdict["problems"])

    def test_an_invented_source_fails(self):
        # The failure that matters: a plausible page number no tool returned.
        verdict = verify_answer("It improves delivery [imaginary.pdf, p9].",
                                self.notes())
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["problems"][0]["kind"], "unknown_source")
        self.assertIn("invented", verdict["problems"][0]["detail"])

    def test_a_note_number_is_a_fair_citation(self):
        verdict = verify_answer("See note [1].", self.notes())
        self.assertTrue(verdict["ok"], verdict["problems"])

    def test_a_note_number_that_does_not_exist_fails(self):
        verdict = verify_answer("See note [7].", self.notes())
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["problems"][0]["kind"], "unknown_source")

    def test_a_number_with_no_citation_fails(self):
        verdict = verify_answer("It improved by 40 percent.", self.notes())
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["problems"][0]["kind"], "uncited_number")

    def test_an_answer_that_cites_nothing_fails_however_it_reads(self):
        draft = ("This looks like a confident answer and it is sourced to "
                 "nothing at all, which is the point.")
        verdict = verify_answer(draft, self.notes())
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["problems"][0]["kind"], "nothing_cited")

    def test_an_empty_answer_says_so(self):
        self.assertEqual(verify_answer("", self.notes())["summary"],
                         "Nothing to check: the answer is empty.")


class TestRecordVerifier(unittest.TestCase):
    """The deterministic side: a claim cites a schema field."""

    def setUp(self):
        self.record = record()

    def test_a_claim_citing_a_real_filled_field_holds(self):
        self.assertTrue(verify("Liver is highest [gtex_max_tissue].",
                               self.record)["ok"])

    def test_citing_a_field_that_does_not_exist_fails(self):
        verdict = verify("It binds things [binding_affinity].", self.record)
        self.assertEqual(verdict["problems"][0]["kind"], "unknown_field")

    def test_citing_an_empty_field_fails(self):
        verdict = verify("Staining is strong [hpa_protein_tissue_intensity].",
                         self.record)
        self.assertEqual(verdict["problems"][0]["kind"], "empty_field")

    def test_a_number_that_is_in_the_cited_field_holds(self):
        self.assertTrue(verify("Liver is 77.41 [gtex_tissue_tpm].",
                               self.record)["ok"])

    def test_a_number_that_is_not_in_the_cited_field_is_flagged(self):
        verdict = verify("Liver is 500.0 [gtex_tissue_tpm].", self.record)
        self.assertTrue(verdict["ok"])  # a warning, not a failure
        self.assertEqual(verdict["problems"][0]["severity"], "warning")

    def test_rounding_is_allowed(self):
        self.assertEqual(verify("Liver is about 77 [gtex_tissue_tpm].",
                                self.record)["problems"], [])

    def test_digits_inside_names_are_not_claims(self):
        verdict = verify("PCSK9 (Q8NBP7) sits at 1p32.3 [chromosomal_location].",
                         self.record)
        self.assertTrue(verdict["ok"], verdict["problems"])


class TestSession(unittest.TestCase):
    def test_with_no_model_it_falls_back_and_says_so(self):
        import os
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"SPICA_DATA_DIR": tmp}):
                agents = Agents(tools=stub_tools())
                self.assertEqual(agents.status()["model"], "")
                chosen, note = agents.backend()
        self.assertEqual(chosen.name, "scripted")
        self.assertIn("No model found", note)

    def test_a_run_carries_the_tools_it_may_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Run(QUESTION, "scripted", root=Path(tmp),
                      tools=[{"key": "documents", "label": "Your documents",
                              "usage": "documents(...)", "status": "ready"}])
            snapshot = run.snapshot()
        self.assertEqual(snapshot["tools"][0]["key"], "documents")

    def test_polling_an_unchanged_run_says_so_rather_than_resending_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Run(QUESTION, "scripted", root=Path(tmp))
            agents = Agents(tools=stub_tools())
            agents._runs[run.id] = run
            first = agents.poll(run.id)
            again = agents.poll(run.id, first["version"])
        self.assertTrue(again["unchanged"])

    def test_polling_a_run_that_does_not_exist_is_not_an_error(self):
        self.assertTrue(Agents(tools=stub_tools()).poll("nope")["missing"])


class TestState(unittest.TestCase):
    def test_a_checkpoint_is_a_copy_not_a_view(self):
        state = State(plan=["a"],
                      notes=[Note("documents", "Your documents", "t", "arg", ["c"])])
        copy = state.copy()
        copy.plan.append("b")
        copy.notes[0].fields.append("other")
        self.assertEqual(state.plan, ["a"])
        self.assertEqual(state.notes[0].fields, ["c"])

    def test_it_survives_a_round_trip_through_json(self):
        state = State(plan=["a"],
                      notes=[Note("documents", "Your documents", "t", "arg", ["c"])],
                      pending="record\x00PCSK9", closed=True, draft="d")
        back = State.from_dict(json.loads(json.dumps(state.to_dict())))
        self.assertEqual(back.notes[0].argument, "arg")
        self.assertEqual(back.pending, "record\x00PCSK9")
        self.assertTrue(back.closed)
        self.assertEqual(back.draft, "d")


if __name__ == "__main__":
    unittest.main()
