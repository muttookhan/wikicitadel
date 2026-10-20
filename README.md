# WikiCitadel

**The LLM Wiki that proves what it says.**

WikiCitadel is a complete, working implementation of the LLM Wiki pattern:
an agent maintains a personal wiki — raw sources preserved untouched, a
compiled layer of interlinked pages, and a schema file that teaches the
agent how the wiki is run — except that here, **every claim carries a
verifiable citation, dead claims are severed so they cannot leak back
into answers, and the system will say "not recorded" instead of
inventing.** Most LLM wikis compile knowledge. This one can be *checked*.

```
raw/        sources, preserved verbatim, never edited after ingest
wiki/       the compiled layer — pages, citations, the index, the log
AGENTS.md   the schema: the constitution the agent works under
scripts/    the engine: validation, citation lockfile, severance, lint
tools/      the Ask door, the governed gateway, the Lens portal, traversal
evaluation/ the registers: verification status, treatments, forecasts
```

## Two-minute demo

This repository *is* a running installation, seeded with a tiny fictional
corpus — a founding note, a decision that was reversed the day it was
made, a tombstone — so every mechanism below can be seen working on real
files in minutes, with no account and no API key:

1. Read `wiki/overview.md` and `wiki/syntheses/decision-register.md` —
   note the `^[cite: …]` marker after each claim, and that the
   superseded blanket decision is kept, labelled, and severed rather
   than quietly rewritten.
2. Run the citation lockfile check:
   `python3 scripts/wiki_cite_lock.py check` — every marker in the seed
   corpus resolves to the exact lines it cites.
3. Build the reading portal: `tools/lens/rebuild.sh`, then open the
   generated Lens — search the seed wiki, open the Briefing, and find
   the one idea waiting on an owner's ruling, with its Approve / Reject
   buttons.
4. Ask the corpus a question it cannot answer and watch it abstain
   rather than guess (the Ask door's contract, `tools/ask/`).

Then replace the seed corpus with your own sources and let your agent
work under `AGENTS.md`.

## What makes it different

- **Citation integrity, mechanically enforced.** Claims cite
  `file#La–Lb`; a lockfile hashes the cited lines; a nightly audit
  re-verifies them, and drift is a named finding, never a silent rot.
- **Severance.** When a claim is superseded or withdrawn, a register
  entry removes it from retrieval — including its paraphrases — while
  the record of what was believed, and why it died, stays inspectable.
  (Independent measurement of a popular memory system found corrected
  values resurrected in 46.7% of trials. Here, resurrection is a test
  failure.)
- **Abstention as a feature.** An explicit gate, tuned on a frozen
  battery, decides when the corpus does not know — and the door says so.
- **Governance with receipts.** Agent writes go through a governed
  gateway: scoped tokens, default-deny, a hash-chained audit ledger,
  staged proposals, and promotion that must pass an evaluation gate.
  The person who proposes is never the person who promotes.
- **A reading portal, not a file dump.** The Lens renders the wiki as a
  portal — briefing, passage-level search with corpus-vocabulary
  suggestions, an interactive graph, timelines, decision and health
  views — with an evidence matrix that shows, per page, *how* it is
  known: owner-attested, source-backed, or due for re-verification.
- **Honest labels.** A verification register states what has actually
  been verified, and no page, report or README in this project claims
  more than the register allows. `BENCHMARKS.md` follows the same rule.

The full inventory is in [CAPABILITIES.md](CAPABILITIES.md) — twelve
sections, including an explicit list of what is **not** in this edition.

## Install

WikiCitadel is files and Python — no service to run, no database, no
account:

```sh
git clone https://github.com/muttookhan/wikicitadel
cd wikicitadel
python3 -m unittest discover -s scripts/tests   # engine test suite
python3 scripts/wiki_validate.py                # validate the seed corpus
```

Point your agent (Claude Code, Codex, or any harness that reads
`AGENTS.md`) at the repository and let it read the schema first. To
start your own wiki, empty `wiki/` and `raw/`, keep `AGENTS.md`, and
ingest your first source.

## Heritage and licences of ideas

WikiCitadel implements Andrej Karpathy's LLM Wiki pattern and stands on
a surveyed field of roughly 3,300 projects (the survey is part of this
project's record). Where a mechanism was adapted from an MIT- or
Apache-2.0-licensed project, the schema credits it by name; mechanisms
from copyleft or source-available projects were re-implemented from
their published ideas only. Third-party code and fonts keep their own
licences where they appear.

## Licence

MIT — see [LICENSE](LICENSE). The schema, the engine, the tools and the
seed corpus are all under the same licence: take it, run your own
citadel.
