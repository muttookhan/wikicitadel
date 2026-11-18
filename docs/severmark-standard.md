# The Severmark Standard (v0.1) — a WikiCitadel branch

**Verifiable memory for AI agents** — a small, implementable pattern
for memory a reader does not have to take on trust. An implementation
conforms when a third party, given only the store and its registers,
can check every claim this standard makes — without asking the
system, or its author, to vouch for it.

**WikiCitadel** is the product — the open-source wiki edition that
implements this pattern. **Severmark** is not a separate product:
it is the name of the branch inside WikiCitadel that carries this
standard and its conformance work (owner ruling, 2026-10-28). Every
mechanism below names the WikiCitadel machinery that implements it,
but the standard is stated so another system can implement it in
its own terms. Licence: MIT.

The pattern has five parts. Each is a *discipline with a checker*,
not a feature claim: a part you cannot run a check against is not
implemented, however good the prose around it sounds.

---

## 1. Memory receipts

A stored claim that rests on a source carries a **receipt**: a
record binding the claim to the exact bytes it rests on.

A receipt states:

- the claim (its text, and a hash of that text);
- where the claim lives (page/record id and line);
- the source (a path or identifier in the raw layer);
- the **range** — the exact lines of the source the claim rests on;
- a **per-line hash** of each cited line, and a content hash of the
  cited block as it stood when the claim was compiled.

The raw layer is immutable: sources are added, never rewritten.
A checker re-reads every receipt's source and reports, per receipt:

- **OK** — the cited lines hash exactly as locked;
- **MOVED** — the same lines (same per-line hash sequence) found at
  a different range; the new range is reported;
- **CHANGED** — the cited content differs and is not found elsewhere
  in the file; the claim needs human re-verification;
- **MISSING** — the source, or the cited lines, are gone.

A whole-file manifest (path, SHA-256, size for every cited source)
catches change *outside* the cited ranges. Direct quotations are
verified verbatim against their cited range (normalising only
whitespace and smart quotes), and divergences are reported with
their exact point.

*Reference implementation:* `scripts/wiki_cite_lock.py` over
`evaluation/citation-lockfile.json` + `evaluation/source-manifest.jsonl`;
the citation itself is written inline as
`^[cite: raw/<path>#L<start>-L<end>]`.

## 2. Severance

Forgetting is **deactivation, never silent erasure**. When a claim
is superseded, corrected away, or withdrawn, a register entry
severs it at retrieval time:

- the claim's page and history **stay** — what was believed, and
  why it died, remain inspectable;
- the severance entry carries **retrieval cues** (cue phrases and
  distinctive terms) derived from the registers that killed the
  claim — decisions, treatments, supersession signals — never
  hand-listed;
- retrieval and answer-packing consult the severance register on
  every query: a severed claim is excluded *by register lookup*,
  never merely out-ranked, and the exclusion survives paraphrase
  under the published match rule (a cue phrase as a contiguous
  token subsequence, OR at least half — and at least 3 — of the
  distinctive terms present).

The failure this part exists to prevent is resurrection: a
corrected value quietly re-entering answers. Under this standard,
resurrection is a test failure (§5), not an anecdote.

*Reference implementation:* `scripts/wiki_severance.py` →
`evaluation/retrieval-severance.json`, consulted by search and by
the Ask door's evidence packing.

## 3. Approval-gated writes, with a trust ledger

No agent writes to the compiled layer directly. Writes pass a
governed gateway:

- **Default-deny, scoped tokens.** Each admitted identity holds a
  token scoped to what it may do; anything not granted is refused.
- **Staged proposals.** A write is proposed into staging first,
  with its provenance (who, on what evidence, under which trust
  tier — owner > curated > project > agent > external >
  untrusted, propagating by weakest link).
- **Review separation.** The proposer is never the promoter.
  Promotion additionally requires a reviewer who is not the
  proposer, and must pass the evaluation gate (§5) where the
  change touches the answer contract.
