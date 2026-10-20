#!/usr/bin/env python3
"""Lens compiler — build the WikiCitadel Lens static site from the
canonical wiki repository.

One deterministic build (blueprint §1.2): parse -> page artefacts ->
edge table -> graph bundle -> search artefacts (+ parity check
against scripts/wiki_search.py) -> mode extracts -> Black Box
summary -> stamp. Same HEAD + same builder => byte-identical
artefacts except the stamp.

Usage:
  python3 tools/lens/build_lens.py [--repo ~/workspace/wikicitadel]
                                   [--out  ~/workspace/lens-site]
"""

import argparse
import html
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lenslib as L  # noqa: E402
import stateviews as SV  # noqa: E402  (Phase-8 items 63/65: state-shaped views, Briefing honesty)

BUILDER_VERSION = "lens-compiler 1.1 (FE-0..FE-6 local build + nashsu parity pass)"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout


def dump_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1),
                    encoding="utf-8")


def dump_js(path, varname, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"window.{varname}={json.dumps(obj, ensure_ascii=False, sort_keys=True)};",
                    encoding="utf-8")


# ---------------------------------------------------------------------------
# Louvain community detection (deterministic: sorted node order, smallest
# community id wins ties) over the weighted undirected graph.
# ---------------------------------------------------------------------------

def louvain(nodes, weights):
    # weights: dict frozenset({a,b}) -> w (a != b)
    adj = {n: {} for n in nodes}
    total2 = 0.0
    for pair, w in weights.items():
        a, b = tuple(pair)
        adj[a][b] = adj[a].get(b, 0.0) + w
        adj[b][a] = adj[b].get(a, 0.0) + w
        total2 += 2.0 * w
    if total2 == 0:
        return {n: i for i, n in enumerate(nodes)}
    deg = {n: sum(adj[n].values()) for n in nodes}
    comm = {n: i for i, n in enumerate(nodes)}
    improved = True
    while improved:
        improved = False
        for n in sorted(nodes):
            cur = comm[n]
            # weight from n to each neighbouring community
            to_comm = defaultdict(float)
            for nb, w in adj[n].items():
                if nb != n:
                    to_comm[comm[nb]] += w
            # community degree sums
            comm_deg = defaultdict(float)
            for x in nodes:
                comm_deg[comm[x]] += deg[x]
            best_c, best_gain = cur, 0.0
            for c in sorted(to_comm):
                if c == cur:
                    continue
                gain = to_comm[c] - comm_deg[c] * deg[n] / total2
                cur_gain = to_comm.get(cur, 0.0) - (comm_deg[cur] - deg[n]) * deg[n] / total2
                delta = gain - cur_gain
                if delta > best_gain + 1e-12:
                    best_gain, best_c = delta, c
            if best_c != cur:
                comm[n] = best_c
                improved = True
    # renumber communities by smallest member id
    remap = {}
    for n in sorted(nodes):
        c = comm[n]
        if c not in remap:
            remap[c] = len(remap)
    return {n: remap[comm[n]] for n in nodes}


def force_layout(nodes, edges, width=1000, height=660, seed=20261013):
    import random
    rng = random.Random(seed)
    pos = {n: [rng.uniform(60, width - 60), rng.uniform(60, height - 60)] for n in nodes}
    k = (width * height / max(1, len(nodes))) ** 0.5
    temp = width / 8.0
    for it in range(320):
        disp = {n: [0.0, 0.0] for n in nodes}
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                d2 = dx * dx + dy * dy + 0.01
                d = d2 ** 0.5
                f = k * k / d
                disp[a][0] += dx / d * f
                disp[a][1] += dy / d * f
                disp[b][0] -= dx / d * f
                disp[b][1] -= dy / d * f
        for (a, b, w) in edges:
            dx = pos[a][0] - pos[b][0]
            dy = pos[a][1] - pos[b][1]
            d = (dx * dx + dy * dy) ** 0.5 + 0.01
            f = d * d / k * min(1.0, w / 4.0 + 0.35)
            disp[a][0] -= dx / d * f
            disp[a][1] -= dy / d * f
            disp[b][0] += dx / d * f
            disp[b][1] += dy / d * f
        for n in nodes:
            dl = (disp[n][0] ** 2 + disp[n][1] ** 2) ** 0.5 + 0.01
            step = min(dl, temp)
            pos[n][0] = min(width - 30, max(30, pos[n][0] + disp[n][0] / dl * step))
            pos[n][1] = min(height - 30, max(30, pos[n][1] + disp[n][1] / dl * step))
        temp *= 0.985
    return {n: [round(pos[n][0], 1), round(pos[n][1], 1)] for n in nodes}


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def dispute_items(pages, route_by_stem, page_by_id):
    """Phase-2 harvest item 9: unresolved talk-page disputes as
    insight items. A talk page (wiki/talk/<page>.md) carries
    `about:` (repo-relative path of the disputed page) and
    `dispute_status:` (open|resolved) in its frontmatter. Open
    disputes surface here deterministically — path order in, fixed
    text shape out, nothing inferred. `about` resolves through the
    same route table as wikilinks, so every page reference in an
    item is a real graph node."""
    items = []
    for pg in sorted(pages, key=lambda p: p["path"]):
        if not pg["path"].startswith("wiki/talk/"):
            continue
        fm = pg.get("fm") or {}
        if str(fm.get("dispute_status") or "").strip().lower() != "open":
            continue
        about = str(fm.get("about") or "")
        about_id = None
        if about:
            key = str(Path(about).with_suffix("")).replace("\\", "/")
            about_id = route_by_stem.get(key) or route_by_stem.get(Path(about).stem)
        target = page_by_id[about_id]["title"] if about_id in page_by_id else about
        items.append({"pages": [about_id] if about_id else [],
                      "text": f"Unresolved dispute on '{target}': "
                              f"'{pg['title']}' is open."})
    return items


