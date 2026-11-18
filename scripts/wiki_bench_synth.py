#!/usr/bin/env python3
"""wiki_bench_synth.py — deterministic synthetic corpus generator
for the reproducible benchmark pack (Marathon Round 2, Lane G).

Why this exists: scripts/wiki_scale_bench.py's synthetic_docs()
builds in-memory (path, text) pairs for timing the BM25 ranker —
it writes no wiki/ tree and no golden questions, so it cannot
feed scripts/wiki_bench_repro.py, whose runner collects docs
from <root>/wiki/ and scores against
<root>/evaluation/golden-questions.jsonl. This generator fills
that gap: it writes a small SYNTHETIC multi-topic wiki corpus
plus a matching golden-questions file into a target root, so a
bench pack can be produced over a corpus whose every answer is
known by construction:

    python3 scripts/wiki_bench_synth.py --out /tmp/synth-root
    # copy the bench scripts into /tmp/synth-root/scripts/, then
    python3 /tmp/synth-root/scripts/wiki_bench_repro.py run \
        --label scale-2026-10-20 --root /tmp/synth-root \
        --git-head <pinned> --corpus-kind synthetic

Corpus design (all vocabulary disjoint across topics):

  * TOPICS topics (default: all six), each with its own core
    vocabulary and per-page focus words used nowhere else in
    the corpus;
  * each topic has one hub page (<topic>-overview) whose text
    is dense in the topic's core vocabulary, plus satellite
    pages that each own exactly one focus word;
  * pages link within their topic (satellites <-> hub, a ring
    of satellites) and each hub links to the next topic's hub,
    so the hybrid graph walk has real structure to walk;
  * two golden questions per topic: one asks after the hub
    using core vocabulary, one asks after a satellite using
    its unique focus word. must_cite is known by construction.

Determinism: generation depends only on (seed, topics,
pages_per_topic); the PRNG is seeded per topic from the seed,
frontmatter dates are fixed, and every list is emitted in
sorted order — two runs with the same arguments produce
byte-identical trees. The corpus is a fixture: its pages say
so in their frontmatter tags and body. It is NOT a substitute
for the real golden set; it measures that the bench machinery
runs end-to-end and ranks known answers first on a corpus
larger and more topically varied than the seed corpus.

Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

DEFAULT_SEED = 20261020
FIXED_DATE = "2026-10-20"

# (slug, core vocabulary, focus words) — every word below is
# unique across the whole table, so a topic's pages can only
# be confused with each other, never with another topic's.
TOPICS = (
    ("astronomy",
     ("telescope", "orbit", "nebula", "quasar", "eclipse", "comet"),
     ("pulsar", "zenith", "aurora", "meteor", "solstice", "parallax",
      "redshift", "occultation", "perihelion", "magnetosphere")),
    ("botany",
     ("photosynthesis", "stamen", "rhizome", "canopy", "pollinator",
      "seedling"),
     ("mycelium", "grafting", "herbarium", "deciduous", "taproot",
      "chlorophyll", "germination", "pruning", "compost", "trellis")),
    ("cooking",
     ("simmer", "caramelise", "julienne", "emulsify", "proofing",
      "seasoning"),
     ("brisket", "sourdough", "vinaigrette", "skillet", "marinade",
      "ganache", "risotto", "tempura", "bouillon", "zesting")),
    ("geology",
     ("basalt", "faultline", "sediment", "magma", "glacier", "tectonic"),
     ("obsidian", "sandstone", "gneiss", "alluvial", "caldera",
      "stalactite", "aquifer", "limestone", "feldspar", "drumlins")),
    ("music",
     ("counterpoint", "cadence", "timbre", "arpeggio", "fugue",
      "dynamics"),
     ("glissando", "vibrato", "ostinato", "syncopation", "harmonics",
      "staccato", "libretto", "overture", "nocturne", "capriccio")),
    ("sailing",
     ("starboard", "tacking", "ballast", "rudder", "mooring", "regatta"),
     ("spinnaker", "windward", "leeward", "catamaran", "anchorage",
      "boathook", "topsail", "keelhaul", "dead reckoning".replace(" ", ""),
      "figurehead")),
)

FILLER = ("notes record section summary details context entry "
          "account survey register catalogue appendix overview").split()


def _page_text(title, topic_slug, core, body_paras, tags, links):
    fm = [
        "---",
        f"title: {title}",
        "type: concept",
        f"created: {FIXED_DATE}",
        f"updated: {FIXED_DATE}",
        "sources: []",
        "tags: [" + ", ".join(tags) + "]",
        "---",
        "",
        f"# {title}",
        "",
    ]
    out = fm + body_paras
    if links:
        out += ["", "## Links", ""]
        out += [f"- [[{stem}]]" for stem in links]
    return "\n".join(out) + "\n"


def build_corpus(seed=DEFAULT_SEED, topic_count=None,
                 pages_per_topic=8):
    """(files, questions, manifest): files maps repo-relative
    path -> text for every generated file except the questions
    and manifest files; questions is the golden-question list;
    manifest summarises the corpus. Pure: no I/O."""
    topics = TOPICS[:topic_count] if topic_count else TOPICS
    if pages_per_topic < 2 or pages_per_topic > 11:
        raise ValueError("pages_per_topic must be in 2..11 "
                         "(hub + up to 10 satellites)")
    files = {}
    questions = []
    total_pages = 0
    for ti, (slug, core, focus_words) in enumerate(topics):
        rng = random.Random(f"bench-synth:{seed}:{slug}")
        core = list(core)
        sats = focus_words[:pages_per_topic - 1]
        hub_rel = f"wiki/{slug}/{slug}-overview.md"
        sat_rels = [f"wiki/{slug}/{slug}-{fw}.md" for fw in sats]
        next_hub = (f"{topics[(ti + 1) % len(topics)][0]}-overview")
        # --- hub page: dense in the core vocabulary
        core_sentence = " ".join(core)
        filler = " ".join(rng.choice(FILLER) for _ in range(24))
        hub_body = [
            f"The {slug} overview records {core_sentence}. "
            f"This synthetic hub page is the {slug} topic's "
            f"centre: {core_sentence} are its core terms, and "
            f"every {slug} satellite page links back here.",
            "",
            f"Core vocabulary, again in full: {core_sentence}. "
            f"{filler}.",
            "",
            "Satellites: " + ", ".join(sats) + ".",
        ]
        hub_links = [Path(r).stem for r in sat_rels] + [next_hub]
        files[hub_rel] = _page_text(
            f"{slug.capitalize()} overview — {core[0]} {core[1]} "
            f"{core[2]}", slug, core, hub_body,
            ["synthetic", slug], hub_links)
        # --- satellite pages: each owns one focus word
        for si, fw in enumerate(sats):
            filler = " ".join(rng.choice(FILLER) for _ in range(30))
            others = " ".join(rng.choice(core) for _ in range(6))
            body = [
                f"This synthetic page documents {fw} within "
                f"{slug}. The term {fw} belongs to this page "
                f"alone in the corpus; {fw} is recorded here "
                f"with {others}.",
                "",
                f"{filler}. The {slug} hub collects every "
                f"satellite term, and {fw} cross-refers to it.",
            ]
            ring_next = sats[(si + 1) % len(sats)]
            links = [f"{slug}-overview", f"{slug}-{ring_next}"]
            files[sat_rels[si]] = _page_text(
                f"{fw.capitalize()} in {slug}", slug, core, body,
                ["synthetic", slug], links)
        total_pages += 1 + len(sats)
        # --- golden questions: hub by core words, one satellite
        # --- by its unique focus word
        qn = len(questions) + 1
        questions.append({
            "id": f"SYN-{qn:03d}", "route": "synthetic",
            "question": f"What does the {slug} overview say "
                        f"about {core[0]}, {core[1]} and "
                        f"{core[2]}?",
            "expected_answer": f"The synthetic {slug} hub "
                               f"page (by construction).",
            "must_cite": [hub_rel], "acceptable_cites": [],
            "forbidden_claims": [], "as_of": FIXED_DATE,
            "source_of_truth": "scripts/wiki_bench_synth.py "
                               "(synthetic fixture, by "
                               "construction)",
        })
        qn = len(questions) + 1
        target_fw = sats[len(sats) // 2]
        questions.append({
            "id": f"SYN-{qn:03d}", "route": "synthetic",
            "question": f"What is recorded about {target_fw} "
                        f"in {slug}?",
            "expected_answer": f"The synthetic {slug} page "
                               f"owning {target_fw} (by "
                               f"construction).",
            "must_cite": [f"wiki/{slug}/{slug}-{target_fw}.md"],
            "acceptable_cites": [], "forbidden_claims": [],
            "as_of": FIXED_DATE,
            "source_of_truth": "scripts/wiki_bench_synth.py "
                               "(synthetic fixture, by "
                               "construction)",
        })
    questions_text = "".join(
        json.dumps(q, ensure_ascii=False, sort_keys=True) + "\n"
        for q in questions)
    manifest = {
        "kind": "synthetic-bench-corpus",
        "generator": "scripts/wiki_bench_synth.py",
        "seed": seed, "topics": [t[0] for t in topics],
        "pages_per_topic": pages_per_topic,
        "corpus_docs": total_pages,
        "questions_count": len(questions),
        "questions_sha256": hashlib.sha256(
            questions_text.encode("utf-8")).hexdigest(),
        "note": "Deterministic synthetic fixture corpus for "
                "the reproducible benchmark pack; not the "
                "real golden set.",
    }
    return files, questions, manifest


def write_corpus(out_root, seed=DEFAULT_SEED, topic_count=None,
                 pages_per_topic=8):
    """Write build_corpus()'s output under out_root and
    return the manifest (also written to
    evaluation/synthetic-manifest.json in the corpus)."""
    out_root = Path(out_root)
    files, questions, manifest = build_corpus(
        seed=seed, topic_count=topic_count,
        pages_per_topic=pages_per_topic)
    for rel, text in sorted(files.items()):
        dest = out_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    ev = out_root / "evaluation"
    ev.mkdir(parents=True, exist_ok=True)
    qtext = "".join(
        json.dumps(q, ensure_ascii=False, sort_keys=True) + "\n"
        for q in questions)
    (ev / "golden-questions.jsonl").write_text(qtext,
                                               encoding="utf-8")
    (ev / "synthetic-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the deterministic synthetic "
                    "bench corpus (see module docstring).")
    parser.add_argument("--out", required=True,
                        help="target root (created if needed)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--topics", type=int, default=None,
                        help="use only the first N topics")
    parser.add_argument("--pages-per-topic", type=int, default=8)
    args = parser.parse_args(argv)
    manifest = write_corpus(args.out, seed=args.seed,
                            topic_count=args.topics,
                            pages_per_topic=args.pages_per_topic)
    print(f"synthetic corpus: {manifest['corpus_docs']} pages, "
          f"{manifest['questions_count']} questions, topics "
          f"{', '.join(manifest['topics'])} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
