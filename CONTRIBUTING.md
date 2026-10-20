# Contributing to WikiCitadel

WikiCitadel is a governed, citation-verified LLM wiki. Contributions are
welcome — and they follow the same discipline the system itself enforces:
evidence first, claims cited, nothing silently overwritten.

## Before you start

- Read `AGENTS.md` (the schema / operating rules) and `README.md`.
- Check the existing issues and the wiki's own `wiki/ideas.md` board —
  the idea may already be recorded there.

## Ground rules

1. **Raw is immutable.** Never edit or delete a file under `raw/`; add a
   new file instead.
2. **Claims carry citations.** A claim that rests on a passage carries
   the claim-level marker shown in `AGENTS.md`, and the marker must
   resolve — the validator checks every one.
3. **Contradictions are flagged in place**, never silently overwritten.
4. **Tests before claims.** Run the affected suite and report the exact
   counts in your pull request. A red suite blocks the change; never
   weaken a test to go green.
5. **Licence discipline.** Original work is MIT. Code adapted from an
   MIT/Apache-2.0 project keeps its attribution; GPL/AGPL/BUSL or
   unlicensed material is never copied — re-implement the idea in your
   own code and say so in the pull request.
6. **No personal data.** Fixtures and examples use fictional people and
   places only.

## Pull requests

- One change per pull request, with the motivation stated up front.
- If your change touches the answer contract, the pickup prompts,
  evidence packing, or model routing, the abstention battery and the
  conflict slice must be re-run and their results included — this is a
  hard gate, described in `AGENTS.md`.
- Run `python3 scripts/wiki_validate.py` and include its verdict.

## Reporting issues

Use the issue templates. For a retrieval or answer-quality report,
include the exact question, what the wiki returned, and what it should
have returned — an unanswerable question the system answered anyway is
as much a bug as a wrong answer.
