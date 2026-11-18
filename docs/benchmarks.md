# Benchmarks — Severmark branch conformance results (WikiCitadel)

This page is the public claims page for the
[Severmark branch standard](severmark-standard.md): the conformance
batteries of the reference implementation (WikiCitadel), run
against the corpus that ships in this repository, with the exact
commands so anyone can reproduce them.

**Every number below was produced by running the named command in
this tree on 2026-10-28.** Where a battery cannot run against the
shipped seed corpus, this page says so, in so many words — a
standard whose claims page hides its gaps is not a standard.

The shipped corpus is a small fictional demo wiki, so these are
**conformance** results (the machinery keeps its promises), not
quality-at-scale results. The larger reference deployment's
measurements — a 15-question golden set, a 12-case abstention
battery, scale ceilings — are in the root
[`BENCHMARKS.md`](../BENCHMARKS.md), labelled as what they are:
another installation's numbers, published as method and baseline.

## Results at a glance (seed corpus, 2026-10-28)

| Battery | Command | Result |
|---|---|---|
| Forgetting / severance | `python3 scripts/wiki_forgetting_check.py` | **2 severance entries, 11 checks, 0 failures** |
| Memory operations (FEB-30 slice) | `python3 scripts/wiki_memory_ops_check.py` | **22 scored steps, accuracy 0.9091** — create 6/6 · reinforce 8/8 · update 3/4 · supersede 3/4; probes 2/2; live probes 3/3; 2 disagreements (findings, see below) |
| Memory receipts | `python3 scripts/wiki_cite_lock.py check` | **PASS — 12 locked citations, OK 12 · MOVED 0 · CHANGED 0 · MISSING 0** |
| Abstention | `python3 scripts/wiki_abstention_check.py` | **Cannot run on the seed corpus** — see below |
| Conflict (Identify / Solve / Escalate) | `python3 scripts/wiki_conflict_score.py --answers <file>` | **Cannot run on the seed corpus** — see below |
| Instrument tests (all of the above, on fixtures) | see below | **63 tests, OK** |
| Gateway (gated writes + trust ledger) | `cd tools/gateway && python3 -m unittest discover -s tests` | **91 tests, OK** |

## Forgetting battery — 11 checks, 0 failures

```console
$ python3 scripts/wiki_forgetting_check.py
forgetting battery: 2 severance entries, 11 checks, 0 failures
```

The seed corpus carries two severed claims (a blanket approval,
and its same-day reversal — the demo's founding decision pair).
For each severance entry the battery checks STORED (the page
still exists — forgetting here is deactivation, not a hole),
SEVERED (the entry carries usable retrieval cues) and PARAPHRASE
(a reworded probe still matches the severance rule, so the cut
survives rewording). For the battery's named control pages it
checks PRESERVATION — live, load-bearing pages exist and are
*not* severed, the over-deletion half of the test. 11 checks,
0 failures, exit code 0.

## Memory-operations slice — accuracy 0.9091, 2 findings

```console
$ python3 scripts/wiki_memory_ops_check.py
memory-ops slice: 6 trajectories, 22 scored steps, 20 agreements, accuracy 0.9091
  create: 6/6
  update: 3/4
  reinforce: 8/8
  supersede: 3/4
  probes: 2/2 passed
  live_probes: 3/3 passed
```

The FEB-30 test (Toma et al., arXiv:2610.22209): over
fact-evolution trajectories whose correct operation class —
create / update / reinforce / supersede — is known by
construction, does the store classify its own operations
correctly? Downstream QA cannot see this property; FEB-30's
tested system scored 20%. Here, synthetic trajectories are
replayed against a temporary store in the real formats, and
each step is classified by the machinery itself: claim-match
for free-text claims (noise floor 0.35), the severance
derivation observed across a ruling's recorded register
write for rulings. The expected label is read only by the
scorer. Probes pin the zombie behaviour (a re-presented
superseded form must be flagged, never resurrected); live
probes run read-only against the shipped corpus.

The two disagreements are findings, stated plainly: a
**value change arriving in free text** (a workday moved from
Saturday to Sunday in a restated sentence) is classified
REINFORCE — the text machinery has no value-comparison step,
so UPDATE exists in this store only as a maintainer's
register/page revision; and a **ruling never written to the
register** classifies as no operation at all — the store
cannot supersede what its registers never recorded. Exit
code 1, because the disagreements exist; the battery is not
weakened to make it green.

## Memory receipts — PASS, 0 problems

```console
$ python3 scripts/wiki_cite_lock.py check
Citation lock check — 12 locked citations, 1 registered sources (locked 2026-10-21)
  OK 12 · MOVED 0 · CHANGED 0 · MISSING 0 · AMBIGUOUS 0
Result: PASS (0 problem(s))
```

Every claim-level citation in the seed wiki is locked to a hash
of its claim text, per-line hashes of its cited source range, and
a content hash of the cited block; the check re-reads the sources
and re-verifies all of it. 12 of 12 receipts verify exactly.

## Abstention battery — cannot run on the seed corpus

```console
$ python3 scripts/wiki_abstention_check.py
FileNotFoundError: [Errno 2] No such file or directory:
'…/evaluation/abstention-battery.jsonl'
```

Stated plainly: **the runner ships, the battery data does not.**
The seed tree carries no `evaluation/abstention-battery.jsonl`,
so there is no abstention score for this corpus, and this page
claims none. The instrument itself is exercised on fixtures by
its test module (`scripts/tests/test_abstention_coverage.py`,
part of the 55 green instrument tests below). The reference
deployment runs its own 12-case battery at a frozen threshold —
its result is reported in the root `BENCHMARKS.md`, as that
installation's number, not this corpus's.

## Conflict slice — cannot run on the seed corpus

`scripts/wiki_conflict_score.py` scores stored answers against
`evaluation/conflict-questions.jsonl` on the three behaviours the
standard separates — **Identify** the conflict, **Solve** it by
following the governing record, **Escalate** what stays
unresolved. The seed tree ships neither the slice file nor a set
of stored answers to score, so **no I/S/E score exists for this
corpus and none is claimed**. The scorer is exercised on fixtures
by `scripts/tests/test_conflict_score.py` (in the 55 below). The
seed corpus does contain the raw material of a conflict — the
blanket direction and its reversal — which is exactly what the
forgetting battery above severs on; a shipped slice built on it
is future work, and will be reported here when it exists, with
its scores, whatever they are.

## Instrument tests — 63, OK

The batteries' own machinery is pinned by unit tests that run
anywhere, fixtures included:

```console
$ python3 -m unittest scripts.tests.test_wiki_forgetting_check \
    scripts.tests.test_conflict_score \
    scripts.tests.test_abstention_coverage \
    scripts.tests.test_wiki_cite_lock scripts.tests.test_wiki_severance \
    scripts.tests.test_wiki_search_severance scripts.tests.test_lens_severance \
    scripts.tests.test_wiki_memory_ops_check
Ran 63 tests — OK
```

The gateway that enforces approval-gated writes and keeps the
hash-chained trust ledger runs its own suite:

```console
$ cd tools/gateway && python3 -m unittest discover -s tests
Ran 91 tests — OK
```

## The rule this page follows

A result appears here only with the command that produced it and
the date it was run. A battery that cannot run is reported as
cannot run. Numbers from any other installation — including this
project's own reference deployment — are labelled with the
installation they belong to and never presented as this corpus's.