def _display_sections(pg):
    """Deterministic display-time sections (harvest item 10):
    unlinked mentions of this page, and this page's blockquotes
    verified verbatim against its cited raw sources."""
    import html as _h
    out = []
    mentions = pg.get("mentions") or []
    if mentions:
        items = "".join(
            f'<li><a href="{m["id"]}.html">{_h.escape(m["title"])}</a>'
            f' — <span class="mention-line">{_h.escape(m["line"])}</span></li>'
            for m in mentions)
        out.append('<section class="display-extra"><h2>Mentions (unlinked)'
                   "</h2><p class=\"note\">Pages that name this page's title "
                   "in prose but do not link to it — computed "
                   "deterministically at build time.</p>"
                   f"<ul>{items}</ul></section>")
    quotes = pg.get("quotes") or []
    if quotes:
        items = "".join(
            f'<li><blockquote>{_h.escape(q["text"])}</blockquote>'
            f'<p class="quote-src">verbatim in {q["source"]} '
            f'line {q["line"]}</p></li>' for q in quotes)
        out.append('<section class="display-extra"><h2>Verified quotations'
                   "</h2><p class=\"note\">Blockquotes on this page found "
                   "verbatim in its cited raw sources.</p>"
                   f"<ul>{items}</ul></section>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Briefing preamble for the agent-readable exports (llms.txt /
# llms-full.txt): teaches an admitted LLM how to use this wiki —
# what it is, the standing questions with their current answers,
# the citation discipline, and the Ask door. Deterministic: the
# only variable content is the body of
# wiki/syntheses/current-state.md, read at build time.
# ---------------------------------------------------------------------------

STANDING_QUESTIONS_FALLBACK = [
    "Where does everything stand, overall?",
    "What is blocked, and on whom?",
    "What decisions await the owner?",
    "What is live right now?",
    "What money clocks are ticking?",
    "What changed most recently?",
]


def build_briefing(repo, query_pages=None, cs_id=None):
    cs_path = repo / "wiki" / "syntheses" / "current-state.md"
    questions = list(STANDING_QUESTIONS_FALLBACK)
    cs_body = ""
    if cs_path.exists():
        _fm, body, _text = L.parse_markdown_file(cs_path)
        cs_body = body.strip()
        if query_pages is not None:
            # The standing page's live queries are evaluated here
            # too, so the briefing reads as answers, not raw blocks.
            cs_body = L.expand_wiki_queries(cs_body, query_pages,
                                            self_id=cs_id)
        found = re.findall(r"(?m)^## Q\d+\.\s+(.+?)\s*$", cs_body)
        if len(found) == len(STANDING_QUESTIONS_FALLBACK):
            questions = found
    lines = [
        "# Briefing — read this first",
        "",
        "## What this wiki is",
        "",
        "This is Owner's private LLM Wiki: a personal knowledge "
        "base of interlinked, source-cited markdown pages, "
        "maintained by the owner's agent and canonical in a "
        "private git repository. Access is OWNER-ONLY — "
        "the Lens portal sits behind the owner's sign-in, and "
        "these exports exist only inside that wall. Nothing here "
        "is public. An admitted reader (an agent or tool the "
        "owner has let in) may read this wiki to answer the "
        "owner's questions; it must not republish, quote, or copy "
        "any of it anywhere else.",
        "",
        "## The standing questions",
        "",
        "The wiki keeps one standing-question page, "
        "wiki/syntheses/current-state.md: six questions, defined "
        "once, whose answers are refreshed whenever the "
        "underlying facts change. The questions are:",
        "",
    ]
    lines += [f"{i}. {q}" for i, q in enumerate(questions, 1)]
    if cs_body:
        lines += ["",
                  "The page's current text follows "
                  "(live query blocks evaluated at build time):",
                  "",
                  cs_body]
    lines += [
        "",
        "## How to use this wiki",
        "",
        "- Reading order: this briefing first, then the index "
        "(the catalogue of every page — in this export, the "
        "Pages list below), then the pages themselves, following "
        "their wikilinks.",
        "- Every factual answer must cite the pages it used. "
        "Name the pages; an answer without its pages is not an "
        "answer from this wiki.",
        "- Claims carry evidence: a claim that rests on one "
        "passage bears an inline ^[cite: raw/...#L<start>-L<end>] "
        "marker pointing at the raw source, and every page's "
        "frontmatter sources list the raw files it rests on. The "
        "raw layer (raw/) is the source of truth; the compiled "
        "pages are the map to it.",
        "- If the wiki does not say, say so. Never invent a fact, "
        "a date, or a citation to fill a gap — insufficient "
        "evidence is an answer.",
        "",
        "## How to ask",
        "",
        "The Lens has an Ask door for questions: a question "
        "submitted there is picked up and answered by the agent "
        "with citations. The door is gated by the owner's ask "
        "token, and answers take minutes, not seconds — the door "
        "is a mailbox, not a chat. A reader without a token can "
        "only read. Reading is the whole of your access: you "
        "cannot file, edit, or decide anything in this wiki.",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    home = Path.home()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--out", default=str(home / "workspace/lens-site"))
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    out = Path(args.out).resolve()
    wiki = repo / "wiki"
    raw = repo / "raw"
    assets = Path(__file__).resolve().parent / "assets"

    head = git(repo, "rev-parse", "HEAD").strip()
    head_short = head[:7]
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.now().astimezone()
    generated_at = now.strftime("%Y-%m-%d %H:%M %Z")
    stamp = {"generated_at": generated_at, "git_head": head, "git_head_short": head_short,
             "builder": BUILDER_VERSION}

    # Previous build stamp (for Briefing deltas)
    prev_stamp = None
    stamp_file = out / ".build-stamp.json"
    if stamp_file.exists():
        try:
            prev_stamp = json.loads(stamp_file.read_text())
        except json.JSONDecodeError:
            prev_stamp = None

    # ---------------- Parse corpus ----------------
    # wiki/access/ holds gateway records (the identity/scope table,
    # the activation record). They are surfaced through the Black
    # Box summary below, not as reading pages in the graph.
    md_files = sorted(p for p in wiki.rglob("*.md") if p.is_file()
                      and "access" not in p.relative_to(wiki).parts[:-1])
    by_stem = {}
    pages_raw = []
    for p in md_files:
        fm, body, text = L.parse_markdown_file(p)
        rel = str(p.relative_to(repo))
        pages_raw.append({"path": rel, "abspath": p, "fm": fm, "body": body, "text": text})
        by_stem.setdefault(p.stem, []).append(rel)

    # Page ids: frontmatter id wins; else stem; collisions disambiguated
    # by type prefix (blueprint §1.3). index/log/overview are structural
    # but still get page artefacts; graph/cards use content pages only.
    used_ids = {}
    for pg in pages_raw:
        fm = pg["fm"]
        stem = Path(pg["path"]).stem
        pid = fm.get("id") or stem
        if pid in used_ids:
            ptype = str(fm.get("type") or "page").lower()
            candidate = f"{ptype}-{stem}"
            n = 2
            base = candidate
            while candidate in used_ids:
                candidate = f"{base}-{n}"
                n += 1
            pid = candidate
            print(f"ROUTE NOTE: id collision for {stem!r} -> {pid!r} ({pg['path']})")
        used_ids[pid] = pg["path"]
        pg["id"] = pid
        pg["title"] = str(fm.get("title") or L.first_h1(pg["body"]) or stem)
        pg["type"] = str(fm.get("type") or "page")
        pg["created"] = str(fm.get("created") or "")
        pg["updated"] = str(fm.get("updated") or "")
        pg["tags"] = [str(t) for t in (fm.get("tags") or [])]
        pg["stage"] = str(fm.get("stage") or "")
        pg["planted"] = str(fm.get("planted") or "")
        pg["tended"] = str(fm.get("tended") or "")
        srcs = fm.get("sources") or []
        if isinstance(srcs, str):
            srcs = [srcs]
        pg["sources_fm"] = [str(s) for s in srcs]
        pg["lede"] = L.extract_lede(pg["body"])
        pg["headings"] = L.page_headings(pg["body"])
        pg["wikilinks"] = L.extract_wikilinks(pg["body"])
        pg["wikilinks_typed"] = L.extract_wikilinks_typed(pg["body"])
        pg["link_sentences"] = L.extract_link_sentences(pg["body"])
        pg["section"] = Path(pg["path"]).parent.name if Path(pg["path"]).parent.name != "wiki" else "wiki"

    route_by_stem = {}
    for pg in pages_raw:
        route_by_stem.setdefault(Path(pg["path"]).stem, pg["id"])
        route_by_stem[pg["id"]] = pg["id"]
    for pg in pages_raw:
        route_by_stem[str(Path(pg["path"]).with_suffix("")).replace("\\", "/")] = pg["id"]

    structural = {"index", "log"}
    content_pages = [pg for pg in pages_raw if pg["id"] not in structural]
    page_by_id = {pg["id"]: pg for pg in pages_raw}

    # ---------------- Provenance manifest + raw inventory ----------------
    manifest = {}
    manifest_meta = {}
    man_path = raw / "sources" / "provenance-manifest.json"
    if man_path.exists():
        mj = json.loads(man_path.read_text())
        manifest = mj.get("files", {}) or {}
        manifest_meta = {"file_count": mj.get("file_count"), "total_bytes": mj.get("total_bytes"),
                         "generated_at": mj.get("generated_at"),
                         "schema_version": mj.get("schema_version")}
    raw_files = sorted(str(p.relative_to(repo)) for p in raw.rglob("*") if p.is_file())
    raw_set = set(raw_files)
    hash_state = {}  # raw path -> verified | changed | not-in-manifest | missing
    for rp in raw_files:
        if rp == "raw/sources/provenance-manifest.json":
            continue
        entry = manifest.get(rp)
        if entry is None:
            hash_state[rp] = "not-in-manifest"
        else:
            actual = L.sha256_file(repo / rp)
            hash_state[rp] = "verified" if actual == entry.get("sha256") else "changed"
    drift = sorted(rp for rp, st in hash_state.items() if st == "changed")
    manifest_status = {
        "files_in_manifest": manifest_meta.get("file_count"),
        "files_on_disk": len(raw_files),
        "verified": sum(1 for s in hash_state.values() if s == "verified"),
        "changed": drift,
        "not_in_manifest": sorted(rp for rp, s in hash_state.items() if s == "not-in-manifest"),
        "generated_at": manifest_meta.get("generated_at"),
        "total_bytes": manifest_meta.get("total_bytes"),
    }

    def citation_info(src):
        # Some pages cite a wiki page by slug in sources[] (e.g.
        # a decisions page cites the report that posed its
        # questions, by slug).
        # Resolve those honestly as page citations instead of
        # reporting a missing raw file.
        if not src.startswith("raw/"):
            pid = route_by_stem.get(src) or route_by_stem.get(Path(src).name)
            if pid:
                return {"path": src, "exists": True, "is_page": True, "page_id": pid,
                        "sha256": None, "sha_short": None, "bytes": None,
                        "hash_state": "page"}
        rp = src if src.startswith("raw/") else f"raw/{src}"
        exists = rp in raw_set
        entry = manifest.get(rp)
        return {"path": rp, "exists": exists, "is_page": False,
                "sha256": entry.get("sha256") if entry else None,
                "sha_short": (entry.get("sha256") or "")[:10] if entry else None,
                "bytes": entry.get("bytes") if entry else None,
                "hash_state": hash_state.get(rp, "missing") if exists else "missing"}

    # ---------------- Edges (one table) ----------------
    # Epistemic tags (harvest item 4; pattern from SamurAIGPT/
    # llm-wiki-agent and swarmvault, both MIT): every edge says
    # whether it was EXTRACTED — present deterministically in the
    # page text or frontmatter (a written wikilink, a typed link
    # the author declared, a frontmatter citation) — or INFERRED
    # by the build (the derived pair relations below: shared
    # sources / common neighbours with no direct link). Readers
    # can then tell fact from inference at a glance.
    #
    # Typed edges (the build; patterns: wiki-to-graph — a link's
    # type inferred from the heading it sits under; zby/
    # commonplace, MIT — the typed-link vocabulary): every edge
    # row also carries `type` + `section`. For a wikilink, `type`
    # is inferred from its section heading via
    # lenslib.SECTION_TYPE_RULES (closed vocabulary: grounds,
    # contradicts, extends, exemplifies, supersedes, mentions) and
    # `section` is that heading's text; wikilink edges dedupe per
    # (target, type), so one page linking another as both evidence
    # and contradiction yields two typed edges, not one blurred
    # one. For a frontmatter `links:` edge the author declared the
    # relation, so type = that relation; for a citation, "cites".
    edges = []
    broken_targets = Counter()
    for pg in content_pages:
        seen = set()
        for target, anchor, _label, section, ltype in pg["wikilinks_typed"]:
            dst = route_by_stem.get(target) or route_by_stem.get(Path(target).name)
            if dst and dst != pg["id"] and (dst, ltype) not in seen:
                seen.add((dst, ltype))
                edges.append({"src": pg["id"], "dst": dst, "kind": "wikilink",
                              "relation": "mentions", "type": ltype,
                              "section": section, "anchor": anchor,
                              "epistemic": "extracted"})
            elif not dst:
                broken_targets[target] += 1
        for src in pg["sources_fm"]:
            info = citation_info(src)
            key = (info["path"], "citation")
            if key not in seen:
                seen.add(key)
                dst = info["page_id"] if info.get("is_page") else f"raw:{info['path']}"
                edges.append({"src": pg["id"], "dst": dst,
                              "kind": "citation", "relation": "cites",
                              "type": "cites", "section": None, "anchor": None,
                              "epistemic": "extracted"})
        links_fm = pg["fm"].get("links") or {}
        if isinstance(links_fm, dict):
            for relation, targets in links_fm.items():
                if isinstance(targets, str):
                    targets = [targets]
                for t in targets or []:
                    dst = route_by_stem.get(str(t)) or route_by_stem.get(Path(str(t)).name)
                    if dst:
                        edges.append({"src": pg["id"], "dst": dst, "kind": "typed",
                                      "relation": str(relation),
                                      "type": str(relation), "section": None,
                                      "anchor": None,
                                      "epistemic": "extracted"})

    backlinks = defaultdict(list)
    neighbours = defaultdict(set)
    for e in edges:
        if e["kind"] in ("wikilink", "typed"):
            backlinks[e["dst"]].append({"from": e["src"], "kind": e["kind"],
                                        "relation": e["relation"],
                                        "type": e.get("type"),
                                        "anchor": e["anchor"]})
            neighbours[e["src"]].add(e["dst"])
            neighbours[e["dst"]].add(e["src"])
    orphans = sorted(pg["id"] for pg in content_pages if not neighbours.get(pg["id"]))

    # ---------------- Mentions + verbatim quotes (display-time) ------
    # Harvest item 10 (pattern: Emmimal/wiki-compiler, MIT — a
    # deterministic phrase-matcher mention graph, zero LLM calls).
    # MENTIONS: pages whose body names another page's title as a
    # phrase but does NOT link it — the link that was never made,
    # computed identically on every build. QUOTES: blockquotes in a
    # page that appear VERBATIM in one of the page's cited raw
    # sources (normalised substring match, line located) — a quote
    # is displayed with its provenance only when it verifies.
    link_pairs = {(e["src"], e["dst"]) for e in edges
                  if e["kind"] in ("wikilink", "typed")}
    norm_cache = {}

    def norm_with_lines(path):
        """(joined normalised text, [(offset, lineno)]) for a file."""
        if path not in norm_cache:
            raw_text = path.read_text(encoding="utf-8", errors="ignore")
            parts, marks, offset = [], [], 0
            for ln, line in enumerate(raw_text.splitlines(), start=1):
                nl = " ".join(L.plain_text(line).lower().split())
                marks.append((offset, ln))
                parts.append(nl)
                offset += len(nl) + 1
            norm_cache[path] = (" ".join(parts), marks)
        return norm_cache[path]

    def norm_text(s):
        return " ".join(L.plain_text(s).lower().split())

    for pg in content_pages:
        title = pg["title"].strip()
        pg["mentions"] = []
        if len(title) >= 5 and title.lower() not in ("overview",):
            pat = re.compile(r"(?<![a-z0-9])" + re.escape(title.lower())
                             + r"(?![a-z0-9])")
            for other in content_pages:
                if other["id"] == pg["id"] or (other["id"], pg["id"]) in link_pairs:
                    continue
                for line in other["body"].splitlines():
                    if pat.search(line.lower()):
                        pg["mentions"].append(
                            {"id": other["id"], "title": other["title"],
                             "line": " ".join(line.strip().split())[:160]})
                        break
            pg["mentions"].sort(key=lambda m: m["id"])
            pg["mentions"] = pg["mentions"][:12]
        # Verbatim quotes from this page's blockquotes.
        pg["quotes"] = []
        blocks, cur = [], []
        for line in pg["body"].splitlines():
            if line.lstrip().startswith(">"):
                cur.append(re.sub(r"^\s*>\s?", "", line))
            elif cur:
                blocks.append(cur)
                cur = []
        if cur:
            blocks.append(cur)
        raw_paths = []
        for s in pg["sources_fm"]:
            info = citation_info(s)
            if not info.get("is_page") and info["exists"]:
                raw_paths.append(repo / info["path"])
        seen_quotes = set()
        for block in blocks:
            qtext = norm_text(" ".join(block))
            qtext = re.sub(r"^\[!\w+\]\s*", "", qtext)
            if len(qtext) < 25 or qtext in seen_quotes:
                continue
            seen_quotes.add(qtext)
            for rp in raw_paths:
                joined, marks = norm_with_lines(rp)
                pos = joined.find(qtext)
                if pos >= 0:
                    lineno = 1
                    for off, ln in marks:
                        if off > pos:
                            break
                        lineno = ln
                    pg["quotes"].append(
                        {"text": " ".join(" ".join(block).split())[:280],
                         "source": str(rp.relative_to(repo)), "line": lineno})
                    break
            if len(pg["quotes"]) >= 8:
                break

    # Index catalogue (for summaries + index lane)
    index_entries = []
    index_by_id = {}
    idx_pg = page_by_id.get("index")
    if idx_pg:
        section = ""
        for line in idx_pg["body"].splitlines():
            hm = re.match(r"^##\s+(.*)", line)
            if hm:
                section = hm.group(1).strip()
                continue
            m = re.match(r"^-\s+\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]\s*[—–-]\s*(.*)$", line.strip())
            if m:
                pid = route_by_stem.get(m.group(1)) or route_by_stem.get(Path(m.group(1)).name)
                if pid:
                    index_entries.append({"id": pid, "section": section,
                                          "line": line.strip(), "summary": m.group(2).strip()})
                    index_by_id.setdefault(pid, index_entries[-1])

    # ---------------- Live queries (the build) ----------------
    # The page index wiki-query blocks evaluate against: frontmatter
    # metadata + normalised outgoing link targets for every page.
    query_pages = []
    for pg in pages_raw:
        targets = set()
        for (t, _anchor, _label) in pg["wikilinks"]:
            nt = L.norm_link_target(t)
            targets.add(nt)
            targets.add(nt.rsplit("/", 1)[-1])
        query_pages.append({
            "id": pg["id"],
            "link": str(Path(pg["path"]).with_suffix("")).replace("\\", "/"),
            "title": pg["title"], "type": pg["type"],
            "section": pg["section"], "tags": pg["tags"],
            "status": str(pg["fm"].get("status") or ""),
            "created": pg["created"], "updated": pg["updated"],
            "as_of": str(pg["fm"].get("as_of") or ""),
            "links": targets,
        })

    # ---------------- Page artefacts ----------------
    # Source-adjacent evidence (item 62b): the citation lockfile's
    # verbatim pairings per page, attached to the page artefact
    # below. A page (or claim) absent from the lockfile gets an
    # empty list and the reading view shows nothing for it.
    cite_lock_pages = L.load_citation_lockfile(repo)
    # Argdown (item 63c): a fenced ```argdown block in a page is
    # compiled at build time to an inline SVG argument map by our
    # own subset parser (stateviews.parse_argdown — nothing
    # vendored; the syntax is Argdown's, MIT, argdown.org). The
    # block is lifted out before rendering and replaced by a
    # placeholder paragraph; the figure (map + the source block,
    # kept as the source of truth) is substituted back after.
    argdown_census = {"blocks": 0, "pages": [], "unparsed": []}
    pages_json = {}
    for pg in pages_raw:
        argdown_figs = []

        def _argdown_sub(m, _figs=argdown_figs, _pg=pg):
            src = m.group(1)
            model = SV.parse_argdown(src)
            svg, warns = SV.argdown_svg(model)
            idx = len(_figs)
            notes = "".join(
                '<p class="caption">Not compiled (outside the supported '
                f'subset): {html.escape(u)}</p>' for u in model["unparsed"])
            notes += "".join(
                f'<p class="caption">{html.escape(w)}</p>'
                for w in model["warnings"] + warns)
            _figs.append(
                '<figure class="argmap"><figcaption>Argument map — '
                'compiled at build from the Argdown block below; the '
                f'block is the source of truth.</figcaption>{svg}'
                '<details><summary>Argdown source</summary>'
                f'<pre><code>{html.escape(src)}</code></pre></details>'
                f'{notes}</figure>')
            argdown_census["blocks"] += 1
            if _pg["id"] not in argdown_census["pages"]:
                argdown_census["pages"].append(_pg["id"])
            for u in model["unparsed"]:
                argdown_census["unparsed"].append(
                    {"page": _pg["id"], "line": u})
            return f"\n\nLENSARGDOWNMAP{idx}\n\n"

        body_src = re.sub(r"(?ms)^```argdown[ \t]*\n(.*?)^```[ \t]*$",
                          _argdown_sub, pg["body"])
        render_body = L.expand_wiki_queries(body_src, query_pages,
                                            self_id=pg["id"])
        html_body, wl = L.render_markdown(render_body)
        for i, fig in enumerate(argdown_figs):
            token = f"<p>LENSARGDOWNMAP{i}</p>"
            if token in html_body:
                html_body = html_body.replace(token, fig)
            elif f"LENSARGDOWNMAP{i}" in html_body:
                html_body = html_body.replace(f"LENSARGDOWNMAP{i}", fig)
        html_body = L.resolve_wikilinks(html_body, wl, route_by_stem)
        html_body += _display_sections(pg)
        hist_raw = git(repo, "log", "--format=%H%x09%cI%x09%s", "-n", "8", "--", pg["path"])
        history = []
        for ln in hist_raw.splitlines():
            parts = ln.split("\t")
            if len(parts) == 3:
                history.append({"sha": parts[0][:7], "date": parts[1][:10], "subject": parts[2]})
        citations = [citation_info(s) for s in pg["sources_fm"]]
        stale = any(c["hash_state"] == "changed" for c in citations)
        # Owner attestation (wave-3 set B): the page is shown as
        # owner-verified only while its frontmatter verified_until
        # — carried with verified_by: owner — is still in the
        # future at build time. An agent's name in verified_by, a
        # malformed date, or a lapsed date renders nothing (the
        # lint lanes surface lapsed/invalid attestations).
        vu = str(pg["fm"].get("verified_until") or "")
        vb = str(pg["fm"].get("verified_by") or "")
        attested_until = vu if (vb == "owner"
                                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", vu)
                                and vu >= now.date().isoformat()) else ""
        pages_json[pg["id"]] = {
            "id": pg["id"], "path": pg["path"], "title": pg["title"], "type": pg["type"],
            "section": pg["section"], "created": pg["created"], "updated": pg["updated"],
            "tags": pg["tags"], "lede": pg["lede"], "headings": pg["headings"],
            "html": html_body, "citations": citations, "stale": stale,
            "backlinks": sorted(backlinks.get(pg["id"], []), key=lambda b: b["from"]),
            "history": history,
            "sources_count": len(citations),
            "mentions": pg.get("mentions", []),
            "quotes": pg.get("quotes", []),
            "verified_until": vu, "verified_by": vb,
            "attested_until": attested_until,
            "stage": pg["stage"], "planted": pg["planted"] or None,
            "tended": pg["tended"] or None,
            "cite_passages": cite_lock_pages.get(pg["path"], []),
        }

    routes = {"routes": [{"id": pg["id"], "path": pg["path"], "title": pg["title"],
                          "type": pg["type"], "route": f"/read/{pg['id']}"}
                         for pg in pages_raw],
              **stamp}

    # Standalone per-page HTML (spot-checkable, printable)
    css_link = '<link rel="stylesheet" href="../lens.css">'
    for pid, pj in pages_json.items():
        standalone = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(pj['title'], quote=True)} — WikiCitadel Lens</title>{css_link}</head>
<body class="standalone"><main class="standalone-main">
<p class="stamp-line">Built {generated_at} · from <code>{head_short}</code> · <a href="../index.html#/read/{pid}">Open in the Lens</a></p>
<article class="reading-body">{pj['html']}</article>
</main></body></html>"""
        (out / "data" / "pages").mkdir(parents=True, exist_ok=True)
        (out / "data" / "pages" / f"{pid}.html").write_text(standalone, encoding="utf-8")
        dump_json(out / "data" / "pages" / f"{pid}.json",
                  {k: v for k, v in pj.items() if k != "html"} | {"html_file": f"pages/{pid}.html"})
    # Idempotency for CI: remove page artefacts from earlier builds
    # whose pages no longer exist, so a rebuild over an existing
    # output directory is exactly the fresh-build result.
    pages_dir = out / "data" / "pages"
    expected = {f"{pid}.{ext}" for pid in pages_json for ext in ("html", "json")}
    for old in pages_dir.iterdir():
        if old.is_file() and old.name not in expected:
            old.unlink()
    dump_json(out / "data" / "routes.json", routes)
    with open(out / "data" / "edges.jsonl", "w", encoding="utf-8") as fh:
        for e in edges:
            fh.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
    dump_js(out / "data" / "pages.js", "LENS_PAGES", pages_json)
    dump_js(out / "data" / "routes.js", "LENS_ROUTES", routes)

    # ---------------- Graph bundle ----------------
    node_ids = [pg["id"] for pg in content_pages]
    # Shared-source signal counts raw citations only (page-slug
    # citations are not shared raw sources).
    sources_of = {}
    for pg in content_pages:
        raw_cites = set()
        for s in pg["sources_fm"]:
            info = citation_info(s)
            if not info.get("is_page") and info["exists"]:
                raw_cites.add(info["path"])
        sources_of[pg["id"]] = raw_cites
    pair_signals = {}

    def pair_key(a, b):
        # sorted tuple, never a frozenset: frozenset iteration order
        # depends on per-process string hashing, which would flip
        # edge endpoints between runs and break determinism.
        return (a, b) if a <= b else (b, a)

    direct_pairs = set()
    for e in edges:
        if e["kind"] in ("wikilink", "typed") and e["src"] in page_by_id and e["dst"] in page_by_id:
            direct_pairs.add(pair_key(e["src"], e["dst"]))
    for i, a in enumerate(node_ids):
        for b in node_ids[i + 1:]:
            direct = 1 if pair_key(a, b) in direct_pairs else 0
            shared = len(sources_of[a] & sources_of[b])
            common = len(neighbours.get(a, set()) & neighbours.get(b, set()))
            affinity = 1 if page_by_id[a]["type"] == page_by_id[b]["type"] else 0
            if direct or shared or common >= 2:
                w = 3.0 * direct + 1.5 * shared + 0.8 * common + 0.5 * affinity
                pair_signals[pair_key(a, b)] = {"direct": direct, "shared_sources": shared,
                                                "common_neighbours": common,
                                                "type_affinity": affinity, "weight": round(w, 2)}
    weights = {k: v["weight"] for k, v in pair_signals.items()}
    communities = louvain(node_ids, weights)
    comm_members = defaultdict(list)
    for n, c in communities.items():
        comm_members[c].append(n)
    comm_label = {}
    for c, members in comm_members.items():
        hub = max(members, key=lambda n: len(neighbours.get(n, set())))
        comm_label[c] = f"Cluster around {page_by_id[hub]['title']}"
    layout = force_layout(node_ids, [(k[0], k[1], v["weight"]) for k, v in pair_signals.items()])

    # Display groups for the graph legend + Knowledge panel. The
    # overview page is frontmatter-typed "synthesis" but is the
    # wiki's Overview — it gets its own group (owner's legend:
    # Overview yellow). Everything else groups by frontmatter type;
    # an unlisted type falls into "other". Group colours are the
    # functional palette the owner asked for (entity blue, concept
    # purple, source orange, overview yellow); synthesis keeps this
    # design system's teal-green, query/other its neutral grey.
    GROUP_ORDER = ["overview", "source", "entity", "concept", "synthesis", "query", "other"]
    GROUP_LABEL = {"overview": "Overview", "source": "Sources", "entity": "Entities",
                   "concept": "Concepts", "synthesis": "Syntheses", "query": "Queries",
                   "other": "Other"}
    GROUP_SINGULAR = {"overview": "Overview", "source": "Source", "entity": "Entity",
                      "concept": "Concept", "synthesis": "Synthesis", "query": "Query",
                      "other": "Other"}
    GROUP_COLOUR = {"overview": "#F2C94C", "source": "#F2994A", "entity": "#5B8DEF",
                    "concept": "#A06CD5", "synthesis": "#5FA88F", "query": "#95A5A6",
                    "other": "#95A5A6"}

    def display_group(pg):
        if pg["id"] == "overview":
            return "overview"
        t = str(pg.get("type") or "page").lower()
        return t if t in GROUP_LABEL else "other"

    # Weighted degree: the sum of a node's incident relation weights.
    # Node size in the client scales with this (relevance sizing).
    wdegree = {n: 0.0 for n in node_ids}
    for k, v in pair_signals.items():
        wdegree[k[0]] += v["weight"]
        wdegree[k[1]] += v["weight"]
    wdegree = {n: round(w, 2) for n, w in wdegree.items()}

    graph_nodes = [{"id": n, "title": page_by_id[n]["title"], "type": page_by_id[n]["type"],
                    "group": display_group(page_by_id[n]),
                    "degree": len(neighbours.get(n, set())),
                    "wdegree": wdegree[n],
                    "community": communities[n],
                    "x": layout[n][0], "y": layout[n][1]} for n in node_ids]
    # Typed relations per pair (the build): counts of the typed
    # edges between the pair's two pages, both directions summed,
    # plus the dominant type (most edges; ties broken by the
    # vocabulary's own order in lenslib.LINK_TYPES so the result
    # is deterministic). Only direct pairs carry types — a derived
    # pair has no written link whose meaning could be typed.
    pair_types = {}
    for e in edges:
        if e["kind"] in ("wikilink", "typed") and e["src"] in page_by_id \
                and e["dst"] in page_by_id:
            counts = pair_types.setdefault(pair_key(e["src"], e["dst"]),
                                           Counter())
            counts[e.get("type") or "mentions"] += 1

    def dominant_type(counts):
        return sorted(counts.items(),
                      key=lambda kv: (-kv[1],
                                      L.LINK_TYPES.index(kv[0])
                                      if kv[0] in L.LINK_TYPES
                                      else len(L.LINK_TYPES),
                                      kv[0]))[0][0]

    graph_edges = [{"a": k[0], "b": k[1], **v,
                    # A pair joined by a written link is extracted;
                    # a pair the build derived from shared sources /
                    # common neighbours alone is inferred.
                    "epistemic": "extracted" if v["direct"] else "inferred",
                    **({"types": dict(sorted(
                        pair_types[pair_key(k[0], k[1])].items())),
                        "relation": dominant_type(
                            pair_types[pair_key(k[0], k[1])])}
                       if pair_key(k[0], k[1]) in pair_types else {})}
                   for k, v in pair_signals.items()]
    graph_edges.sort(key=lambda e: (-e["weight"], e["a"], e["b"]))

    group_counts = Counter(display_group(pg) for pg in content_pages)
    type_groups = [{"key": key, "label": GROUP_LABEL[key], "singular": GROUP_SINGULAR[key],
                    "colour": GROUP_COLOUR[key], "count": group_counts[key]}
                   for key in GROUP_ORDER if group_counts.get(key)]

    # Community metrics: hub (by weighted degree), share of the wiki,
    # cohesion = share of members' link weight that stays inside the
    # cluster. Colours are the design system's community set
    # (lens-design-system.md §1.4, Okabe-Ito derived).
    COMMUNITY_COLOURS = ["#E69F00", "#56B4E9", "#009E73", "#F0E442",
                         "#0072B2", "#D55E00", "#CC79A7", "#999999"]
    internal_weight = Counter()
    for k, v in pair_signals.items():
        if communities[k[0]] == communities[k[1]]:
            internal_weight[communities[k[0]]] += v["weight"]
    comm_data = []
    for c, members in sorted(comm_members.items()):
        hub = max(members, key=lambda n: (wdegree[n], n))
        total_w = sum(wdegree[n] for n in members)
        cohesion = round(200.0 * internal_weight.get(c, 0.0) / total_w, 1) if total_w else 0.0
        comm_data.append({"id": c, "label": comm_label[c], "members": sorted(members),
                          "colour": COMMUNITY_COLOURS[c % len(COMMUNITY_COLOURS)],
                          "hub_id": hub, "hub_title": page_by_id[hub]["title"],
                          "cohesion": cohesion,
                          "share": round(100.0 * len(members) / max(1, len(node_ids)), 1)})

    # ---------------- Graph analytics (the build) ----------------
    # Co-citation (Graph Analysis pattern): two pages are co-cited
    # when a third page links to both; the panel shows the citing
    # sentences where the two links appear together. Link
    # prediction: Adamic-Adar over the direct-link graph for pairs
    # with no direct link — the "missing link?" lane. Both are
    # computed from the edge table; neither writes to any page.
    node_set = set(node_ids)
    citers = defaultdict(set)
    for e in edges:
        if e["kind"] in ("wikilink", "typed") and e["src"] in node_set \
                and e["dst"] in node_set:
            citers[e["dst"]].add(e["src"])
    sentence_pairs = []
    for pg in content_pages:
        for text, targets in pg["link_sentences"]:
            ids = sorted({route_by_stem.get(t)
                          or route_by_stem.get(Path(t).name)
                          for t in targets} - {None, pg["id"]})
            ids = [i for i in ids if i in node_set]
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    sentence_pairs.append((pg["id"], a, b, text))
    cocitations = L.cocitation_index(citers, sentence_pairs)
    nb_content = {n: {x for x in neighbours.get(n, set())
                      if x in node_set and x != n} for n in node_ids}
    missing_links = L.link_suggestions(nb_content, top_n=12)
    missing_items = [{
        "pages": [m["a"], m["b"]],
        "text": f"'{page_by_id[m['a']]['title']}' and "
                f"'{page_by_id[m['b']]['title']}' have no direct link "
                f"but share {m['common_neighbours']} neighbour(s) "
                f"(Adamic-Adar {m['adamic_adar']}). A computed "
                f"suggestion only — no page has been changed."}
        for m in missing_links[:8]]

    # Community methods, measured (the build): the rendered
    # clusters are the Louvain partition above. Label propagation —
    # the Graph Analysis plugin's algorithm, implemented in
    # lenslib — was run on the same weights and COLLAPSES on this
    # corpus (its largest community swallows the super-hubs'
    # neighbourhood whole), so it is reported here as a measurement,
    # not used for the rendered partition. If the corpus shape
    # changes, this line is where the comparison shows it.
    lp_comm = L.label_propagation(node_ids, weights)
    lp_sizes = Counter(lp_comm.values())
    community_methods = {
        "rendered": "louvain",
        "louvain": {"communities": len(comm_data),
                    "largest_share": round(
                        100.0 * max(len(c["members"])
                                    for c in comm_data) / len(node_ids), 1)},
        "label_propagation": {"communities": len(lp_sizes),
                              "largest_share": round(
                                  100.0 * max(lp_sizes.values())
                                  / len(node_ids), 1)},
    }

    # ---------------- Insights (all computed, none invented) ----------------
    surprising = []
    for e in graph_edges:
        if e["direct"] == 0 and communities[e["a"]] != communities[e["b"]] and e["weight"] >= 2.3:
            surprising.append({
                "a": e["a"], "b": e["b"], "pages": [e["a"], e["b"]],
                "text": f"'{page_by_id[e['a']]['title']}' and '{page_by_id[e['b']]['title']}' "
                        f"share {e['shared_sources']} source(s) and {e['common_neighbours']} "
                        f"common neighbour(s) but have no direct link."})
    gaps = [{"kind": "orphan", "id": o, "pages": [o],
             "text": f"'{page_by_id[o]['title']}' has no links in or out."} for o in orphans]
    for target, count in broken_targets.most_common():
        if count >= 2:
            gaps.append({"kind": "missing-page", "id": None, "pages": [],
                         "text": f"{count} pages link to [[{target}]], which has no page yet."})
    thin = [pg["id"] for pg in content_pages if pg["type"] == "source" and not pg["sources_fm"]]
    for t in thin:
        gaps.append({"kind": "thin-coverage", "id": t, "pages": [t],
                     "text": f"Source page '{page_by_id[t]['title']}' cites no raw source."})
    hub_items = []
    for rank, n in enumerate(sorted(node_ids, key=lambda n: (-wdegree[n], n))[:3]):
        if wdegree[n] <= 0:
            break
        lead = ("carries the most link weight of any page" if rank == 0
                else "is one of the strongest hubs")
        hub_items.append({"pages": [n],
                          "text": f"'{page_by_id[n]['title']}' {lead} — link weight "
                                  f"{'%g' % wdegree[n]} across {len(neighbours.get(n, set()))} "
                                  f"neighbour(s). The strongest hub is drawn largest."})
    bridge_items = []
    bridge_rank = []
    for n in node_ids:
        # Neighbours can include structural pages (index, log) that a
        # content page links to; they have no community, so skip them.
        nbr_comms = {communities[x] for x in neighbours.get(n, set())
                     if x in communities}
        foreign = nbr_comms - {communities[n]}
        if len(foreign) >= 1 and len(nbr_comms) >= 3:
            top_foreign = sorted((pair_signals[pair_key(n, x)]["weight"], x)
                                 for x in neighbours.get(n, set())
                                 if x in communities and communities[x] != communities[n])
            pages = [n] + [x for _w, x in top_foreign[-2:]][::-1] if top_foreign else [n]
            bridge_rank.append((len(nbr_comms), wdegree[n], n, len(foreign), pages))
    for _nc, _w, n, nforeign, pages in sorted(bridge_rank, key=lambda r: (-r[0], -r[1], r[2]))[:5]:
        bridge_items.append({"pages": pages,
                              "text": f"'{page_by_id[n]['title']}' is a bridge: its direct links "
                                      f"reach into {nforeign + 1} communities, tying its own "
                                      f"cluster to {nforeign} other(s)."})
    comm_items = [{"pages": [c["hub_id"]],
                   "text": f"{c['label']}: {len(c['members'])} pages ({c['share']}% of the wiki) "
                           f"around '{c['hub_title']}'; {c['cohesion']}% of its link weight "
                           f"stays inside the cluster."}
                  for c in comm_data]
    dispute_list = dispute_items(content_pages, route_by_stem, page_by_id)
    insight_categories = [
        {"key": "hubs", "label": "Top hubs", "count": len(hub_items), "items": hub_items},
        {"key": "bridges", "label": "Bridge pages", "count": len(bridge_items), "items": bridge_items},
        {"key": "communities", "label": "Community summaries", "count": len(comm_items), "items": comm_items},
        {"key": "surprising", "label": "Surprising connections", "count": len(surprising[:6]), "items": surprising[:6]},
        {"key": "missing-links", "label": "Missing link? (computed suggestions)", "count": len(missing_items), "items": missing_items},
        {"key": "gaps", "label": "Knowledge gaps", "count": len(gaps), "items": gaps},
        {"key": "disputes", "label": "Unresolved disputes", "count": len(dispute_list), "items": dispute_list},
    ]
    graph_stats = {"pages": len(node_ids),
                   "direct_links": sum(1 for v in pair_signals.values() if v["direct"]),
                   "relations": len(graph_edges),
                   "communities": len(comm_data)}
    graph = {"nodes": graph_nodes, "edges": graph_edges,
             "communities": comm_data,
             "community_colours": COMMUNITY_COLOURS,
             "type_groups": type_groups,
             "stats": graph_stats,
             "insights": {"categories": insight_categories,
                          "surprising": surprising[:6], "gaps": gaps},
             "cocitations": cocitations,
             "missing_links": missing_links,
             "tier": 1 if len(node_ids) <= 500 else (2 if len(node_ids) <= 5000 else 3),
             **stamp}
    dump_json(out / "data" / "graph.json", graph)
    dump_js(out / "data" / "graph.js", "LENS_GRAPH", graph)

    # ---------------- GRAPH_REPORT (the build) ----------------
    # The periodic graph report (Graphify pattern, Apache-2.0):
    # god nodes, communities, surprising connections, missing-link
    # suggestions, the typed-edge census, and suggested questions —
    # each question a fixed template over a computed fact, its
    # basis stated. Everything here is computed from the edge
    # table at build; nothing is generated prose, and nothing in
    # the report writes back to a wiki page.
    god_nodes = [{"id": n, "title": page_by_id[n]["title"],
                  "wdegree": wdegree[n],
                  "degree": len(neighbours.get(n, set()))}
                 for n in sorted(node_ids,
                                 key=lambda n: (-wdegree[n], n))[:10]
                 if wdegree[n] > 0]
    type_counts = Counter(e.get("type") or "mentions" for e in edges)
    suggested_questions = []
    if god_nodes:
        g0 = god_nodes[0]
        suggested_questions.append({
            "question": f"Why does '{g0['title']}' carry the most "
                        f"link weight in the wiki?",
            "basis": f"Highest weighted degree: {('%g' % g0['wdegree'])} "
                     f"across {g0['degree']} neighbour(s)."})
    if bridge_items:
        b0 = bridge_items[0]
        suggested_questions.append({
            "question": f"What holds the bridge page "
                        f"'{page_by_id[b0['pages'][0]]['title']}' "
                        f"together across its communities?",
            "basis": b0["text"]})
    if missing_links:
        m0 = missing_links[0]
        suggested_questions.append({
            "question": f"Should '{page_by_id[m0['a']]['title']}' and "
                        f"'{page_by_id[m0['b']]['title']}' be linked?",
            "basis": f"No direct link, but {m0['common_neighbours']} "
                     f"shared neighbour(s); Adamic-Adar "
                     f"{m0['adamic_adar']} (computed suggestion)."})
    if comm_data:
        big = max(comm_data, key=lambda c: (len(c["members"]), -c["id"]))
        suggested_questions.append({
            "question": f"What holds the '{big['label']}' cluster "
                        f"together?",
            "basis": f"Largest community: {len(big['members'])} pages, "
                     f"hub '{big['hub_title']}', cohesion "
                     f"{big['cohesion']}%."})
    if surprising:
        s0 = surprising[0]
        suggested_questions.append({
            "question": f"Why do '{page_by_id[s0['a']]['title']}' and "
                        f"'{page_by_id[s0['b']]['title']}' resemble "
                        f"each other without linking?",
            "basis": s0["text"]})
    graph_report = {
        "god_nodes": god_nodes,
        "communities": [{"id": c["id"], "label": c["label"],
                         "hub_id": c["hub_id"],
                         "hub_title": c["hub_title"],
                         "members": len(c["members"]),
                         "share": c["share"], "cohesion": c["cohesion"]}
                        for c in comm_data],
        "community_methods": community_methods,
        "surprising_connections": surprising[:6],
        "missing_links": missing_links,
        "typed_edges": {"counts": dict(sorted(type_counts.items())),
                        "total_edges": len(edges)},
        "suggested_questions": suggested_questions[:5],
        **stamp}
    dump_json(out / "data" / "graph-report.json", graph_report)
    dump_js(out / "data" / "graph-report.js", "LENS_GRAPH_REPORT",
            graph_report)

    # ---------------- Knowledge panel (type-grouped tree + Files) ----------------
    # The nashsu-style left panel: pages grouped by display group with
    # real counts, plus a Files view grouped by folder. The structural
    # pages (index, log) ride in a separate "Wiki record" group so the
    # type-group counts sum exactly to the graph's page count.
    knowledge_groups = []
    for key in GROUP_ORDER:
        members = sorted((pg for pg in content_pages if display_group(pg) == key),
                         key=lambda pg: pg["title"].lower())
        if not members:
            continue
        knowledge_groups.append({"key": key, "label": GROUP_LABEL[key],
                                 "colour": GROUP_COLOUR[key], "count": len(members),
                                 "pages": [{"id": pg["id"], "title": pg["title"],
                                            "updated": pg["updated"]} for pg in members]})
    record_pages = [{"id": pg["id"], "title": pg["title"]}
                    for pg in pages_raw if pg["id"] in ("index", "log")]
    section_label = {"wiki": "Root", "sources": "Sources", "entities": "Entities",
                     "concepts": "Concepts", "syntheses": "Syntheses", "queries": "Queries"}
    file_groups = []
    for sec in ["wiki", "sources", "entities", "concepts", "syntheses", "queries"]:
        members = sorted((pg for pg in pages_raw if pg["section"] == sec),
                         key=lambda pg: pg["title"].lower())
        if members:
            file_groups.append({"key": sec, "label": section_label[sec],
                                "count": len(members),
                                "pages": [{"id": pg["id"], "title": pg["title"]}
                                          for pg in members]})
    knowledge = {"groups": knowledge_groups,
                 "record": {"label": "Wiki record", "pages": record_pages},
                 "files": file_groups,
                 "total": len(content_pages), **stamp}
    dump_json(out / "data" / "knowledge.json", knowledge)
    dump_js(out / "data" / "knowledge.js", "LENS_KNOWLEDGE", knowledge)

    # ---------------- Search artefacts + parity ----------------
    # The reference implementation is loaded once, here: the wikilink
    # graph over the search corpus is built by the reference module
    # itself (build_link_graph), so graph construction is shared with
    # scripts/wiki_search.py rather than mirrored — only the ranking
    # math is mirrored (lenslib), and the parity check below covers
    # both BM25 and the hybrid ranking.
    spec = importlib.util.spec_from_file_location("wiki_search", repo / "scripts" / "wiki_search.py")
    ws = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ws)
    ref_docs = []
    for p in md_files:
        text = p.read_text(encoding="utf-8", errors="ignore")
        ref_docs.append((p, text))
    doc_adj = ws.build_link_graph(ref_docs)
    # Retrieval severance (item 20): the same list wiki_search.py
    # loads by default, handed to the mirror so the parity check
    # below exercises severance on both implementations.
    sev_path = repo / "evaluation" / "retrieval-severance.json"
    severance = None
    if sev_path.is_file():
        severance = json.loads(sev_path.read_text(encoding="utf-8"))
    postings_index = L.PostingsIndex(
        [{"key": str(p), "text": t,
          "structural": str(p.relative_to(repo)) in ("wiki/index.md", "wiki/log.md")}
         for p, t in ref_docs], severance=severance)
    # Surfaces (the surfaces build): the tag registry (item 59's vocabulary +
    # item 56's tag resolution) and the freshness signals (item
    # 46's records, rendered by the results UI — fold-in 2). Both
    # are computed once here and travel with the search artefacts.
    tag_registry = L.load_tag_registry(repo)
    fresh_signals = L.load_freshness_signals(repo)
    pg_by_path = {pg["path"]: pg for pg in pages_raw}
    doc_meta = []
    doc_sections = []
    for (p, t) in ref_docs:
        rel = str(p.relative_to(repo))
        pid = route_by_stem.get(p.stem)
        pg = page_by_id.get(pid) if pid else None
        raw_pg = pg_by_path.get(rel)
        fm = (raw_pg or {}).get("fm") or {}
        body = (raw_pg or {}).get("body") or L.parse_markdown_file(p)[1]
        doc_meta.append({"path": rel, "id": pid,
                         "title": pg["title"] if pg else p.stem,
                         "type": pg["type"] if pg else "page",
                         "section": (rel.split("/")[1]
                                     if rel.startswith("wiki/")
                                     and len(rel.split("/")) > 2
                                     else ""),
                         "facets": L.doc_facets(fm, tag_registry),
                         "fresh": L.freshness_line(L.freshness_record(
                             rel, t, signals=fresh_signals))})
        doc_sections.append(L.sectionize(body))
    search_docs = {"docs": doc_meta,
                   "texts": [t for _p, t in ref_docs],
                   "plain": [L.plain_text(L.parse_markdown_file(p)[1]) for p, _t in ref_docs],
                   "sections": doc_sections}
    dump_json(out / "data" / "search" / "docs.json", search_docs)
    dump_json(out / "data" / "search" / "postings.json", postings_index.to_json())
    idx_entries_client = []
    if idx_pg:
        link_re = re.compile(r"\[\[([^\]|#]+)")
        by_stem_single = {}
        for pg in pages_raw:
            by_stem_single.setdefault(Path(pg["path"]).stem, pg["id"])
        for line in idx_pg["text"].splitlines():
            targets = link_re.findall(line)
            pids = []
            for t in targets:
                cand = route_by_stem.get(t.strip()) or by_stem_single.get(Path(t.strip()).name)
                if cand:
                    pids.append(cand)
            if pids:
                idx_entries_client.append({"line": line.strip(), "page_ids": pids})
    dump_json(out / "data" / "search" / "index-entries.json", {"entries": idx_entries_client})
    exact = {"pages": [{"id": pg["id"], "title": pg["title"], "path": pg["path"]} for pg in pages_raw],
             "raw": [{"path": rp, "sha256": (manifest.get(rp) or {}).get("sha256"),
                      "hash_state": hash_state.get(rp, "missing")} for rp in raw_files]}
    dump_json(out / "data" / "search" / "exact.json", exact)
    dump_js(out / "data" / "search.js", "LENS_SEARCH",
            {"docs": doc_meta, "texts": search_docs["texts"], "plain": search_docs["plain"],
             "sections": doc_sections,
             "index": postings_index.to_json(), "index_entries": idx_entries_client,
             "exact": exact,
             "graph_adj": [doc_adj.get(i, []) for i in range(len(ref_docs))],
             # Phase-8 surfaces: the facet schema over the corpus
             # (item 56), the severance list for the browser
             # ranker (fold-in 1 — the same list handed to the
             # Python index above), and item 59's corpus
             # vocabulary + registry maps for suggestions and
             # the relaxation ladder.
             "facets": L.facet_schema([d["facets"] for d in doc_meta]),
             "severance": severance,
             "vocab": L.build_vocabulary(
                 [{"id": pg["id"], "title": pg["title"],
                   "headings": pg["headings"]} for pg in pages_raw],
                 tag_registry),
             "tags": {"resolve": tag_registry["resolve"],
                      "broader": tag_registry["broader"],
                      "concepts": tag_registry["concepts"]}})

    # Parity check vs scripts/wiki_search.py (FE-3 acceptance):
    # BM25 top-10 AND hybrid top-10 must be identical, query by query.
    parity = {"queries": [], "passed": True}
    test_queries = ["rights gate", "reserved seat fails closed",
                    "backup canonical home", "corpus page count",
                    "black box ledger", "decision register",
                    "standing questions", "citation lockfile",
                    "source grading", "retention schedule"]
    for q in test_queries:
        terms = L.tokenize(q)
        ref = ws.bm25_rank(terms, ref_docs)
        ref_top = [str(p.relative_to(repo)) for _s, p, _t in ref[:10]]
        mine = postings_index.rank(terms)
        my_top = [doc_meta[i]["path"] for _s, i in mine[:10]]
        ok = ref_top == my_top
        ref_h = ws.hybrid_rank(terms, ref_docs, doc_adj)
        ref_h_top = [str(p.relative_to(repo)) for _s, p, _t, _d in ref_h[:10]]
        my_h = postings_index.hybrid_rank(terms, doc_adj)
        my_h_top = [doc_meta[i]["path"] for _s, i, _d in my_h[:10]]
        h_ok = ref_h_top == my_h_top
        parity["queries"].append({"query": q, "match": ok, "hybrid_match": h_ok,
                                  "reference_top": ref_top[:3], "lens_top": my_top[:3],
                                  "reference_hybrid_top": ref_h_top[:3],
                                  "lens_hybrid_top": my_h_top[:3]})
        if not (ok and h_ok):
            parity["passed"] = False

    # ---------------- Timeline ----------------
    events = []
    log_pg = page_by_id.get("log")
    if log_pg:
        chunks = re.split(r"(?m)^## \[", log_pg["body"])
        for ch in chunks[1:]:
            m = re.match(r"(\d{4}-\d{2}-\d{2})\] (\w+) \| (.*?)\n(.*)", ch, re.S)
            if not m:
                continue
            date, kind, title, bodytxt = m.groups()
            stream = {"ingest": "Ingests", "decision": "Decisions", "query": "Queries",
                      "lint": "Lint"}.get(kind, "Wiki life")
            summary = L.plain_text(bodytxt)[:240]
            actor = None
            am = re.search(r"\((Owner|Agent|Reviewer|Collaborator)\)", title)
            if am:
                actor = am.group(1)
            events.append({"date": date, "kind": kind, "stream": stream,
                           "title": title.strip(), "summary": summary, "actor": actor,
                           "source": "wiki/log.md"})
    log_out = git(repo, "log", "-n", "80",
                  "--format=@@@%H%x09%cI%x09%s", "--numstat")
    cur = None
    for ln in log_out.splitlines():
        if ln.startswith("@@@"):
            parts = ln[3:].split("\t")
            if len(parts) == 3:
                cur = {"date": parts[1][:10], "kind": "commit", "stream": "Commits",
                       "title": parts[2], "sha": parts[0][:7], "files": 0,
                       "summary": "", "actor": None, "source": "git log"}
                events.append(cur)
        elif cur is not None and "\t" in ln:
            cur["files"] += 1
    events.sort(key=lambda e: e["date"], reverse=True)
    timeline = {"events": events,
                "caption": "This is the history of this wiki — its own log and git "
                           "commits. It is not a monitor of external repositories.",
                **stamp}
    dump_json(out / "data" / "timeline.json", timeline)

    # ---------------- Decisions ----------------
    decisions = []
    dec_pg = page_by_id.get("decision-register")
    refinements = ""
    if dec_pg:
        body = dec_pg["body"]
        items = list(re.finditer(r"(?m)^(\d+)\.\s+\*\*(.+?)\*\*", body, re.S))
        for j, m in enumerate(items):
            start = m.end()
            end = items[j + 1].start() if j + 1 < len(items) else len(body)
            tail = body[start:end]
            tail = tail.split("> [!note]")[0]
            detail = L.plain_text(tail)[:700]
            head_text = re.sub(r"\s+", " ", m.group(2)).strip()
            decisions.append({"n": int(m.group(1)), "title": head_text,
                                "status": "Decided", "decider": "Owner",
                                "date": dec_pg.get("updated") or dec_pg.get("created") or "",
                                "detail": detail, "page_id": "decision-register"})
        nm = re.search(r"> \[!note\] Refinements(.*?)(?=\n## |\Z)", body, re.S)
        if nm:
            refinements = L.plain_text(nm.group(1))[:900]
    open_items = []
    for pg in content_pages:
        if pg["type"] == "query":
            open_items.append({"id": pg["id"], "title": pg["title"],
                               "summary": (index_by_id.get(pg["id"], {}).get("summary")
                                           or pg["lede"] or ""),
                               "updated": pg["updated"]})
    decisions_data = {"decisions": decisions, "refinements": refinements,
                      "open_items": open_items, **stamp}
    dump_json(out / "data" / "decisions.json", decisions_data)

    # ---------------- Cards ----------------
    cat_by_type = {"source": "Sources", "entity": "Entities", "concept": "Concepts",
                   "synthesis": "Syntheses", "query": "Queries"}
    rel_weight = {}
    for k, v in pair_signals.items():
        a, b = k
        rel_weight.setdefault(a, []).append((v["weight"], b))
        rel_weight.setdefault(b, []).append((v["weight"], a))
    cards = []
    for pg in content_pages:
        idxe = index_by_id.get(pg["id"])
        summary = pg["lede"] or (idxe or {}).get("summary")
        no_summary = summary is None
        related = sorted(rel_weight.get(pg["id"], []), reverse=True)[:3]
        cards.append({"id": pg["id"], "title": pg["title"], "type": pg["type"],
                      "category": cat_by_type.get(pg["type"], "Syntheses"),
                      "summary": summary, "no_summary": no_summary,
                      "why": (idxe or {}).get("summary") if idxe and idxe.get("summary") != summary else None,
                      "updated": pg["updated"],
                      "source_path": pg["sources_fm"][0] if pg["sources_fm"] else None,
                      "related": [{"id": rid, "title": page_by_id[rid]["title"]} for _w, rid in related]})
    cards_data = {"cards": cards, **stamp}
    dump_json(out / "data" / "cards.json", cards_data)

    # ---------------- Black Box summary ----------------
    # Reads the REAL ledgers from wiki/access/ and verifies both
    # hash chains at build time, using the gateway's own ledger
    # code loaded by path (the same verify_chain the CLI runs).
    # The panel invents nothing: no ledger files -> not-started;
    # a failed chain -> broken at the exact entry; otherwise the
    # sessions, denials and watcher activity below are the
    # ledgers' own contents.
    bb_dir = wiki / "access"
    ledger_mod = None
    ledger_py = repo / "tools" / "gateway" / "gateway" / "ledger.py"
    if ledger_py.exists():
        _spec = importlib.util.spec_from_file_location("bb_ledger", ledger_py)
        ledger_mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(ledger_mod)

    def bb_read(glob_pattern):
        """-> (status, entries, first_bad_seq) over all matching files."""
        files = sorted(bb_dir.glob(glob_pattern)) if bb_dir.exists() else []
        entries, first_bad = [], None
        for f in files:
            if ledger_mod is not None:
                check = ledger_mod.verify_chain(f)
                if not check["ok"] and first_bad is None:
                    first_bad = check["bad_seq"]
                entries.extend(ledger_mod.read_entries(f))
            else:  # gateway code missing: parse but cannot verify
                for ln in f.read_text(encoding="utf-8").splitlines():
                    if ln.strip():
                        entries.append(json.loads(ln))
                if first_bad is None:
                    first_bad = -1
        if not files:
            return "not-started", entries, None
        if first_bad is not None:
            return "broken", entries, first_bad
        return "verified", entries, None

    gw_status, gw_entries, gw_bad = bb_read("black-box-*.jsonl")
    wt_status, wt_entries, wt_bad = bb_read("watcher-*.jsonl")

    sessions_by_id = {}
    for e in gw_entries:
        sid = e.get("session_id")
        if not sid or sid in ("genesis", "no-session"):
            continue
        s = sessions_by_id.setdefault(sid, {
            "session_id": sid, "actor": e.get("actor"),
            "started": e.get("ts"), "last": e.get("ts"),
            "actions": Counter(), "entries": 0})
        s["entries"] += 1
        s["last"] = e.get("ts")
        s["actions"][e.get("action")] += 1
    bb_sessions = []
    for s in sessions_by_id.values():
        s = dict(s)
        s["summary"] = " · ".join(
            f"{a} ×{n}" for a, n in sorted(s.pop("actions").items()))
        bb_sessions.append(s)
    bb_sessions.sort(key=lambda s: s["started"] or "", reverse=True)

    bb_denials = [{"seq": e.get("seq"), "ts": e.get("ts"),
                   "actor": e.get("actor"), "action": e.get("action"),
                   "tool": e.get("tool")}
                  for e in gw_entries if e.get("result") == "deny"]
    bb_unattributed = [{"seq": e.get("seq"), "ts": e.get("ts"),
                        "event_kind": e.get("event_kind"),
                        "path": e.get("path"),
                        "what": f"{e.get('event_kind') or ''} "
                                f"{e.get('path') or ''}".strip()}
                       for e in wt_entries if e.get("action") == "watcher_event"]
    bb_gaps = [{"seq": e.get("seq"),
                "restart_ts": e.get("restart_ts") or e.get("ts"),
                "last_heartbeat": e.get("last_heartbeat")}
               for e in wt_entries if e.get("action") == "watcher_gap"]

    bb_anchor = None
    anchor_files = sorted(bb_dir.glob("anchor-*.json")) if bb_dir.exists() else []
    if anchor_files:
        try:
            bb_anchor = json.loads(anchor_files[-1].read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            bb_anchor = None

    if gw_status == "verified":
        bb_note = (f"The gateway is ACTIVE and this panel is read from "
                   f"its ledger: {len(gw_entries)} entries, hash chain verified "
                   f"at build time. Sessions, denials and watcher activity "
                   f"below are the ledgers' own contents — nothing here is "
                   f"invented.")
        bb_chain_health = (
            f"Verified at build · {len(gw_entries)} entries · head "
            f"{(gw_entries[-1].get('entry_hash') or '')[:12]}…"
            + (f" · anchored at seq {bb_anchor.get('seq')}"
               if bb_anchor else " · not yet anchored"))
    elif gw_status == "broken":
        bb_note = (f"The gateway ledger's hash chain FAILED verification at "
                   f"entry {gw_bad}. Entries after that point are not "
                   f"trusted until this is resolved.")
        bb_chain_health = (f"BROKEN at entry {gw_bad} — entries after it "
                           f"are not trusted")
    else:
        bb_note = ("The Black Box ledger is empty because the gateway has not "
                   "recorded any entries yet. Nothing is recorded until it does — "
                   "this panel invents no activity. Git history (Timeline) is the "
                   "only activity record until the gateway starts the ledger.")
        bb_chain_health = "Not started — no gateway ledger exists yet"
    blackbox = {"generated_at": generated_at, "git_head": head,
                "gateway_ledger": {"status": gw_status,
                                   "entries_checked": len(gw_entries),
                                   "first_bad_seq": gw_bad,
                                   "head": (gw_entries[-1].get("entry_hash")
                                            if gw_entries else None),
                                   "last_anchor": bb_anchor},
                "watcher_ledger": {"status": wt_status,
                                   "entries_checked": len(wt_entries),
                                   "first_bad_seq": wt_bad,
                                   "last_anchor": None},
                "sessions": bb_sessions, "denials": bb_denials,
                "unattributed": bb_unattributed, "watcher_gaps": bb_gaps,
                "note": bb_note}
    dump_json(out / "data" / "blackbox-summary.json", blackbox)

    # ---------------- Briefing ----------------
    # "New since the last build" is written from the wiki's own log
    # (wiki/log.md) — the plain-English record the wiki keeps of
    # itself — not from raw git commit messages. Log entries are
    # headed `## [YYYY-MM-DD] <kind> | <Title>`; the kind word maps
    # to a plain verb (other kinds keep their own word). The log is
    # append-only, so newest = reverse file order; cap 8, matching
    # the old commit feed. Only if the log is missing or yields no
    # entries does the feed fall back to the git-log behaviour.
    KIND_VERB = {"ingest": "Added", "query": "Answered",
                 "lint": "Checked", "setup": "Set up"}
    log_feed = []
    log_md_path = wiki / "log.md"
    if log_md_path.exists():
        for m in re.finditer(r"(?m)^## \[(\d{4}-\d{2}-\d{2})\] (\w+) \| (.+?)\s*$",
                             log_md_path.read_text(encoding="utf-8")):
            f_date, f_kind, f_title = m.groups()
            f_verb = KIND_VERB.get(f_kind, f_kind.capitalize())
            log_feed.append(f"{f_verb} — {f_title} · {f_date}")
    if log_feed:
        deltas = list(reversed(log_feed))[:8]
        delta_label = "latest entries from the wiki log (wiki/log.md)"
    elif prev_stamp and prev_stamp.get("git_head") and prev_stamp["git_head"] != head:
        delta_raw = git(repo, "log", "--format=%s", f"{prev_stamp['git_head']}..{head}")
        delta_label = f"since the last build ({prev_stamp['git_head'][:7]})"
        deltas = [ln for ln in delta_raw.splitlines() if ln.strip()]
    elif prev_stamp and prev_stamp.get("git_head") == head:
        delta_raw = git(repo, "log", "--format=%s", "-n", "8")
        delta_label = "recent commits (nothing new since the last build)"
        deltas = [ln for ln in delta_raw.splitlines() if ln.strip()]
    else:
        delta_raw = git(repo, "log", "--format=%s", "-n", "8")
        delta_label = "recent commits (no earlier build stamp on this machine)"
        deltas = [ln for ln in delta_raw.splitlines() if ln.strip()]
    # "Waiting on you" = the owner's undecided ideas, read from the
    # "## Waiting for your call" section of wiki/ideas.md: one
    # plain-text item per bullet, markdown stripped, capped at 8.
    # Each item also carries "title": the bullet's bold lead (the
    # text inside the first **...**, stripped the same way) — the
    # exact string the Lens ruling buttons quote back through the
    # Ask door and scripts/wiki_ruling.py matches on ideas.md.
    # A bullet with no bold lead gets title "" and renders no
    # buttons.
    waiting_items = []
    ideas_md_path = wiki / "ideas.md"
    if ideas_md_path.exists():
        ideas_sec = re.search(r"(?ms)^## Waiting for your call\s*$(.*?)(?=^## |\Z)",
                              ideas_md_path.read_text(encoding="utf-8"))
        if ideas_sec:
            for ln in ideas_sec.group(1).splitlines():
                if not ln.startswith("- "):
                    continue
                raw_bullet = ln[2:]
                bold = re.search(r"\*\*(.+?)\*\*", raw_bullet)
                wtext = raw_bullet.replace("**", "").replace("`", "")
                wtext = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", wtext)
                wtext = re.sub(r"\s+", " ", wtext).strip()
                wtitle = ""
                if bold:
                    wtitle = bold.group(1).replace("**", "").replace("`", "")
                    wtitle = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", wtitle)
                    wtitle = re.sub(r"\s+", " ", wtitle).strip()
                if wtext:
                    waiting_items.append({"text": wtext, "title": wtitle})
                if len(waiting_items) >= 8:
                    break
    # ---------------- Standing queries (items 58 + 60) ----------------
    # The owner's saved searches (evaluation/standing-queries.jsonl,
    # filed via scripts/wiki_standing_queries.py — the Lens itself is
    # read-only) re-run against the fresh corpus with the same hybrid
    # ranking the search artefacts carry; the Briefing reports, per
    # query, the pages that are new or changed since the query's
    # last-looked stamp. Stamp discipline (lenslib): a stamp advances
    # only in a build that reports the query, and the advance is
    # written back to the register file — a visible working-tree
    # change the next commit carries, never a silent mutation. In
    # the CI pipeline the checkout is ephemeral, so the committed
    # register is what persists; local rebuilds advance the working
    # copy. A missing register is not an error: no watches filed yet.
    # (This is the one deliberate exception to "same HEAD => same
    # artefacts": the second build at one HEAD correctly reports
    # nothing new, because the first build advanced the stamps.)
    sq_records = L.load_standing_queries(repo)
    sq_lines, sq_records_out, sq_advanced = L.standing_queries_report(
        sq_records, postings_index, doc_adj, doc_meta,
        search_docs["texts"], generated_at, head_short)
    if sq_advanced:
        L.write_standing_queries(repo, sq_records_out)
    print(f"Standing queries: {len(sq_lines)} watched"
          + (f" ({len(sq_advanced)} stamp(s) advanced)"
             if sq_advanced else ""))

    lint_counts = {"broken_link_targets": len(broken_targets),
                   "broken_link_mentions": sum(broken_targets.values()),
                   "orphans": len(orphans),
                   "pages_missing_from_index": sum(
                       1 for pg in content_pages if pg["id"] not in index_by_id),
                   "pages_without_sources": len(thin)}
    type_counts = Counter(pg["type"] for pg in content_pages)
    briefing = {
        "generated_at": generated_at, "git_head": head, "git_head_short": head_short,
        "overview_lede": page_by_id["overview"]["lede"] if "overview" in page_by_id else None,
        "stats": {
            "pages": len(content_pages), "pages_by_type": dict(type_counts),
            "raw_files": manifest_status["files_on_disk"],
            "raw_bytes": manifest_status["total_bytes"],
            "decisions_decided": len(decisions),
            "log_entries": sum(1 for e in events if e["source"] == "wiki/log.md"),
            "edges": len(edges),
        },
        "deltas": deltas, "deltas_label": delta_label,
        "lint": lint_counts,
        "lint_items": {
            "orphans": [{"id": o, "title": page_by_id[o]["title"]} for o in orphans],
            "missing_pages": [{"target": t, "count": c} for t, c in broken_targets.most_common(8)],
            "thin": [{"id": t, "title": page_by_id[t]["title"]} for t in thin],
        },
        "waiting_on_you": waiting_items,
        "standing_queries": sq_lines,
        "health": {
            "canonical_anchor": f"Canonical repo HEAD {head_short} (the git remote is canonical; this build is from the local working copy at the same HEAD when pushed)",
            "manifest": (f"{manifest_status['verified']} of {manifest_status['files_in_manifest']} manifest-listed "
                         f"raw files verified against the provenance manifest · {len(drift)} changed · "
                         f"{len(manifest_status['not_in_manifest'])} not listed · "
                         f"manifest generated {manifest_status['generated_at']}"),
            "manifest_ok": len(drift) == 0,
            "blackbox_chain": bb_chain_health,
            "restore_drill": "No restore drill recorded.",
        },
        "latest_log": events[0] if events else None,
    }
    # ---------------- the surfaces build: state views + Briefing honesty ----------------
    # Items 63 + 65. All computations live in stateviews.py and run
    # over the same registers the rest of the build reads; nothing
    # here invents a number. A source that is missing degrades to a
    # stated note in the artefact, never to a fabricated value.
    today = now.date()
    due_map = L.freshness_due_map(repo, today)
    matrix_pages = [{
        "id": pg["id"], "path": pg["path"], "tags": pg["tags"],
        "status": str(pg["fm"].get("status") or ""),
        "superseded_by": str(pg["fm"].get("superseded_by") or ""),
        "attested_until": pages_json[pg["id"]]["attested_until"],
        "sources_count": pages_json[pg["id"]]["sources_count"],
    } for pg in content_pages]
    matrix = SV.evidence_matrix(matrix_pages, set(due_map.keys()))
    pages_by_path = {pg["path"]: {"fm": pg["fm"],
                                   "attested_until":
                                   pages_json[pg["id"]]["attested_until"]}
                     for pg in content_pages}
    id_by_path = {pg["path"]: pg["id"] for pg in pages_raw}
    lifecycle = SV.lifecycle_paths(repo, pages_by_path, id_by_path,
                                   due_map=due_map)
    state_data = {
        "generated_at": generated_at, "git_head_short": head_short,
        "matrix": matrix, "lifecycle": lifecycle,
        "argdown": argdown_census,
        "argdown_note": ("Argument maps compile from ```argdown fenced "
                         "blocks inside pages (own subset parser, "
                         "stateviews.parse_argdown). Pages carrying a "
                         "block are listed; zero blocks is a true count, "
                         "not a missing feature."),
    }
    # --- Item 65: honesty stack on the Briefing ---
    lane_series = SV.lint_lane_series(repo)
    for entry in lane_series["series"]:
        entry["points_svg"] = SV.sparkline_points(
            [p["value"] for p in entry["points"]], lane_series["shared_max"])
    try:
        _rspec = importlib.util.spec_from_file_location(
            "wiki_reverify", repo / "scripts" / "wiki_reverify.py")
        _rmod = importlib.util.module_from_spec(_rspec)
        _rspec.loader.exec_module(_rmod)
        schedule = _rmod.due_claims(today)
        forecast = SV.due_forecast(schedule, today)
    except Exception as exc:  # the schedule is canonical; say so plainly
        forecast = {"error": f"re-verification schedule unavailable: {exc}"}
        schedule = []
        print(f"PHASE8 NOTE: due forecast unavailable ({exc})")
    count_bands = [{"to": 1, "label": "≤1", "tone": "good"},
                   {"to": 3, "label": "2–3", "tone": "watch"},
                   {"to": 10 ** 9, "label": "4+", "tone": "bad"}]

    def _count_bullet(key, label, value, note, bands=None, scale=None):
        sc = scale if scale is not None else max(10, value)
        bnds = [dict(b) for b in (bands or count_bands)]
        bnds[-1]["to"] = sc
        return {"key": key, "label": label, "value": value, "unit": "count",
                "target": 0, "target_label": "target 0", "scale_max": sc,
                "bands": bnds, "note": note,
                "geometry": SV.bullet_geometry(value, 0, sc, bnds)}

    bullets = []
    if "error" not in forecast:
        bullets.append(_count_bullet(
            "reverify_due", "Claims past re-verification due",
            forecast["due_now_count"],
            "FSRS schedule (scripts/wiki_reverify.py). Every day a due "
            "claim sits unverified, the wiki asserts on stale checks."))
    open_cases = 0
    cases_path = repo / "evaluation" / "contradiction-cases.jsonl"
    if cases_path.exists():
        for ln in cases_path.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") == "case" and not str(
                    rec.get("status") or "").startswith("closed"):
                open_cases += 1
    bullets.append(_count_bullet(
        "open_cases", "Open contradiction Cases", open_cases,
        "evaluation/contradiction-cases.jsonl — a Case stays open until "
        "the contradiction is adjudicated on the record."))
    bullets.append(_count_bullet(
        "broken_links", "Broken link targets", lint_counts["broken_link_targets"],
        "Build lint over the compiled pages: wikilinks naming a page "
        "that does not exist."))
    bullets.append(_count_bullet(
        "thin_pages", "Source pages citing no raw source",
        lint_counts["pages_without_sources"],
        "Build lint: type=source pages with an empty sources list — "
        "summaries with nothing under them.",
        bands=[{"to": 2, "label": "≤2", "tone": "good"},
               {"to": 6, "label": "3–6", "tone": "watch"},
               {"to": 10 ** 9, "label": "7+", "tone": "bad"}],
        scale=max(12, lint_counts["pages_without_sources"])))
    eval_notes = []
    base_path = repo / "evaluation" / "extended-baseline.json"
    latest_path = repo / "evaluation" / "results" / "extended-latest.json"
    if base_path.exists() and latest_path.exists():
        base = json.loads(base_path.read_text(encoding="utf-8"))
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        eps = float(base.get("epsilon") or 0.02)
        gated = base.get("gated_metrics") or {}
        agg = (latest.get("aggregates") or {})

        def _rate_bullet(key, label, latest_v, base_v, note):
            bands = [{"to": round(base_v - 0.05, 4),
                      "label": "below gate −0.05", "tone": "bad"},
                     {"to": round(base_v - eps, 4),
                      "label": "within 0.05 of baseline", "tone": "watch"},
                     {"to": 1.0, "label": "at/above the gate band",
                      "tone": "good"}]
            return {"key": key, "label": label, "value": latest_v,
                    "unit": "rate", "target": base_v,
                    "target_label": f"baseline {base_v} (gate ε {eps})",
                    "scale_max": 1.0, "bands": bands, "note": note,
                    "geometry": SV.bullet_geometry(latest_v, base_v, 1.0,
                                                    bands)}

        if "mrr_must_cite" in gated and "mrr_must_cite" in agg:
            bullets.append(_rate_bullet(
                "eval_mrr", "Retrieval MRR (extended set)",
                agg["mrr_must_cite"], gated["mrr_must_cite"],
                "Latest extended eval vs its recorded baseline; the "
                "bullet's tick is the baseline, the band edge the "
                "gate's epsilon."))
        cov = (agg.get("citation_coverage") or {}).get("@10")
        if "citation_coverage@10" in gated and cov is not None:
            bullets.append(_rate_bullet(
                "eval_coverage", "Citation coverage @10 (extended set)",
                cov, gated["citation_coverage@10"],
                "Share of extended-set questions whose must-cite page "
                "is retrieved in the top 10."))
    else:
        eval_notes.append("Extended-eval bullet omitted: baseline or "
                          "latest results file missing at build.")
    honesty = {
        "admission_rule": SV.ADMISSION_RULE,
        "admission_verdicts": SV.ADMISSION_VERDICTS,
        "bullets": bullets,
        "bullet_notes": eval_notes + [
            "Locked-citation coverage (pages carrying ^[cite:] markers) "
            "has no declared target on record, so it gets no bullet: a "
            "bullet without a target is a bar wearing a costume. It "
            "joins when the owner sets the target."],
        "lane_series": lane_series,
        "forecast": forecast,
        "chart_gate": "Every chart in this build answers to "
                      "tools/lens/CHART-HONESTY.md (Cairo's rules as "
                      "checkable items); the Phase-8 smoke lane "
                      "mechanically checks the items that can be "
                      "checked over the artefact.",
    }
    briefing["honesty"] = honesty
    print(f"the surfaces build: matrix {matrix['total_pages']} pages × "
          f"{len(matrix['states'])} states · lifecycle "
          f"{lifecycle['record_count']} records · argdown "
          f"{argdown_census['blocks']} block(s) · bullets "
          f"{len(bullets)} · forecast due-now "
          f"{forecast.get('due_now_count', 'n/a')}")
    dump_json(out / "data" / "state.json", state_data)
    dump_json(out / "data" / "briefing.json", briefing)
    dump_js(out / "data" / "modes.js", "LENS_MODES",
            {"timeline": timeline, "decisions": decisions_data, "cards": cards_data,
             "briefing": briefing, "blackbox": blackbox, "state": state_data})

    # ---------------- Q&A history ----------------
    # The Ask-Agent question store lives at wiki/access/qa-2026.jsonl
    # (one JSON record per line). A missing file is not an error: it
    # simply means no questions have been asked yet, so the Lens
    # ships an empty history. Records are projected onto exactly the
    # public fields and sorted newest first (by asked_at descending).
    qa_path = wiki / "access" / "qa-2026.jsonl"
    qa_fields = ("id", "question", "asker", "asked_at", "answered_at",
                 "answer", "citations", "status", "mode", "question_type",
                 "abstained", "abstention_reason", "citation_details",
                 "trust_verdict", "sub_answers")
    qa_entries = []
    if qa_path.exists():
        for ln in qa_path.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            qa_entries.append({f: rec.get(f) for f in qa_fields})
    qa_entries.sort(key=lambda e: str(e.get("asked_at") or ""), reverse=True)
    qa_data = {"entries": qa_entries}
    dump_json(out / "data" / "qa.json", qa_data)
    dump_js(out / "data" / "qa.js", "LENS_QA", qa_data)
    qa_answered = sum(1 for e in qa_entries if e.get("status") == "answered")
    print(f"Q&A: {len(qa_entries)} records ({qa_answered} answered)")

    # ---------------- Staged proposals (diff view) ----------------
    # Wave-3 item C2: the gateway's staged proposals
    # (staging/proposed/<id>.md + <id>.json manifest pairs) rendered
    # as per-hunk diffs against the current pages, with the manifest
    # facts. Display only — decisions are made in chat and executed
    # through the gateway; this view carries no approve/reject
    # control, by the owner's standing design for the portal.
    # Build context: the CI pipeline checks out the whole repo
    # (the pipeline definition's checkout step) and runs rebuild.sh from
    # the root, so staging/ reaches this build whenever it is part
    # of the checked-out tree; where it is absent the artefact
    # degrades to an empty list with a note (lenslib).
    id_by_path = {pg["path"]: pg["id"] for pg in pages_raw}
    proposals_data = {**L.build_proposals_artefact(repo, id_by_path), **stamp}
    dump_json(out / "data" / "proposals.json", proposals_data)
    dump_js(out / "data" / "proposals.js", "LENS_PROPOSALS", proposals_data)
    print(f"Proposals: {len(proposals_data['proposals'])} staged draft(s), "
          f"{len(proposals_data['excluded'])} excluded, "
          f"{len(proposals_data['skipped'])} skipped")

    # ---------------- Trails (item 62a) ----------------
    # Authored reading paths over the typed-edge graph, defined
    # as data in tools/lens/trails.json and validated hop by hop
    # against the edge table above: a trail whose hop the graph
    # no longer carries is dropped with its reasons, never
    # rendered as curated.
    trails_data = {**L.build_trails_artefact(repo, page_by_id, edges),
                   **stamp}
    dump_json(out / "data" / "trails.json", trails_data)
    dump_js(out / "data" / "trails.js", "LENS_TRAILS", trails_data)
    print(f"Trails: {len(trails_data['trails'])} authored trail(s) "
          f"rendered, {len(trails_data['dropped'])} dropped")
    for dropped in trails_data["dropped"]:
        print(f"  TRAIL DROPPED {dropped['id']}: "
              + "; ".join(dropped["reasons"]))
    paired = sum(len(pj.get("cite_passages") or [])
                 for pj in pages_json.values())
    print(f"Citation pairings: {paired} claim<->passage pairs from "
          f"the lockfile across "
          f"{sum(1 for pj in pages_json.values() if pj.get('cite_passages'))} pages")

    # ---------------- Agent-readable exports (llms.txt) ----------------
    # Harvest item 9 (pattern: Pratiyush/llm-wiki, MIT): the wiki
    # should be legible to other agents by construction, not only
    # to this UI. llms.txt is the curated map (titles, one-line
    # summaries, links to the standalone page files); llms-full.txt
    # is the whole compiled layer as one text file.
    llms_lines = [
        "# WikiCitadel Lens",
        "",
        f"> The compiled layer of Owner's private LLM Wiki — every "
        f"content page, interlinked and source-cited. Built "
        f"{generated_at} from commit {head_short} by "
        f"{BUILDER_VERSION}. Access: owner only when deployed.",
        "",
        "## Pages",
        "",
    ]
    for pg in sorted(content_pages, key=lambda p: p["path"]):
        summary = (index_by_id.get(pg["id"], {}).get("summary")
                   or pg["lede"] or "")
        summary = " ".join(str(summary).split())
        llms_lines.append(f"- [{pg['title']}](data/pages/{pg['id']}.html)"
                          + (f": {summary}" if summary else ""))
    llms_lines += ["", "## Data artefacts", "",
                   "- [Graph (nodes, edges, communities, insights)]"
                   "(data/graph.json)",
                   "- [Edge table (one row per relation, epistemic-tagged)]"
                   "(data/edges.jsonl)",
                   "- [Graph report (god nodes, communities, surprising "
                   "connections, missing-link suggestions)]"
                   "(data/graph-report.json)",
                   "- [Search documents + postings](data/search/docs.json)",
                   "- [Q&A history](data/qa.json)",
                   "- [Staged proposals with per-hunk diffs, display "
                   "only](data/proposals.json)",
                   "- [Authored reading trails over the typed-edge "
                   "graph](data/trails.json)",
                   "- [Build manifest (SHA-256 of every emitted file)]"
                   "(build-manifest.json)",
                   "", "## Raw sources", ""]
    for rp in raw_files:
        llms_lines.append(f"- {rp} ({hash_state.get(rp, 'missing')})")
    briefing_md = build_briefing(
        repo, query_pages,
        (page_by_id.get("current-state") or {}).get("id"))
    llms_text = briefing_md + "\n\n" + "\n".join(llms_lines) + "\n"
    (out / "llms.txt").write_text(llms_text, encoding="utf-8")

    full_parts = [
        f"WikiCitadel — full compiled layer\n"
        f"Built {generated_at} from commit {head_short} · "
        f"{len(content_pages)} content pages\n"
    ]
    for pg in sorted(content_pages, key=lambda p: p["path"]):
        full_parts.append(
            "\n" + "=" * 78 + f"\n# {pg['title']}\n"
            f"Path: {pg['path']} · Type: {pg['type']} · "
            f"Updated: {pg['updated']}\n" + "=" * 78 + "\n\n"
            + pg["body"].strip() + "\n")
    full_text = briefing_md + "\n\n" + "".join(full_parts)
    (out / "llms-full.txt").write_text(full_text, encoding="utf-8")
    print(f"Exports: llms.txt ({len(llms_text.splitlines())} lines), "
          f"llms-full.txt ({len(full_text)} chars)")

    # ---------------- Auth wall (Azure Static Web Apps config) ----------------
    # Emitted at the site root on every build so the deployed portal is
    # locked by default: everything requires the "owner" role, /login and
    # 401s redirect to the platform AAD sign-in, and /.auth/* stays
    # reachable because the platform handles it before these routes.
    # Until the owner accepts the role invitation with the hosting
    # platform, the wall
    # shows a sign-in to everyone — that is the intended state.
    # Route order matters: /api/ask is owner-only (the Lens door —
    # only the signed-in owner may ask Agent a question through the
    # portal). The /api/health and /api/questions service paths are reachable
    # anonymously at the routing layer ONLY because the function
    # itself enforces a bearer service token (x-ask-token) with a
    # 403 — no unauthenticated operation exists; route rules cannot
    # express token auth, so the anonymous allowance here is not an
    # opening: the function rejects every request without the token.
    swa_config = {
        "routes": [
            {"route": "/login", "redirect": "/.auth/login/aad", "statusCode": 302},
            {"route": "/api/ask", "allowedRoles": ["owner"]},
            {"route": "/api/health", "allowedRoles": ["anonymous"], "methods": ["GET"]},
            {"route": "/api/questions", "allowedRoles": ["anonymous"], "methods": ["GET", "POST"]},
            {"route": "/api/questions/*", "allowedRoles": ["anonymous"], "methods": ["POST"]},
            {"route": "/*", "allowedRoles": ["owner"]},
        ],
        "responseOverrides": {
            "401": {"redirect": "/.auth/login/aad", "statusCode": 302},
        },
        # Audit L1: the site is fully self-contained (no external
        # scripts, styles, fonts or images), so the headers can be
        # strict. style-src keeps 'unsafe-inline' because the SPA
        # sets style attributes from its own templates; scripts,
        # however, are 'self' only — no inline script exists.
        "globalHeaders": {
            "Cache-Control": "no-cache",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'self'; script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; font-src 'self'; "
                "connect-src 'self'; frame-ancestors 'none'; "
                "base-uri 'self'; form-action 'self'"),
        },
    }
    (out / "staticwebapp.config.json").write_text(
        json.dumps(swa_config, indent=2) + "\n", encoding="utf-8")

    # ---------------- Shell ----------------
    shell = (assets / "shell.html").read_text(encoding="utf-8")
    shell = shell.replace("{{GENERATED_AT}}", generated_at)
    shell = shell.replace("{{HEAD_SHORT}}", head_short)
    shell = shell.replace("{{HEAD}}", head)
    (out / "index.html").write_text(shell, encoding="utf-8")
    for name in ("lens.css", "app.js"):
        (out / name).write_text((assets / name).read_text(encoding="utf-8"), encoding="utf-8")
    # Self-hosted fonts (Fraunces / Inter / IBM Plex Mono, OFL): the
    # @font-face rules in lens.css reference fonts/<file>, so the
    # whole directory — WOFF2 files and their licences — ships.
    fonts_src = assets / "fonts"
    if fonts_src.is_dir():
        fonts_out = out / "fonts"
        fonts_out.mkdir(exist_ok=True)
        for f in sorted(fonts_src.iterdir()):
            if f.is_file():
                (fonts_out / f.name).write_bytes(f.read_bytes())
    stamp_file.write_text(json.dumps(stamp, indent=1), encoding="utf-8")

    # ---------------- Build manifest (hashed) ----------------
    # Emitted LAST: a SHA-256 over every other emitted file, so a
    # consumer can verify the build it is reading is the build the
    # stamp claims (harvest item 9). The manifest never lists
    # itself.
    manifest_files = {}
    for f in sorted(out.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(out))
        if rel == "build-manifest.json":
            continue
        manifest_files[rel] = {"sha256": L.sha256_file(f),
                               "bytes": f.stat().st_size}
    dump_json(out / "build-manifest.json",
              {"builder": BUILDER_VERSION, "git_head": head,
               "git_head_short": head_short, "generated_at": generated_at,
               "file_count": len(manifest_files), "files": manifest_files})
    print(f"Build manifest: {len(manifest_files)} files hashed")

    print(f"Lens build complete: {len(content_pages)} content pages, "
          f"{len(edges)} edges, {len(graph_nodes)} graph nodes, "
          f"search corpus {postings_index.n} docs.")
    print(f"HEAD {head_short} · stamp {generated_at}")
    print(f"Manifest: {manifest_status['verified']} verified, {len(drift)} changed, "
          f"{len(manifest_status['not_in_manifest'])} not in manifest.")
    print(f"Black Box: gateway {gw_status} ({len(gw_entries)} entries), "
          f"watcher {wt_status} ({len(wt_entries)} entries), "
          f"{len(bb_sessions)} sessions, {len(bb_denials)} denials.")
    print(f"Lint-at-build: {lint_counts}")
    print(f"Parity vs scripts/wiki_search.py: {'PASS' if parity['passed'] else 'FAIL'} "
          f"(BM25 {sum(1 for q in parity['queries'] if q['match'])}/{len(parity['queries'])}, "
          f"hybrid {sum(1 for q in parity['queries'] if q['hybrid_match'])}/{len(parity['queries'])} "
          f"queries identical top-10)")
    for q in parity["queries"]:
        if not q["match"]:
            print(f"  MISMATCH {q['query']!r}: ref={q['reference_top']} lens={q['lens_top']}")
        if not q["hybrid_match"]:
            print(f"  HYBRID MISMATCH {q['query']!r}: ref={q['reference_hybrid_top']} "
                  f"lens={q['lens_hybrid_top']}")
    return 0 if parity["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
