import { useEffect, useRef, useState } from "react";
import { Loader2, MessagesSquare } from "lucide-react";
import { askQuestion, saveThinking, thinkingChoice, type Run } from "../agents";
import { AgentRun } from "./AgentRun";

// AI mode. Agents answer an arbitrary question. They search the user's
// documents and call the deterministic tools. The report is different: no
// model builds it, and it never goes through this screen.

export function Ask() {
  const [text, setText] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [thinking, setThinking] = useState(true);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    input.current?.focus();
    thinkingChoice().then(setThinking).catch(() => undefined);
  }, []);

  const toggleThinking = () => {
    const next = !thinking;
    setThinking(next);
    saveThinking(next).catch(() => undefined);
  };

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const question = text.trim();
    if (!question) {
      setProblem("No question entered.");
      return;
    }
    setBusy(true);
    setProblem("");
    try {
      const result = await askQuestion(question, thinking);
      if (result.error) setProblem(result.error);
      else setRun(result);
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

  if (run) return <AgentRun run={run} onBack={() => setRun(null)} />;

  return (
    <div className="m-auto w-full max-w-[680px] px-8 py-16">
      <h1 className="text-[34px] font-bold leading-[1.15] tracking-[-0.02em] text-balance text-ink">
        Questions
      </h1>
      <p className="mt-3 max-w-[58ch] text-[15px] leading-relaxed text-slate">
        Answers from indexed documents and from the record tools. A model writes the answer; code checks
        each citation and each cited number.
      </p>

      <form onSubmit={submit} noValidate className="mt-8">
        <label htmlFor="ask-question" className="mb-1.5 block px-1 text-[12px] font-medium text-slate">
          Question
        </label>
        <div className="rounded-[18px] border border-line bg-surface p-2 transition-[border-color,box-shadow] focus-within:border-azure focus-within:shadow-[0_0_0_4px_rgb(0_178_255/0.18)]">
          <textarea
            ref={input}
            value={text}
            rows={3}
            onChange={(e) => {
              setText(e.target.value);
              if (problem) setProblem("");
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(e);
              }
            }}
            id="ask-question"
            spellCheck={false}
            aria-label="Question"
            className="w-full resize-none bg-transparent px-3 py-2 text-[15px] leading-relaxed text-ink outline-none placeholder:text-slate/70"
          />
          <div className="flex items-center justify-between px-1 pb-1">
            <div className="flex items-center gap-4 px-2">
              <button
                type="button"
                role="switch"
                aria-checked={thinking}
                onClick={toggleThinking}
                title={
                  thinking
                    ? "Reasoning before the first plan and the answer. Slower."
                    : "No reasoning step. Faster; weaker on questions with several steps."
                }
                className="flex items-center gap-2 text-[12px] text-slate hover:text-ink"
              >
                <span
                  aria-hidden="true"
                  className={`relative h-[18px] w-8 rounded-full border transition-colors ${
                    thinking ? "border-azure-deep bg-azure-deep" : "border-line bg-frost"
                  }`}
                >
                  <span
                    className={`absolute top-[2px] size-3 rounded-full transition-[left] ${
                      thinking ? "left-[16px] bg-on-accent" : "left-[2px] bg-slate"
                    }`}
                  />
                </span>
                Thinking {thinking ? "on" : "off"}
              </button>
              <span className="text-[12px] text-slate">Enter: ask. Shift+Enter: new line.</span>
            </div>
            <button
              type="submit"
              disabled={busy}
              className="flex h-10 items-center gap-2 rounded-full bg-azure-deep px-5 text-[14px] font-semibold text-on-accent transition-colors hover:bg-azure-hover disabled:opacity-70"
            >
              {busy ? (
                <Loader2 size={17} className="animate-spin" aria-hidden="true" />
              ) : (
                <MessagesSquare size={17} strokeWidth={2} aria-hidden="true" />
              )}
              Ask
            </button>
          </div>
        </div>
        {problem && (
          <p role="alert" className="mt-3 px-5 text-[13px] text-error">
            {problem}
          </p>
        )}
      </form>
    </div>
  );
}
