#!/usr/bin/env python3
"""Answer provenance pack for the Ask door (W3, 2026-10-22).

Every Ask answer can carry ONE provenance envelope — a
structured record, stamped on the Q&A record at answer time,
that lets a reader (or an audit) walk from any sentence of the
answer back to the evidence it rests on WITHOUT re-running the
query:

- **per citation**: the source page, the exact passage, the
  cited document's identity (sha256 + byte size + DOI where the
  page's frontmatter carries one), and the retrieval/scoring
  PATH that produced it — the rank and score retrieval offered
  it at, the reranker's name/relevance/multiplier when the
  rerank stage touched it, the governance outcome (the page's
  state in the retrieval-governance artefact, W1.5 — a cited
  page survived; withheld pages are named in ``withheld``),
  and the packing decision (packed / dropped / severed, with
  standing and freshness where packing recorded them);
- **per sentence**: which citations the sentence rests on,
  with the W1.4 sentence scorer's verdict and the
  character-exact span (normalised-page coordinates) of the
  supporting region — computed at answer time over the
  record's own passages, by the scorer the house already has;
- **the policy snapshot**: the corpus state the answer was
  assembled against — git HEAD, the governance artefact's
  state hash and its register input hashes, and the frozen
  abstention threshold — so a later reader can tell whether
  the state an answer was computed against still stands;
- **absence, named**: on a zero-result answer, ``absent_terms``
  names which query terms appear in NO document (from the
  retrieval diagnostics captured at answer time), and an
  abstention's envelope shows WHY — the recorded reason, the
  top score against the threshold, severance and withholding
  counts. Nothing about the abstention path is softened;
- **source type, labelled**: every envelope states what the
  answer rests on — ``local-corpus`` (cited wiki pages),
  ``abstention`` (the door refused; no fallback was taken), or
  ``model-knowledge-fallback`` when the caller's diagnostics
  declare one (with the local recall that fell short). The
  standing door never falls back — the abstention contract
  forbids an uncited answer — but the label exists and fires
  whenever the recorded state says a fallback happened;
- **a verify block**: explicit, runnable instructions for
  checking the answer (recompute the document hashes, run the
  citation lockfile check, re-run retrieval against the named
  policy snapshot) instead of asking the caller to trust it.

ANSWER-TIME RULE (the pack's founding discipline): provenance
is recorded from the pipeline's own state at answer time —
the finished record, the ``pack_evidence`` result the answer
was composed from, and the retrieval diagnostics the search
stages produced (see ``RETRIEVAL SHAPE`` below). It is NEVER
reconstructed afterwards by re-searching: a reconstruction can
disagree with what the answer actually used. Where a datum was
not captured, the envelope leaves the field absent rather than
inventing it; the only computations performed at build time
are deterministic readings of the answer's own artefacts —
the sentence scorer over the record's passages (W1.4) and the
sha256 of the exact files the citations resolve to, which pin
WHICH VERSION of each document the answer rests on.

RETRIEVAL SHAPE — the diagnostics a caller supplies (all
optional; each feeds the matching envelope block):

- ``terms``: ``[{"term": str, "documents": int}]`` — per-term
  document counts from the retrieval index (``hits`` accepted
  for ``documents``);
- ``candidates``: ``[{"page", "rank", "score", "detail"}]``
  in offered order — ``detail`` may carry the search result's
  own fields (``reranker``, ``rerank_relevance``, ``rerank``);
- ``governance``: ``[{"page", "state", "outcome", "reasons"}]``
  — per-page governance decisions (``outcome`` is
  ``"survived"`` / ``"withheld"``);
- ``zero_result``: retrieval offered nothing;
- ``top_score``: the best score retrieval produced;
- ``reranker``: the reranker the seam ran;
- ``fallback``: ``{"kind": "model-knowledge", "local_recall",
  "threshold"}`` when the answer was composed from model
  knowledge after local recall fell below threshold;
- ``absence_certificate``: a W1.5 absence certificate,
  carried verbatim.

Placement (the recorded seam decision, mirroring coverage.py
and trace.py): the envelope is NOT folded into the answer
text and changes no contract field. ``pickup.py`` stamps a
supplied envelope onto the record as an additive ``provenance``
field and renders a ``## Provenance`` section in the staged
proposal; a payload carrying ``provenance_inputs`` (the
answer-time ``pack_result`` + ``retrieval`` diagnostics) or
``emit_provenance: true`` gets its envelope built from the
finished record at record time. Records without the field are
byte-identical to before.

Licence posture: clean re-implementation. The envelope idea —
document hash + verify block + context receipts (the build
list's rows: @333eco/corpus, smaramwbc/statewave,
ABRAXAS/VESTI) — is restated in this wiki's own code and
vocabulary against this pipeline's own state; no code or text
from those projects is held here.

Pure stdlib; importable without network access.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import answer_contract  # noqa: E402
import depth_ladder  # noqa: E402
import sentence_scoring  # noqa: E402

GOVERNANCE_REL = "evaluation/retrieval-governance.json"
BASELINE_REL = "evaluation/extended-baseline.json"


# ---------------------------------------------------------------------------
# Document identity (the exact files the citations resolve to)
# ---------------------------------------------------------------------------

def _frontmatter_value(text, field):
    """The scalar value of *field* in the YAML frontmatter of
    *text*, or None. A deliberately small reader: the first
    ``---`` block only, plain ``field: value`` lines — enough
    for an identifier like a DOI, never a general YAML parse."""
    lines = str(text or "").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith(field + ":"):
            value = line.split(":", 1)[1].strip().strip("\"'")
            return value or None
    return None


def document_identity(page, wiki_dir, cache):
    """The identity block for the document *page* names: its
    repo-relative path (``wiki/...``), sha256 and byte size of
    the file AS IT STANDS at answer time, and its DOI where the
    frontmatter carries one. None when *wiki_dir* is not
    supplied or the citation does not resolve — the envelope
    never invents an identity for a document it cannot read."""
    if wiki_dir is None:
        return None
    if page in cache:
        return cache[page]
    identity = None
    path = answer_contract.citation_path(page, wiki_dir)
    if path is not None and path.is_file():
        data = path.read_bytes()
        text = data.decode("utf-8", errors="replace")
        identity = {
            "path": "wiki/" + path.relative_to(
                Path(wiki_dir)).as_posix(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "doi": _frontmatter_value(text, "doi"),
        }
    cache[page] = identity
    return identity


# ---------------------------------------------------------------------------
# Policy snapshot (the corpus state the answer was made against)
# ---------------------------------------------------------------------------

def _git_head(root):
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10)
        head = out.stdout.strip()
        return head if out.returncode == 0 and head else None
    except Exception:
        return None


def policy_snapshot(root, retrieval):
    """The policy snapshot block, or None when no *root* is
    available to read state from. Every piece is present only
    when it can be determined from the artefacts themselves;
    the pieces that could not be determined are NAMED in
    ``unavailable`` — an absent piece is stated, not implied."""
    if root is None:
        return None
    root = Path(root)
    snap, unavailable = {}, []

    head = _git_head(root)
    if head:
        snap["git_head"] = head
    else:
        unavailable.append("git_head")

    artefact = None
    gov_path = root / GOVERNANCE_REL
    if gov_path.is_file():
        try:
            artefact = json.loads(
                gov_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            artefact = None
    if isinstance(artefact, dict) \
            and artefact.get("kind") == "retrieval-governance":
        snap["governance_state_hash"] = artefact.get("state_hash")
        generated = artefact.get("generated_from") or {}
        if isinstance(generated.get("inputs"), dict):
            snap["governance_inputs"] = generated["inputs"]
    else:
        unavailable.append("governance_state_hash")

    tau = None
    base_path = root / BASELINE_REL
    if base_path.is_file():
        try:
            tau = json.loads(base_path.read_text(
                encoding="utf-8")).get("abstain_threshold")
        except (OSError, ValueError):
            tau = None
    if isinstance(tau, (int, float)) and not isinstance(tau, bool):
        snap["abstain_threshold"] = tau
    else:
        unavailable.append("abstain_threshold")

    reranker = (retrieval or {}).get("reranker")
    if reranker:
        snap["reranker"] = reranker
    if unavailable:
        snap["unavailable"] = unavailable
    return snap, artefact


def governance_state_for(page, artefact, wiki_dir):
    """The governance-artefact state of *page* (W1.5), or None:
    ``{state, reasons}`` read from the artefact's own page map
    (keys are ``wiki/...`` paths) — recorded state, looked up
    at answer time, never recomputed here."""
    if not isinstance(artefact, dict) or wiki_dir is None:
        return None
    path = answer_contract.citation_path(page, wiki_dir)
    if path is None:
        return None
    rel = "wiki/" + path.relative_to(Path(wiki_dir)).as_posix()
    entry = (artefact.get("pages") or {}).get(rel)
    if not isinstance(entry, dict):
        return None
    return {"state": entry.get("state"),
            "reasons": entry.get("reasons") or []}


# ---------------------------------------------------------------------------
# Retrieval diagnostics (answer-time state, normalised)
# ---------------------------------------------------------------------------

def _term_documents(retrieval):
    """``[(term, documents)]`` from the diagnostics, in the
    caller's order; a term whose count is not a number is
    skipped — an unknown count is not a zero."""
    out = []
    for entry in (retrieval or {}).get("terms") or []:
        if not isinstance(entry, dict):
            continue
        term = entry.get("term")
        count = entry.get("documents", entry.get("hits"))
        if term and isinstance(count, (int, float)) \
                and not isinstance(count, bool):
            out.append((str(term), int(count)))
    return out


def _candidates_by_page(retrieval):
    out = {}
    for cand in (retrieval or {}).get("candidates") or []:
        if isinstance(cand, dict) and cand.get("page"):
            out.setdefault(str(cand["page"]), cand)
    return out


def _governance_by_page(retrieval):
    out = {}
    for entry in (retrieval or {}).get("governance") or []:
        if isinstance(entry, dict) and entry.get("page"):
            out.setdefault(str(entry["page"]), entry)
    return out


def _packing_by_page(pack_result):
    """``{page: decision-entry}`` over a pack_evidence result:
    packed first, then dropped, then severed (a page appears
    once; the earliest list is its fate)."""
    out = {}
    if not isinstance(pack_result, dict):
        return out
    for decision in ("packed", "dropped", "severed"):
        for entry in pack_result.get(decision) or []:
            if isinstance(entry, dict) and entry.get("page"):
                page = str(entry["page"])
                if page not in out:
                    block = {"decision": decision,
                             "score": entry.get("score"),
                             "tokens": entry.get("tokens")}
                    if entry.get("reason"):
                        block["reason"] = entry["reason"]
                    if isinstance(entry.get("standing"), dict):
                        block["standing"] = entry["standing"]
                    if isinstance(entry.get("freshness"), dict) \
                            and entry["freshness"].get("line"):
                        block["freshness"] = \
                            entry["freshness"]["line"]
                    out[page] = block
    return out


# ---------------------------------------------------------------------------
# Sentence linkage (W1.4's scorer, over the record's own passages)
# ---------------------------------------------------------------------------

def _sentence_links(record, wiki_dir):
    """Score the answer's sentences (top-level, then each
    sub-answer's) against the passages its own record carries.

    Returns ``(links, spans)``: ``links`` maps a passage key to
    the sentence records resting on it; ``spans`` maps
    ``(unit, sentence_index, key)`` to the character-exact span
    in normalised-page coordinates, computed only where the
    passage locates in its page (``wiki_dir`` required).
    Everything runs on answer-time artefacts — the record and
    the files its citations name — with the scorer the house
    already has; no query is re-run.
    """
    units = [("answer", record)]
    for sub in record.get("sub_answers") or []:
        if isinstance(sub, dict):
            units.append(("sub-answer", sub))
    links, spans = {}, {}
    page_cache = {}
    for unit_name, unit in units:
        entries = sentence_scoring.evidence_entries(unit)
        if not entries:
            continue
        by_key = {e["key"]: e for e in entries}
        for index, sentence in enumerate(
                sentence_scoring.split_sentences(
                    unit.get("answer") or "")):
            result = sentence_scoring.score_sentence(
                sentence, entries)
            for entry in result["selected"]:
                key = entry["key"]
                link = {"unit": unit_name, "index": index,
                        "sentence": sentence,
                        "verdict": result["verdict"],
                        "coverage": result["coverage"]}
                links.setdefault(key, []).append(link)
                if wiki_dir is not None \
                        and entry.get("passage") is not None:
                    text = sentence_scoring._page_text(
                        entry["page"], wiki_dir, page_cache)
                    if text is not None:
                        loc = sentence_scoring.locate_in_page(
                            text, entry["passage"])
                        sup = sentence_scoring.support_span(
                            sentence, entry["passage"])
                        if loc is not None and sup is not None:
                            spans[(unit_name, index, key)] = {
                                "page": entry["page"],
                                "start": loc[0] + sup[0],
                                "end": loc[0] + sup[1]}
    for key, key_links in links.items():
        for link in key_links:
            span = spans.get((link["unit"], link["index"], key))
            if span is not None:
                link["span"] = span
    return links


# ---------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------

def _source_type(record, retrieval):
    """The explicit source-type label: what this answer rests
    on, stated on the envelope's face."""
    fallback = (retrieval or {}).get("fallback")
    if isinstance(fallback, dict) \
            and fallback.get("kind") == "model-knowledge":
        return {
            "kind": "model-knowledge-fallback",
            "label": (
                "MODEL KNOWLEDGE — this answer does NOT rest on "
                "the local corpus: local recall fell below "
                "threshold and the answer was composed from "
                "model knowledge. Treat every statement as "
                "uncited."),
            "local_recall": fallback.get("local_recall"),
            "recall_threshold": fallback.get("threshold"),
        }
    if record.get("abstained"):
        return {
            "kind": "abstention",
            "label": (
                "ABSTENTION — no source: the wiki held no "
                "sufficient evidence and the door refused "
                "rather than falling back to model knowledge."),
        }
    cited = len(record.get("citations") or [])
    return {
        "kind": "local-corpus",
        "label": (
            "LOCAL CORPUS — this answer rests on %d cited wiki "
            "page(s), pinned by hash below." % cited),
    }