- **Trust ledger.** Every admitted act — proposal, review,
  promotion, refusal — is appended to a **hash-chained audit
  ledger** (the Black Box): each entry binds to the previous
  entry's hash, so a rewritten history does not verify. The chain
  head is anchored outside the ledger (in git) so tampering is
  detectable, not merely impolite.

An installation that cannot show its ledger has no governed
writes, whatever its gateway is called.

*Reference implementation:* `tools/gateway` (MCP gateway + Black
Box ledger; `gateway verify` checks the chain).

## 4. Measured abstention

"the corpus does not know" is a first-class answer, and it is
**measured, not trusted**. The answer contract is pinned by a
frozen battery of cases, each stating its expected verdict as
data:

- no corpus evidence → **abstain**, with a reason;
- the only evidence is severed → **abstain** (severance);
- top-ranked evidence below the calibrated threshold τ →
  **abstain** (no usable evidence);
- nothing packed → **abstain** (empty pack);
- thin-but-real evidence → **answer**, with citations;
- a reasoning chain expressing uncertainty under a definitive
  answer forces the trust verdict to **hold**.

The battery runs deterministically against the live pipeline
(search + packing + contract — no live model), so what is pinned
is the contract layer, not a model's prose. The threshold is
frozen with the battery: it is never re-tuned in the same change
that fails it, and a case is never weakened to make a run green.

*Reference implementation:* `scripts/wiki_abstention_check.py`
over `evaluation/abstention-battery.jsonl`.

## 5. Conformance batteries

Conformance is four published batteries plus the receipt check.
An implementation claims Severmark conformance only with current,
reproducible results for each — and states plainly any battery it
cannot run.

1. **Receipt check** (§1): every locked citation re-verified;
   PASS = 0 problems (no CHANGED, no MISSING).
2. **Forgetting battery** (§2): cases derived from the
   implementation's own severance register, checking **STORED**
   (the severed page still exists), **SEVERED** (the entry carries
   usable cues), **PARAPHRASE** (a reworded probe still matches),
   and **PRESERVATION** (named live control pages exist and are
   NOT severed — the over-deletion half). PASS = 0 failures.
   (Pattern: the Bemula forgetting benchmark, Xie et al.,
   arXiv:2610.18052 — two-sided failure: the forgotten thing stays
   extractable, or more than was asked is deleted.)
3. **Abstention battery** (§4): every frozen case's verdict
   matches its stated expectation. PASS = all cases.
4. **Conflict slice**: stored answers scored on the corpus's real
   conflicts in three separate behaviours — **Identify** the
   conflict, **Solve** it by following the governing record,
   **Escalate** the residual uncertainty. An answer that detects
   a conflict mid-run but asserts over it in the final answer is
   the failure this slice exists to catch; for an unresolved
   conflict, identifying and escalating *is* the correct score.
5. **Memory-operations slice**: fact-evolution trajectories
   whose correct operation class (create / update / reinforce /
   supersede) is known by construction, replayed against the
   implementation's own store machinery and scored on
   classification agreement — the intrinsic property downstream
   QA cannot see. Unlike the batteries above this slice reports
   a **score with named disagreements**, not a zero-failure
   pass: an implementation states its accuracy per class and
   the steps it got wrong. (Pattern: FEB-30 in Toma et al.,
   "Beyond Downstream QA", arXiv:2610.22209, whose tested
   system classified 20% of operations correctly.)

Any change to the answer contract, evidence packing (including
its severance and standing inputs), or model routing re-runs the
batteries before integration. A red battery blocks the change.

*Reference implementation:* `scripts/wiki_forgetting_check.py`,
`scripts/wiki_abstention_check.py`, `scripts/wiki_conflict_score.py`,
`scripts/wiki_memory_ops_check.py`;
current reference results: [benchmarks.md](benchmarks.md).

---

## What conformance does not claim

- Nothing about answer *style*, model choice, or prose quality —
  the standard governs whether memory can be **checked**, not
  whether it reads well.
- Nothing about scale: an implementation states its own measured
  ceiling, dated and re-measurable, and claims nothing beyond it.
- No comparison scores against other systems. Conformance is a
  property of one's own store, proven on one's own registers.
