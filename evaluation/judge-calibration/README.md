# Judge calibration — seed installation

The Ask door's answers can be scored by a judge. Before any judge's
verdicts are trusted, the judge must be *certified* against labelled
examples — and certification here is designed to be refused:

- `judge-config.json` pins the judge (a deterministic rule-based stub;
  no LLM judge is wired in) and the bars: at least 100 labelled
  examples, at least 100 of them labelled by the owner personally,
  true-positive and true-negative rates of at least 0.8.
- `labeled-examples.jsonl` is the starter set: 120 examples derived
  from this seed corpus. None is owner-labelled, so the owner bar is
  unmet and **certification is refused** — that refusal, with its one
  named reason, is the correct current state, and the test suite
  asserts it.
- `stub_judge.py` implements the rubric in `judge-prompt.md` with the
  Ask door's own contract machinery. Its known limitation: it checks
  forbidden claims by normalised containment and cannot see refutation
  framing.

When the owner labels 100+ examples, the same runner re-scores; the
day an LLM judge is configured, it inherits the same bars.