def _verify_block(record, citations_block, root):
    """Explicit verify instructions: runnable checks, built
    from what the envelope actually pins."""
    checks = []
    docs = [c for c in citations_block if c.get("document")]
    if docs:
        checks.append({
            "what": "each cited document is the version the "
                    "answer rests on",
            "command": "sha256sum " + " ".join(
                c["document"]["path"] for c in docs),
            "expect": "each hash equals the sha256 recorded "
                      "in this envelope",
        })
    checks.append({
        "what": "the corpus's citations still verify",
        "command": "python3 scripts/wiki_cite_lock.py check",
        "expect": "the citation lockfile reports the cited "
                  "passages unchanged",
    })
    checks.append({
        "what": "this record passes the abstention contract",
        "command": "python3 tools/ask/pickup.py validate",
        "expect": "the record holding this envelope reports ok",
    })
    question = str(record.get("question") or "")
    if question:
        checks.append({
            "what": "retrieval against the CURRENT corpus "
                    "(the answer was computed against the "
                    "policy snapshot above; a moved corpus can "
                    "answer differently)",
            "command": "python3 scripts/wiki_search.py %s"
                       % json.dumps(question),
            "expect": "compare with the envelope's retrieval "
                      "path before treating any difference as "
                      "an error in the answer",
        })
    return {
        "instructions": [
            "Do not trust this envelope — check it: every "
            "claim below names the artefact that settles it.",
            "A citation's sha256 pins the document version the "
            "answer rests on; if the file has moved since, the "
            "hash says so before the prose can mislead.",
        ],
        "checks": checks,
    }


