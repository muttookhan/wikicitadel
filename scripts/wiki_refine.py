#!/usr/bin/env python3
"""wiki_refine.py — query-log refinement loop (WikiCitadel v1).

Pattern: DeepRefine-Skill (MIT) refines a
wiki from its own query log — dry-run proposed edits, every proposal
evidence-labelled HIGH / MEDIUM / LOW, apply refuses LOW by default,
and accepted changes land as a staged, validated swap rather than a
silent rewrite. OUR adaptation keeps the same governance shape as
the rest of this repo (cf. scripts/wiki_evolve.py): this tool NEVER
edits a wiki page. The dry run emits proposals (a filing + a
machine-readable manifest); `apply` turns accepted proposals into
gateway staged proposals (staging/proposed/prop-*.md + .json) via
GatewayStore.stage_proposal, and a human reviewer decides, edits,
and promotes (or rejects) through the ordinary gateway path.

Inputs, stated plainly: the Lens keeps NO query log — its search is
client-side and records nothing. The only query log this wiki has is
the Ask door's recorded Q&A, wiki/access/qa-*.jsonl (plus the staged
qa-*.md pickup proposals, which duplicate it). Pickup run reports
are not persisted in the repo. So the loop reads the QA log, git
history (for "the cited page changed since the answer"), and a
retrieval replay of each logged question through
scripts/wiki_search.py's hybrid ranker (for "retrieved but never
cited").

Detectors (all deterministic):
  stale-citation        an answer cited a page that has since
                        changed — materially (>= MATERIAL_LINES
                        changed lines in git since the answer) or
                        modestly (any later commit / `updated`
                        advanced);
  gap-abstained         a question the Ask door abstained on — the
                        wiki demonstrably had no answer;
  gap-repeat            the same question (token Jaccard >= 0.6)
                        asked more than once — the settled answer
                        is not findable enough;
  thin-answer           an answer carrying trust verdict hold, an
                        abstained sub-answer, a single citation, or
                        a very short body;
  retrieved-never-cited a page the search ranks top-K for logged
                        questions but no recorded answer ever cited.

Labels: HIGH = direct deterministic evidence (material change,
an abstention on record, a repeat cluster containing an
abstention); MEDIUM = corroborated but weaker (modest change,
clean repeat cluster, thin answer, page retrieved for >= 2
distinct questions yet never cited); LOW = single-occurrence
signal (page retrieved once, never cited). `apply` refuses LOW
unless --include-low is passed, and records the refusal either way.

Coaching : a refusal is not the end of the
conversation. Every refused LOW proposal carries a
`coaching_note` (low_coaching_note) written from the loop's
actual scoring inputs — the signal it rested on, and the
concrete signal that would have raised its label — recorded
in the manifest, printed at apply time, and filed with the
refusal. The label rules above do not move; the note exists
so a contributor (agent or human) whose signal was refused
learns what corroboration looks like instead of routing
around the gate (the Halfaker warning, via the
survey: gates that only reject strangle their own pipeline).

    python3 scripts/wiki_refine.py            # dry run -> filing
    python3 scripts/wiki_refine.py apply      # stage non-LOW
    python3 scripts/wiki_refine.py apply --include-low
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "gateway"))

from gateway import profile as profile_mod  # noqa: E402

TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = set("""the a an and or of to in is are was were be been for on
with as by at from this that it its has have had not no do does did will
would can could should may might must shall than then so such into over
under more most other some any only also just very what did does do is
are was were about""".split())

MATERIAL_LINES = 20        # changed lines (added+deleted) = material
REPEAT_JACCARD = 0.6       # token-set similarity = same question
RETRIEVAL_TOPK = 5         # replay depth for retrieved-never-cited
THIN_ANSWER_CHARS = 300    # below this an answer counts as thin
MAX_UNCITED_PROPOSALS = 8  # filing stays readable at any log size

LABELS = ("HIGH", "MEDIUM", "LOW")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_qa_records(root: Path) -> list[dict]:
    """All Ask-door Q&A records (wiki/access/qa-*.jsonl), oldest first."""
    records = []
    access = root / "wiki" / "access"
    if not access.is_dir():
        return records
    for path in sorted(access.glob("qa-*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rec["_log_file"] = str(path.relative_to(root))
            records.append(rec)
    records.sort(key=lambda r: str(r.get("asked_at") or ""))
    return records


def iter_pages(root: Path) -> dict[str, dict]:
    """Wiki pages keyed by repo-relative path."""
    pages = {}
    wiki = root / "wiki"
    if not wiki.is_dir():
        return pages
    for p in sorted(wiki.rglob("*.md")):
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        rel = str(p.relative_to(root))
        pages[rel] = {
            "rel": rel,
            "stem": str(p.relative_to(wiki))[:-3],   # e.g. concepts/llm-wiki
            "name": p.stem,
            "text": text,
            "fields": profile_mod.frontmatter_of(text) or {},
        }
    return pages


def record_citations(rec: dict) -> list[str]:
    """Citation page refs of a record, incl. sub-answers.

    Citations are plain strings in older records and rich entries
    ({page, score, passage}) since WikiCitadel v1; both are accepted.
    """
    out = []

    def take(cites):
        for c in cites or []:
            if isinstance(c, dict):
                c = c.get("page")
            if c:
                out.append(str(c))

    take(rec.get("citations"))
    take(rec.get("citation_details"))
    for sub in rec.get("sub_answers") or []:
        take(sub.get("citations"))
        take(sub.get("citation_details"))
    return out


def resolve_citation(cite: str, pages: dict[str, dict]) -> str | None:
    """Resolve a citation ref to a wiki page path, or None."""
    cite = cite.strip()
    direct = f"wiki/{cite}.md" if not cite.endswith(".md") else f"wiki/{cite}"
    if direct in pages:
        return direct
    by_stem = [rel for rel, pg in pages.items() if pg["stem"] == cite]
    if len(by_stem) == 1:
        return by_stem[0]
    by_name = [rel for rel, pg in pages.items() if pg["name"] == cite]
    if len(by_name) == 1:
        return by_name[0]
    return None


# ---------------------------------------------------------------------------
# Git change evidence
# ---------------------------------------------------------------------------

def page_changes(root: Path, rel: str, since_iso: str,
                 runner=subprocess.run) -> dict | None:
    """Commits touching `rel` after `since_iso`, via git log --numstat.

    Returns {commits, added, deleted, lines, last} or None when git
    cannot answer (not a repo, git missing) — callers fall back to
    the page's frontmatter `updated`.
    """
    try:
        proc = runner(
            ["git", "-C", str(root), "log", f"--since={since_iso}",
             "--format=COMMIT%x09%aI", "--numstat", "--", rel],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    commits, added, deleted, last = 0, 0, 0, ""
    for line in proc.stdout.splitlines():
        if line.startswith("COMMIT\t"):
            commits += 1
            last = last or line.split("\t", 1)[1].strip()
        else:
            parts = line.split("\t")
            if len(parts) == 3:
                a, d = parts[0], parts[1]
                added += int(a) if a.isdigit() else 0
                deleted += int(d) if d.isdigit() else 0
    return {"commits": commits, "added": added, "deleted": deleted,
            "lines": added + deleted, "last": last}


# ---------------------------------------------------------------------------
# Question similarity
# ---------------------------------------------------------------------------

def content_tokens(text: str) -> set[str]:
    return {t for t in TOKEN_RE.findall(str(text).lower())
            if len(t) >= 3 and t not in STOPWORDS}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster_questions(records: list[dict]) -> list[list[int]]:
    """Group record indexes whose questions are near-duplicates."""
    parent = list(range(len(records)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    toks = [content_tokens(r.get("question") or "") for r in records]
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            if jaccard(toks[i], toks[j]) >= REPEAT_JACCARD:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(records)):
        groups.setdefault(find(i), []).append(i)
    return [g for g in groups.values() if len(g) > 1]


# ---------------------------------------------------------------------------
# Detectors — each returns proposal dicts
# ---------------------------------------------------------------------------

def _pid(kind: str, target: str, key: str) -> str:
    digest = hashlib.sha1(f"{kind}|{target}|{key}".encode()).hexdigest()[:8]
    return f"refine-{kind}-{digest}"


def _proposal(kind, label, target, section, sketch, evidence, new_page=False):
    return {
        "id": _pid(kind, target, json.dumps(evidence, sort_keys=True)),
        "kind": kind, "label": label, "target_path": target,
        "section": section, "sketch": sketch, "evidence": evidence,
        "new_page": new_page, "status": "proposed",
        "proposal_id": None, "apply_note": None,
        "coaching_note": None,
    }


def stale_label(changes: dict | None, updated_advanced: bool) -> str | None:
    """Label rule for a cited page that may have changed since an answer.

    HIGH: material git change (>= MATERIAL_LINES lines). MEDIUM: any
    later commit below the material line, or (git silent) the page's
    frontmatter `updated` moved past the answer date. None: no change.
    """
    if changes is not None:
        if changes["lines"] >= MATERIAL_LINES:
            return "HIGH"
        if changes["commits"] > 0:
            return "MEDIUM"
        return None
    return "MEDIUM" if updated_advanced else None


def detect_stale_citations(records, pages, changes_for) -> list[dict]:
    """(a) Answers whose cited pages have since changed.

    `changes_for(rel, since_iso)` -> page_changes dict or None.
    """
    out = []
    for rec in records:
        if rec.get("abstained"):
            continue
        answered = str(rec.get("answered_at") or rec.get("asked_at") or "")
        if not answered:
            continue
        seen = set()
        for cite in record_citations(rec):
            rel = resolve_citation(cite, pages)
            if rel is None or rel in seen:
                continue
            seen.add(rel)
            changes = changes_for(rel, answered)
            page = pages[rel]
            updated = str(page["fields"].get("updated") or "")
            updated_advanced = bool(updated) and updated > answered[:10]
            label = stale_label(changes, updated_advanced)
            if label is None:
                continue
            if changes is not None:
                ev_change = (f"{changes['commits']} commit(s), "
                             f"+{changes['added']}/-{changes['deleted']} "
                             f"lines, latest {changes['last'][:10]}")
            else:
                ev_change = f"frontmatter updated {updated} (git unavailable)"
            out.append(_proposal(
                "stale-citation", label, rel, "Refinement proposal",
                f"Re-check the Ask-door answer {rec.get('id')} "
                f"(\"{str(rec.get('question'))[:90]}\") against the "
                f"current text of this page: the answer was recorded "
                f"{answered[:10]} citing it, and the page has changed "
                f"since ({ev_change}). If any claim in the answer no "
                f"longer matches, record a corrected QA entry and note "
                f"the supersession; if it still matches, no edit is "
                f"needed — close the staged proposal by rejecting it "
                f"with that reason.",
                {"question_id": rec.get("id"),
                 "question": rec.get("question"),
                 "answered_at": answered,
                 "change": ev_change}))
    return out


def _slug(question: str) -> str:
    toks = [t for t in TOKEN_RE.findall(str(question).lower())
            if len(t) >= 3 and t not in STOPWORDS][:5]
    return "-".join(toks) or "unanswered-question"


def detect_gaps(records, pages, clusters) -> list[dict]:
    """(b) Repeated questions, abstentions, thin answers."""
    out = []
    clustered = {i for g in clusters for i in g}

    # Repeat clusters.
    for group in clusters:
        members = [records[i] for i in group]
        qids = [m.get("id") for m in members]
        any_abstained = any(m.get("abstained") for m in members)
        label = "HIGH" if any_abstained else "MEDIUM"
        cited_pages = []
        for m in members:
            for cite in record_citations(m):
                rel = resolve_citation(cite, pages)
                if rel and rel not in cited_pages:
                    cited_pages.append(rel)
        question = str(members[0].get("question") or "")
        if cited_pages:
            target, new_page = cited_pages[0], False
            sketch = (f"This question (or a near-duplicate) has been "
                      f"asked {len(members)} times ({', '.join(qids)}): "
                      f"\"{question[:90]}\". The settled answers live "
                      f"only in the QA log. Promote a standing answer: "
                      f"fold the settled answer into this page so the "
                      f"next asking finds it in search, and cross-link "
                      f"the other cited pages ({', '.join(cited_pages[1:]) or 'none'}).")
        else:
            target = f"wiki/queries/refine-{_slug(question)}.md"
            new_page = True
            sketch = (f"This question (or a near-duplicate) has been "
                      f"asked {len(members)} times ({', '.join(qids)}) "
                      f"and no answer ever cited a page: "
                      f"\"{question[:90]}\". Draft a standing answer "
                      f"page here from sources, or record why the wiki "
                      f"cannot answer it.")
        out.append(_proposal(
            "gap-repeat", label, target, "Refinement proposal", sketch,
            {"question_ids": qids, "asks": len(members),
             "any_abstained": any_abstained, "question": question},
            new_page=new_page))

    # Single abstentions and thin answers (not already in a cluster).
    for i, rec in enumerate(records):
        if i in clustered:
            continue
        qid = rec.get("id")
        question = str(rec.get("question") or "")
        if rec.get("abstained"):
            target = f"wiki/queries/refine-{_slug(question)}.md"
            out.append(_proposal(
                "gap-abstained", "HIGH", target, "Refinement proposal",
                f"The Ask door was asked \"{question[:90]}\" on "
                f"{str(rec.get('asked_at') or '')[:10]} and abstained "
                f"({rec.get('abstention_reason') or 'no reason recorded'}). "
                f"The wiki demonstrably had no answer. Decide at "
                f"review: answer it here from sources, or record why "
                f"it stays unanswered.",
                {"question_id": qid, "question": question,
                 "asked_at": rec.get("asked_at"),
                 "abstention_reason": rec.get("abstention_reason")},
                new_page=True))
            continue
        thin = thin_reasons(rec)
        if thin:
            cites = record_citations(rec)
            target = None
            for cite in cites:
                target = resolve_citation(cite, pages)
                if target:
                    break
            if target is None:
                target = f"wiki/queries/refine-{_slug(question)}.md"
                new_page = True
            else:
                new_page = False
            out.append(_proposal(
                "thin-answer", "MEDIUM", target, "Refinement proposal",
                f"The Ask-door answer {qid} (\"{question[:90]}\") is "
                f"thin: {'; '.join(thin)}. Deepen the record — add "
                f"the missing support on this page (or a corrected QA "
                f"entry) so the next answer stands on more than this.",
                {"question_id": qid, "question": question,
                 "thin_reasons": thin},
                new_page=new_page))
    return out


def thin_reasons(rec: dict) -> list[str]:
    """Deterministic thinness signals for one answered record."""
    reasons = []
    if rec.get("trust_verdict") in ("hold", "review"):
        reasons.append(f"trust verdict {rec.get('trust_verdict')}")
    if any((s.get("abstained")) for s in rec.get("sub_answers") or []):
        reasons.append("a sub-answer abstained")
    if len(record_citations(rec)) <= 1:
        reasons.append("a single citation")
    if len(str(rec.get("answer") or "")) < THIN_ANSWER_CHARS:
        reasons.append(f"answer under {THIN_ANSWER_CHARS} characters")
    # A one-citation, full-length, verdict-clean answer is not thin.
    if reasons == ["a single citation"] and \
            len(str(rec.get("answer") or "")) >= THIN_ANSWER_CHARS:
        return []
    return reasons


def detect_retrieved_never_cited(records, pages, ranker) -> list[dict]:
    """(c) Pages search ranks for logged questions but answers never cite.

    `ranker(question) -> [repo-relative page paths]` (top-K).
    Label rule: MEDIUM when retrieved for >= 2 distinct questions,
    LOW for a single retrieval.
    """
    cited_anywhere: set[str] = set()
    for rec in records:
        for cite in record_citations(rec):
            rel = resolve_citation(cite, pages)
            if rel:
                cited_anywhere.add(rel)
    hits: dict[str, dict] = {}
    for rec in records:
        question = str(rec.get("question") or "")
        if not question:
            continue
        for rel in ranker(question)[:RETRIEVAL_TOPK]:
            if rel not in pages or rel in cited_anywhere:
                continue
            entry = hits.setdefault(rel, {"questions": [], "qids": []})
            if rec.get("id") not in entry["qids"]:
                entry["questions"].append(question)
                entry["qids"].append(rec.get("id"))
    out = []
    for rel, entry in sorted(hits.items(),
                             key=lambda kv: (-len(kv[1]["qids"]), kv[0])):
        n = len(entry["qids"])
        label = "MEDIUM" if n >= 2 else "LOW"
        out.append(_proposal(
            "retrieved-never-cited", label, rel, "Refinement proposal",
            f"Search ranks this page in the top {RETRIEVAL_TOPK} for "
            f"{n} logged question(s) ({', '.join(entry['qids'])}), "
            f"but no recorded answer has ever cited it. Check for "
            f"mis-filing or a missing link: if it belongs in those "
            f"answers' neighbourhood, link it from the pages they did "
            f"cite; if its ranking is a false friend, note why here "
            f"so the next run can stop proposing it.",
            {"question_ids": entry["qids"],
             "questions": entry["questions"], "retrieved_for": n}))
        if len(out) >= MAX_UNCITED_PROPOSALS:
            break
    return out


# ---------------------------------------------------------------------------
# Retrieval replay (production ranker over scripts/wiki_search.py)
# ---------------------------------------------------------------------------

def make_ranker(root: Path):
    spec = importlib.util.spec_from_file_location(
        "wiki_search", Path(__file__).resolve().parent / "wiki_search.py")
    ws = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ws)
    wiki = root / "wiki"
    docs = [(p, p.read_text(encoding="utf-8", errors="ignore"))
            for p in sorted(wiki.rglob("*.md")) if p.is_file()]
    adj = ws.build_link_graph(docs)

    def rank(question: str) -> list[str]:
        ranked = ws.hybrid_rank(ws.tokenize(question), docs, adj)
        return [str(p.relative_to(root)) for _s, p, _t, _d in ranked]

    return rank


# ---------------------------------------------------------------------------
# Filing + manifest
# ---------------------------------------------------------------------------

INPUTS_NOTE = (
    "Inputs: the Ask door's recorded Q&A (`wiki/access/qa-*.jsonl`) "
    "is the only query log this wiki keeps — the Lens search is "
    "client-side and records nothing, and pickup run reports are "
    "not persisted in the repo. Change evidence is git history "
    "since each answer; retrieval evidence is a replay of each "
    "logged question through `scripts/wiki_search.py` (hybrid rank, "
    f"top {RETRIEVAL_TOPK}).")


def analyse(root: Path, today: date | None = None, ranker=None) -> dict:
    today = today or date.today()
    records = load_qa_records(root)
    pages = iter_pages(root)

    def changes_for(rel, since):
        return page_changes(root, rel, since)

    proposals = []
    proposals += detect_stale_citations(records, pages, changes_for)
    clusters = cluster_questions(records)
    proposals += detect_gaps(records, pages, clusters)
    if ranker is None:
        ranker = make_ranker(root)
    proposals += detect_retrieved_never_cited(records, pages, ranker)

    by_label = {lb: sum(1 for p in proposals if p["label"] == lb)
                for lb in LABELS}
    manifest = {
        "tool": "scripts/wiki_refine.py",
        "pattern": "DeepRefine-Skill (MIT) — dry-run, evidence-labelled "
                   "proposals; apply refuses LOW by default",
        "generated_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "date": today.isoformat(),
        "inputs": INPUTS_NOTE,
        "stats": {
            "qa_records": len(records),
            "repeat_clusters": len(clusters),
            "pages_scanned": len(pages),
            "proposals": len(proposals),
            "by_label": by_label,
            "by_kind": {k: sum(1 for p in proposals if p["kind"] == k)
                        for k in sorted({p["kind"] for p in proposals})},
        },
        "proposals": proposals,
        "apply_runs": [],
    }
    return manifest


def render_filing(manifest: dict) -> str:
    d = manifest["date"]
    st = manifest["stats"]
    lines = [
        "---",
        f"title: Query-log refinement — {d} (dry-run proposals)",
        "type: query",
        f"created: {d}",
        f"updated: {d}",
        "sources:",
        "  - docs/research-notes.md",
        "tags: [refine, query-log, proposal, filings]",
        "status: draft",
        "confidence: observed",
        "---",
        "",
        f"# Query-log refinement — {d}",
        "",
        "> [!warning] DRY RUN — proposals only, nothing applied",
        "> Generated by the query-log refinement loop "
        "(`scripts/wiki_refine.py`, WikiCitadel v1; pattern: "
        "DeepRefine-Skill, MIT). Every item below is a PROPOSAL with "
        "an evidence label (HIGH / MEDIUM / LOW). **No page has been "
        "changed.** `apply` stages non-LOW proposals at the gateway "
        "(LOW is refused by default and the refusal recorded); a "
        "reviewer decides each staged proposal from there.",
        "",
        manifest["inputs"],
        "",
        f"Scale this run: {st['qa_records']} QA record(s), "
        f"{st['repeat_clusters']} repeat cluster(s), "
        f"{st['pages_scanned']} pages scanned → "
        f"{st['proposals']} proposal(s) "
        f"(HIGH {st['by_label']['HIGH']} · "
        f"MEDIUM {st['by_label']['MEDIUM']} · "
        f"LOW {st['by_label']['LOW']}).",
        "",
    ]
    if not manifest["proposals"]:
        lines += ["No proposals this run — the detectors found "
                  "nothing the log can support.", ""]
    for p in manifest["proposals"]:
        lines += [
            f"## [{p['label']}] {p['kind']} → {p['target_path']}",
            "",
            p["sketch"],
            "",
            f"Evidence: `{json.dumps(p['evidence'], sort_keys=True)}`",
            "",
        ]
    return "\n".join(lines)


def filing_paths(root: Path, d: str) -> tuple[Path, Path]:
    base = root / "wiki" / "filings" / f"refine-{d}"
    return base.with_suffix(".md"), base.with_suffix(".json")


def write_dry_run(root: Path, manifest: dict) -> tuple[Path, Path]:
    md_path, json_path = filing_paths(root, manifest["date"])
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_filing(manifest), encoding="utf-8")
    json_path.write_text(json.dumps(manifest, indent=2, sort_keys=True)
                         + "\n", encoding="utf-8")
    return md_path, json_path


def low_coaching_note(proposal: dict) -> str:
    """The coaching half of a LOW refusal, written from the
    proposal's own scoring inputs — never boilerplate: it
    names the single-occurrence signal the proposal rested
    on and the concrete signal that would have raised the
    label (the loop's label rules, applied to its evidence).

    The only LOW the detectors produce today is
    retrieved-never-cited with retrieved_for == 1 (a second
    distinct question would have made it MEDIUM). Any other
    LOW kind falls back to the general rule stated from the
    same inputs: LOW is the single-occurrence label."""
    kind = proposal.get("kind")
    ev = proposal.get("evidence") or {}
    target = proposal.get("target_path")
    if kind == "retrieved-never-cited":
        n = ev.get("retrieved_for", 1)
        qids = ", ".join(ev.get("question_ids") or []) or "—"
        return (
            f"Coaching: refused on a single-occurrence signal "
            f"— search ranked {target} in the top "
            f"{RETRIEVAL_TOPK} for {n} logged question(s) "
            f"({qids}) and no recorded answer has ever cited "
            f"it. The signal that would have raised this to "
            f"MEDIUM (and staged it): the same page ranking in "
            f"the top {RETRIEVAL_TOPK} for a SECOND distinct "
            f"logged question while still never cited — one "
            f"more independent asking surfacing the page. A "
            f"single retrieval is as likely a ranking false "
            f"friend as a real gap, so the loop asks for "
            f"corroboration before spending a reviewer's "
            f"time. Short of that signal, stage it "
            f"deliberately with `apply --include-low` — the "
            f"refusal and the flag are recorded either way.")
    return (
        f"Coaching: refused on a single-occurrence signal "
        f"(kind {kind}, evidence "
        f"{json.dumps(ev, sort_keys=True)}). LOW is this "
        f"loop's single-occurrence label; the signal that "
        f"would have raised it is a second, independent "
        f"occurrence of the same evidence — corroboration, "
        f"not volume. Short of that, stage it deliberately "
        f"with `apply --include-low` — the refusal and the "
        f"flag are recorded either way.")


# ---------------------------------------------------------------------------
# Apply — stage accepted proposals at the gateway; LOW refused by default
# ---------------------------------------------------------------------------

def premortem_placeholder() -> list[str]:
    """The premortem placeholder appended to every staged
    proposal . The premortem itself is written in a
    SEPARATE pass, by hand, before the proposal is put to
    the owner — a generator that filled it in mechanically
    would defeat the exercise, whose value is reasons the
    drafting pass did not produce. Until that pass runs,
    the block stands as an explicit NOT YET WRITTEN marker,
    and scripts/wiki_decision_gate.py names every staged
    proposal still carrying only the placeholder."""
    return [
        "---",
        "",
        "## Premortem (not yet written)",
        "",
        "**NOT YET WRITTEN.** Before this proposal is put to "
        "the owner, a separate pass replaces this placeholder "
        "with a written premortem (format: "
        "`templates/proposal.md`): the heading becomes "
        "`## Premortem (YYYY-MM-DD)`, the premise is stated — "
        "\"It is <date, ~6 months on> and this failed. The "
        "reasons were:\" — and 3–7 concrete, past-tense "
        "reasons follow, each closed by the mitigation that "
        "designs against it or an explicit accepted-risk "
        "note. The exercise generates reasons; it does not "
        "raise correctness by any measured percentage "
        "(Klein's famous 30% is the increase in reasons "
        "*generated* under prospective hindsight — Mitchell, "
        "Russo & Pennington 1989 — whose design carried no "
        "accuracy check).",
        "",
    ]


def proposal_page_content(root: Path, proposal: dict) -> str:
    """The staged content: current page + proposal section, or a draft."""
    target = root / proposal["target_path"]
    section = [
        "",
        "---",
        "",
        f"## {proposal['section']} — machine-generated (wiki-refine)",
        "",
        f"Label: **{proposal['label']}** · kind: {proposal['kind']} · "
        f"refine id: {proposal['id']}",
        "",
        proposal["sketch"],
        "",
        "Evidence from the query log:",
        "",
        f"```json\n{json.dumps(proposal['evidence'], indent=2, sort_keys=True)}\n```",
        "",
        "Filed by `scripts/wiki_refine.py` (WikiCitadel v1; pattern: "
        "DeepRefine-Skill, MIT). This is a proposal only — a reviewer "
        "makes any real edit by hand in staging and promotes (or "
        "rejects) through the ordinary gateway path.",
        "",
    ] + premortem_placeholder()
    if proposal["new_page"] or not target.is_file():
        d = date.today().isoformat()
        title = ("Standing answer — "
                 + Path(proposal["target_path"]).stem.replace("-", " "))
        front = ["---", f"title: {json.dumps(title)}", "type: query",
                 f"created: {d}", f"updated: {d}", "sources: []",
                 "tags: [refine, query-log]", "status: draft", "---",
                 "", f"# {title}", ""]
        return "\n".join(front + section)
    current = target.read_text(encoding="utf-8", errors="ignore")
    return current.rstrip() + "\n" + "\n".join(section)


def apply_proposals(root: Path, manifest: dict, include_low: bool = False,
                    store=None) -> dict:
    """Stage every non-LOW proposal (LOW too only with include_low).

    Mutates and returns the manifest: each proposal gains a status
    (staged / refused / error), the gateway proposal id when staged,
    and the run is appended to manifest['apply_runs'] and to the
    filing. Wiki pages are never written — staging only.
    """
    if store is None:
        from gateway.config import Config
        from gateway.store import GatewayStore
        env = {"GATEWAY_WIKI_ROOT": str(root),
               "GATEWAY_STAGING_DIR": str(root / "staging")}
        store = GatewayStore(Config(env=env))
    run = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "include_low": include_low, "staged": [], "refused": [],
           "errors": []}
    for p in manifest["proposals"]:
        if p.get("status") == "staged":
            continue
        if p["label"] == "LOW" and not include_low:
            p["status"] = "refused"
            p["apply_note"] = ("LOW evidence — refused by default "
                               "(re-run apply --include-low to stage it)")
            p["coaching_note"] = low_coaching_note(p)
            run["refused"].append(p["id"])
            continue
        try:
            content = proposal_page_content(root, p)
            meta = store.stage_proposal(
                actor="wiki-refine",
                session_id=f"wiki-refine-{manifest['date']}",
                target_path=p["target_path"], content=content,
                cites=[p["target_path"]],
                direction_source={"kind": "tooling",
                                  "ref": "scripts/wiki_refine.py"},
                task_ref="batch3.2-query-log-refinement")
            p["status"] = "staged"
            p["proposal_id"] = meta["proposal_id"]
            p["apply_note"] = f"gateway state: {meta['state']}"
            run["staged"].append({"id": p["id"],
                                  "proposal_id": meta["proposal_id"],
                                  "state": meta["state"],
                                  "target": p["target_path"]})
        except Exception as exc:  # staging refusal is a recorded outcome
            p["status"] = "error"
            p["apply_note"] = f"staging failed: {exc}"
            run["errors"].append({"id": p["id"], "error": str(exc)})
    manifest.setdefault("apply_runs", []).append(run)

    # Record the run in the filing + manifest on disk.
    md_path, json_path = filing_paths(root, manifest["date"])
    if md_path.is_file():
        lines = ["", f"## Apply run — {run['at']}",
                 "",
                 f"include_low: {str(include_low).lower()} · "
                 f"staged {len(run['staged'])} · "
                 f"refused {len(run['refused'])} · "
                 f"errors {len(run['errors'])}", ""]
        for s in run["staged"]:
            lines.append(f"- staged: {s['id']} → {s['proposal_id']} "
                         f"({s['state']}) targeting {s['target']}")
        by_id = {p["id"]: p for p in manifest["proposals"]}
        for r in run["refused"]:
            lines.append(f"- refused: {r} (LOW evidence, default)")
            note = (by_id.get(r) or {}).get("coaching_note")
            if note:
                lines.append(f"- coaching for {r}: {note}")
        for e in run["errors"]:
            lines.append(f"- error: {e['id']} — {e['error']}")
        if not (run["staged"] or run["refused"] or run["errors"]):
            lines.append("- nothing to stage (all proposals already "
                         "staged, or none).")
        lines.append("")
        with md_path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
    json_path.write_text(json.dumps(manifest, indent=2, sort_keys=True)
                         + "\n", encoding="utf-8")
    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", nargs="?", default="analyse",
                    choices=["analyse", "apply"])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--date", default=None,
                    help="filing date (YYYY-MM-DD); default today")
    ap.add_argument("--manifest", default=None,
                    help="apply: manifest JSON to stage from "
                         "(default: the filing for --date)")
    ap.add_argument("--include-low", action="store_true",
                    help="apply: also stage LOW-evidence proposals "
                         "(recorded in the run)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    today = (date.fromisoformat(args.date) if args.date else date.today())

    if args.command == "analyse":
        manifest = analyse(root, today=today)
        md_path, json_path = write_dry_run(root, manifest)
        st = manifest["stats"]
        print(f"dry run: {st['qa_records']} QA record(s) -> "
              f"{st['proposals']} proposal(s) "
              f"(HIGH {st['by_label']['HIGH']}, "
              f"MEDIUM {st['by_label']['MEDIUM']}, "
              f"LOW {st['by_label']['LOW']})")
        for p in manifest["proposals"]:
            print(f"  [{p['label']}] {p['kind']}: {p['target_path']}")
        print(f"filing:  {md_path.relative_to(root)}")
        print(f"manifest: {json_path.relative_to(root)}")
        return 0

    # apply
    if args.manifest:
        manifest = json.loads(Path(args.manifest).read_text(
            encoding="utf-8"))
    else:
        _md, json_path = filing_paths(root, today.isoformat())
        if not json_path.is_file():
            print(f"no dry-run manifest for {today.isoformat()} — "
                  f"run the dry run first", file=sys.stderr)
            return 2
        manifest = json.loads(json_path.read_text(encoding="utf-8"))
    manifest = apply_proposals(root, manifest,
                               include_low=args.include_low)
    run = manifest["apply_runs"][-1]
    print(f"apply: staged {len(run['staged'])}, "
          f"refused {len(run['refused'])}, errors {len(run['errors'])}"
          f" (include_low={args.include_low})")
    by_id = {p["id"]: p for p in manifest["proposals"]}
    for s in run["staged"]:
        print(f"  staged {s['id']} -> {s['proposal_id']} ({s['state']})")
    for r in run["refused"]:
        print(f"  refused {r} (LOW)")
        note = (by_id.get(r) or {}).get("coaching_note")
        if note:
            print(f"    coaching: {note}")
    for e in run["errors"]:
        print(f"  error {e['id']}: {e['error']}")
    return 0 if not run["errors"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