def build_provenance(record, pack_result=None, retrieval=None,
                     wiki_dir=None, root=None) -> dict:
    """Build the provenance envelope for one answer *record*.

    *pack_result* is the ``evidence_packing.pack_evidence``
    result the answer was composed from and *retrieval* the
    search stages' diagnostics (module docstring) — both are
    answer-time pipeline state supplied by the caller, never
    reconstructed here. *wiki_dir* (the ``wiki/`` directory)
    enables document identities and sentence spans; *root*
    (the repo root) enables the policy snapshot. Either may be
    omitted: the corresponding blocks are then absent or named
    unavailable, never faked.
    """
    record = record if isinstance(record, dict) else {}
    retrieval = retrieval if isinstance(retrieval, dict) else {}
    if wiki_dir is not None:
        wiki_dir = Path(wiki_dir)
    if root is None and wiki_dir is not None:
        root = wiki_dir.parent
    if root is not None:
        root = Path(root)

    snap_result = policy_snapshot(root, retrieval)
    snapshot, artefact = snap_result if snap_result else (None, None)

    candidates = _candidates_by_page(retrieval)
    gov_decisions = _governance_by_page(retrieval)
    packing = _packing_by_page(pack_result)
    term_docs = _term_documents(retrieval)
    absent_terms = [t for t, n in term_docs if n == 0]
    # -- depth (W6) ----------------------------------------
    # When the record carries a depth block (tools/ask/
    # depth_ladder.py) whose bundle says sentence scoring
    # is not run at that depth (quick), the scorer does not
    # run for this envelope: the per-citation sentence lists
    # stay empty, the support summaries are omitted rather
    # than computed as zeros, and the envelope's depth
    # summary below states why. Records without a depth
    # block are the default depth — scoring runs, exactly
    # as before this seam existed.
    depth_block = record.get("depth")
    scoring_not_run = (
        isinstance(depth_block, dict)
        and depth_block.get("sentence_scoring") == "not-run")
    if scoring_not_run:
        links = {}
    else:
        links = _sentence_links(record, wiki_dir)

    # -- per-citation blocks ----------------------------------
    entries = sentence_scoring.evidence_entries(record)
    doc_cache = {}
    citations_block = []
    cited_pages = set()
    for entry in entries:
        page = entry["page"]
        cited_pages.add(page)
        path = {}
        cand = candidates.get(page)
        if cand is not None:
            path["surfaced_by"] = ["retrieval"]
            if cand.get("rank") is not None:
                path["retrieval_rank"] = cand["rank"]
            if cand.get("score") is not None:
                path["retrieval_score"] = cand["score"]
            detail = cand.get("detail") or {}
            rerank = {}
            if detail.get("reranker"):
                rerank["reranker"] = detail["reranker"]
            if detail.get("rerank_relevance") is not None:
                rerank["relevance"] = detail["rerank_relevance"]
            if detail.get("rerank") is not None:
                rerank["multiplier"] = detail["rerank"]
            if rerank:
                path["rerank"] = rerank
                path["surfaced_by"].append("rerank")
        decision = gov_decisions.get(page)
        gov_block = None
        if decision is not None:
            gov_block = {
                "state": decision.get("state"),
                "outcome": decision.get("outcome") or "survived",
                "reasons": decision.get("reasons") or [],
                "source": "retrieval-diagnostics",
            }
        else:
            state = governance_state_for(page, artefact, wiki_dir)
            if state is not None:
                gov_block = {
                    "state": state["state"],
                    "outcome": "survived",
                    "reasons": state["reasons"],
                    "source": "retrieval-governance-artefact",
                }
        if gov_block is not None:
            path["governance"] = gov_block
            if "governance" not in path.get("surfaced_by", []):
                path.setdefault("surfaced_by", []).append(
                    "governance")
        if page in packing:
            path["packing"] = packing[page]
            path.setdefault("surfaced_by", []).append("packing")
        if entry.get("score") is not None:
            path["answer_score"] = entry["score"]
        key_links = links.get(entry["key"], [])
        citation_block = {
            "page": page,
            "key": entry["key"],
            "passage": entry.get("passage"),
            "anchor": entry.get("anchor"),
            "document": document_identity(page, wiki_dir,
                                          doc_cache),
            "path": path,
            "sentences": key_links,
        }
        if not scoring_not_run:
            citation_block["support_summary"] = {
                "sentences": len(key_links),
                "supported": sum(
                    1 for l in key_links
                    if l["verdict"] == "supported"),
                "partially_supported": sum(
                    1 for l in key_links
                    if l["verdict"] == "partially-supported"),
            }
        citations_block.append(citation_block)

    envelope = {
        "kind": "ask-provenance",
        "version": 1,
        "question_id": record.get("id"),
        "question": record.get("question"),
        "assembled_at": record.get("answered_at"),
        "mode": record.get("mode")
                or answer_contract.DEFAULT_ASK_MODE,
        "source_type": _source_type(record, retrieval),
        "citations": citations_block,
    }
    if snapshot is not None:
        envelope["policy_snapshot"] = snapshot

    # -- the road not taken ------------------------------------
    if isinstance(pack_result, dict):
        envelope["uncited_passages"] = [
            {"page": str(p.get("page")), "score": p.get("score"),
             "tokens": p.get("tokens")}
            for p in pack_result.get("packed") or []
            if isinstance(p, dict)
            and str(p.get("page")) not in cited_pages
        ]
        envelope["dropped"] = [
            {"page": str(p.get("page")), "score": p.get("score"),
             "tokens": p.get("tokens"),
             "reason": p.get("reason")}
            for p in pack_result.get("dropped") or []
            if isinstance(p, dict)
        ]
    withheld = []
    if isinstance(pack_result, dict):
        for p in pack_result.get("severed") or []:
            if isinstance(p, dict):
                withheld.append({
                    "page": str(p.get("page")),
                    "reason": "severed",
                    "severed_by": p.get("severed_by"),
                    "source": p.get("source"),
                    "score": p.get("score"),
                })
    for page, decision in gov_decisions.items():
        if decision.get("outcome") == "withheld":
            withheld.append({
                "page": page,
                "reason": "governance-withheld",
                "state": decision.get("state"),
                "reasons": decision.get("reasons") or [],
            })
    if withheld:
        envelope["withheld"] = withheld

    # -- absence + abstention ----------------------------------
    if term_docs:
        envelope["term_documents"] = [
            {"term": t, "documents": n} for t, n in term_docs]
    if absent_terms:
        envelope["absent_terms"] = absent_terms
    if retrieval.get("zero_result"):
        envelope["zero_result"] = True
    cert = retrieval.get("absence_certificate")
    if isinstance(cert, dict):
        envelope["absence_certificate"] = cert
    if record.get("abstained"):
        abstention = {
            "reason": record.get("abstention_reason"),
            "top_score": retrieval.get("top_score"),
            "withheld_count": len(withheld),
            "all_evidence_severed": bool(
                isinstance(pack_result, dict)
                and pack_result.get("all_evidence_severed")),
        }
        if snapshot is not None \
                and "abstain_threshold" in snapshot:
            abstention["tau"] = snapshot["abstain_threshold"]
        envelope["abstention"] = abstention

    # -- lessons on record (W5) ------------------------------
    # When the record carries a lessons block (tools/ask/
    # lessons.py — matched from the finished record against
    # the corrections ledger, after this answer was composed),
    # the envelope NAMES the matched lessons so an audit can
    # walk from the envelope to the block; the block itself,
    # with the rules quoted verbatim, rides the record.
    lessons = record.get("lessons")
    if isinstance(lessons, dict) and lessons.get("matched"):
        envelope["lessons"] = {
            "count": len(lessons["matched"]),
            "entries": [
                {"entry": m.get("entry"),
                 "rule": m.get("rule"),
                 "state": m.get("state")}
                for m in lessons["matched"]
                if isinstance(m, dict)
            ],
            "source": "the record's own lessons block "
                      "(tools/ask/lessons.py), matched from "
                      "the finished record — the envelope "
                      "names the lessons; it does not "
                      "re-derive them",
        }

    # -- depth (W6) ----------------------------------------
    # When the record carries a depth block (tools/ask/
    # depth_ladder.py — the declared quick / standard /
    # deep the answer was composed at), the envelope NAMES
    # it, so an audit reads the answer's depth — and what
    # it cost — from the envelope, and a quick answer's
    # missing sentence scoring is explained here rather
    # than mistaken for missing support.
    if isinstance(depth_block, dict) and depth_block.get("level"):
        envelope["depth"] = depth_ladder.envelope_summary(
            depth_block)

    envelope["verify"] = _verify_block(
        record, citations_block, root)
    return envelope
