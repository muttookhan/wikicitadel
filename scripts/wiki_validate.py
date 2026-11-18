#!/usr/bin/env python3
"""Typed-frontmatter validation for the LLM Wiki (the build machinery).

SIGN's lesson from the gist comment thread: prose schemas are
unenforced instructions. This validator makes the AGENTS.md page
conventions mechanical. For every content page under wiki/ it
checks:

  - frontmatter present, with title / type / created / updated /
    sources / tags all present (missing key = ERROR; an explicitly
    empty sources or tags list = WARNING — the field exists but
    cites nothing);
  - type in the allowed set (source | entity | concept |
    synthesis | query);
  - created / updated parse as ISO dates, updated not before
    created;
  - every sources entry resolves: a path entry must exist on disk
    (and should live under raw/); a bare slug must resolve against
    raw/sources/ by exact token-set match on the file stem (the
    wiki_stale.py convention) — unresolvable = ERROR, ambiguous
    (several files share the token set) = WARNING;
  - every [[wikilink]] in the body resolves to an existing page
    (by stem or by repo-relative path, the llm_wiki.py lint
    convention) — broken = ERROR; a bare-stem link whose stem is
    shared by several pages = WARNING (ambiguous target);
  - every claim-level citation marker ^[cite: <path>#L<a>-L<b>]
    (the AGENTS.md convention, adapted from
    atomicstrata/llm-wiki-compiler, MIT) resolves: the cited file
    exists and the line range lies inside it — either failure is
    an ERROR; a marker-shaped string that does not parse is an
    ERROR too (a silently-wrong citation is worse than none);
  - a present-tense quantitative claim (quantity + explicit
    currency marker in one sentence) on a page with no `as_of`
    frontmatter is a WARNING (the claim lifecycle
    itself lives in scripts/wiki_claims.py);
  - the gateway lifecycle profile (tools/gateway/profiles/
    wiki-default.json) is applied with the same
    definition the gateway enforces on its write path: declared
    page types + their required fields. The shipped profile is
    warn-legacy, so violations are WARNINGs; they become ERRORs
    only if the Owner flips the profile to enforce.

Structural files (wiki/index.md, wiki/log.md) are catalog/log, not
typed pages, and are reported as STRUCTURAL instead of failing
field checks — the same exemption llm_wiki.py lint applies.

COVERAGE (context-engine standard, enforced mechanically): every
file in the raw/ provenance manifest must be ACCOUNTED FOR by the
wiki layer — cited in at least one page's sources, or exempted
with a reason in the exemptions section of
raw/sources/tools-record.md (entries there are
backticked repo-relative paths, or directory prefixes ending in
"/"). Anything else is UNACCOUNTED and counts as an ERROR:
preserved is not known until compiled.

Usage:  python3 scripts/wiki_validate.py
Exit code: 0 when there are no errors, 1 otherwise (warnings and
structural notes never fail the run). Stdlib only.
"""
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
RAW = ROOT / "raw"
RAW_SOURCES = RAW / "sources"
MANIFEST_PATH = RAW_SOURCES / "provenance-manifest.json"
NOTE_PATH = RAW_SOURCES / "tools-record.md"

ALLOWED_TYPES = {"source", "entity", "concept", "synthesis", "query"}
REQUIRED_FIELDS = ("title", "type", "created", "updated", "sources", "tags")
STRUCTURAL = {"wiki/index.md", "wiki/log.md"}

LINK_RE = re.compile(r"\[\[([^\]|#]+)")
FENCE_RE = re.compile(r"```.*?```", re.S)
CODESPAN_RE = re.compile(r"`[^`\n]*`")
CITE_RE = re.compile(r"\^\[cite:\s*([^\]#\s]+)#L(\d+)(?:-L?(\d+))?\s*\]")
CITE_LOOSE_RE = re.compile(r"\^\[cite:[^\]]*\]")
# Volatile-claim lint (helicerat/llm-wiki-loop,
# MIT): a sentence carrying a quantity AND an explicit present-
# tense currency marker, on a page with no as_of, is a claim
# about a moving number stated as current fact. Calibrated on
# this corpus: broader forms (any number+unit) flag 21 pages of
# properly dated historical records — false positives; the
# currency-marker requirement is what makes it a volatility
# signal rather than a numeracy signal.
VOL_NUM_RE = re.compile(
    r"\b\d[\d,]*(\.\d+)?\s*(%|percent|tests?|files?|units?|claims?|"
    r"pages?|records?|lines|items)\b", re.I)
VOL_CUR_RE = re.compile(
    r"\b(currently|at present|as of now|now stands|stands at|"
    r"as of today)\b", re.I)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def strip_code(text: str) -> str:
    """Remove fenced blocks and inline code spans.

    Link-shaped text inside code is literal syntax, not a link —
    Obsidian treats it the same way. (llm_wiki.py lint does not
    strip code and false-positives on such examples.)
    """
    return CODESPAN_RE.sub("", FENCE_RE.sub("", text))


# ---------------------------------------------------------------- parser

def _split_flow(inner: str):
    """Split a flow-list body on top-level commas (quote-aware)."""
    parts, cur, quote = [], [], None
    for ch in inner:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch == ",":
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return [p.strip().strip("\"'") for p in parts if p.strip()]


def parse_frontmatter(text: str):
    """Parse the YAML-subset frontmatter used by this wiki.

    Returns (fields, body) where list-valued keys are lists and
    scalars are strings, or (None, text) when there is no
    frontmatter block. Handles flow lists (quoted or bare), block
    lists at any indent, and plain scalars.
    """
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None, text
    fields = {}
    lines = m.group(1).splitlines()
    i = 0
    while i < len(lines):
        km = re.match(r"^([A-Za-z_]+):\s*(.*)$", lines[i])
        if not km:
            i += 1
            continue
        name, val = km.group(1), km.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            fields[name] = _split_flow(val[1:-1])
        elif val.startswith("- "):
            fields[name] = [val[2:].strip().strip("\"'")]
        elif val:
            fields[name] = val.strip("\"'")
        else:
            items = []
            j = i + 1
            while j < len(lines) and re.match(r"^\s*-\s+", lines[j]):
                items.append(
                    re.sub(r"^\s*-\s+", "", lines[j]).strip().strip("\"'"))
                j += 1
            if items:
                fields[name] = items
                i = j - 1
            else:
                fields[name] = None
        i += 1
    return fields, text[m.end():]


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def parse_date(value):
    """ISO date or datetime -> date; None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip()
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
    except ValueError:
        return None


# ------------------------------------------------------------- resolvers

def slug_tokens(s: str):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


class Resolvers:
    def __init__(self):
        # slug token-set -> [repo-relative raw file paths]
        self.slug_map = {}
        if RAW_SOURCES.exists():
            for p in sorted(RAW_SOURCES.rglob("*")):
                if p.is_file():
                    key = frozenset(slug_tokens(p.stem))
                    self.slug_map.setdefault(key, []).append(
                        p.relative_to(ROOT).as_posix())
        # wikilink targets: stem -> [pages], path-no-suffix -> page
        self.pages = sorted(p for p in WIKI.rglob("*.md") if p.is_file())
        self.by_stem = {}
        self.by_path = {}
        for p in self.pages:
            self.by_stem.setdefault(p.stem, []).append(p)
            self.by_path[str(p.relative_to(ROOT).with_suffix(""))] = p

    def resolve_source(self, entry: str):
        """-> (status, resolved_rel_path or None, detail).

        status: ok | missing | unresolvable | ambiguous | external
        """
        if entry.startswith(("http://", "https://")):
            return "external", None, "external pointer citation"
        if "/" in entry:
            rel = Path(entry).as_posix()
            if (ROOT / rel).exists():
                if not rel.startswith("raw/"):
                    return "ok", rel, "resolves, but outside raw/"
                return "ok", rel, ""
            return "missing", rel, "cited path not on disk"
        matches = self.slug_map.get(frozenset(slug_tokens(entry)), [])
        if not matches:
            return "unresolvable", None, "no raw file matches this slug"
        if len(matches) > 1:
            return "ambiguous", matches[0], \
                f"slug matches {len(matches)} raw files: {', '.join(matches)}"
        return "ok", matches[0], ""

    def resolve_link(self, target: str):
        """-> (status, detail): ok | broken | ambiguous."""
        cand = self.by_path.get(target) or self.by_stem.get(target) \
            or self.by_stem.get(Path(target).name)
        if not cand:
            return "broken", ""
        pages = cand if isinstance(cand, list) else [cand]
        if len(pages) > 1 and "/" not in target:
            return "ambiguous", \
                f"stem shared by {len(pages)} pages: " + ", ".join(
                    str(p.relative_to(ROOT)) for p in pages)
        return "ok", ""


# -------------------------------------------------------------- coverage

def load_exemptions():
    """Parse the exemptions section of the engineering note.

    Returns (rules, note_found): rules are (entry, is_prefix) pairs
    from backticked items under the 'Coverage exemptions' heading.
    """
    if not NOTE_PATH.exists():
        return [], False
    text = NOTE_PATH.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"^##\s+.*Coverage exemptions.*$", text, re.M)
    if not m:
        return [], True
    section = text[m.end():]
    nxt = re.search(r"^##\s+", section, re.M)
    if nxt:
        section = section[:nxt.start()]
    rules = []
    for line in section.splitlines():
        for item in re.findall(r"`([^`]+)`", line):
            item = item.strip()
            if item.startswith("raw/"):
                rules.append((item, item.endswith("/")))
    return rules, True


def exemption_for(rel: str, rules):
    for item, is_prefix in rules:
        if is_prefix and rel.startswith(item):
            return item
        if not is_prefix and rel == item:
            return item
    return None


# ------------------------------------------------------- claim citations

_line_counts = {}


def line_count(rel: str) -> int:
    if rel not in _line_counts:
        try:
            _line_counts[rel] = len(
                (ROOT / rel).read_text(encoding="utf-8",
                                       errors="ignore").splitlines())
        except OSError:
            _line_counts[rel] = -1
    return _line_counts[rel]


def check_claim_citations(rel_page: str, body: str, errors):
    """Resolve every ^[cite: path#L<a>-L<b>] marker in a page body.
    Returns how many markers were checked. Failures are appended
    to `errors` (kind 'claim citation')."""
    text = strip_code(body)
    checked = 0
    for m in CITE_LOOSE_RE.finditer(text):
        raw_marker = m.group(0)
        cm = CITE_RE.fullmatch(raw_marker)
        if cm is None:
            errors.append((rel_page, "claim citation",
                           f"malformed marker {raw_marker!r} — expected "
                           "^[cite: <path>#L<start>-L<end>]"))
            checked += 1
            continue
        checked += 1
        path, start_s, end_s = cm.group(1), cm.group(2), cm.group(3)
        start = int(start_s)
        end = int(end_s) if end_s else start
        rel = Path(path).as_posix()
        if ".." in Path(rel).parts or rel.startswith("/"):
            errors.append((rel_page, "claim citation",
                           f"{raw_marker}: path escapes the repo"))
            continue
        if not (ROOT / rel).is_file():
            errors.append((rel_page, "claim citation",
                           f"{raw_marker}: cited file not on disk"))
            continue
        n = line_count(rel)
        if start < 1 or end < start or end > n:
            errors.append((rel_page, "claim citation",
                           f"{raw_marker}: line range {start}-{end} "
                           f"outside {rel} (1-{n})"))
    return checked


# ------------------------------------------------------- two axes
# Two-axis discipline (idea from
# kelly-create/LLM-WIKI-skills — no license, re-implemented):
# `status` is LIFECYCLE, `confidence` is EVIDENCE STRENGTH, and
# their vocabularies are disjoint. A value from one axis written
# on the other ("status: high", "confidence: published") is a
# conflation — a warning here, because the axes only mean anything
# while they cannot be confused. Vocabularies live in the gateway
# profile's "axes" block (one definition); these are the fallbacks.

DEFAULT_AXES = {
    "status": {"draft", "verified", "published", "archived",
               "active", "needs-verification", "superseded",
               "deprecated"},
    "confidence": {"observed", "inferred", "low", "medium", "high"},
}


def axis_conflation(fields, axes=None):
    """-> [detail, ...] for status/confidence values that belong
    to the OTHER axis. Exact single-value matches only: a page
    listing the vocabulary itself is documentation, not a claim."""
    axes = axes or DEFAULT_AXES
    status_vocab = {str(v).lower() for v in axes.get("status") or []}
    conf_vocab = {str(v).lower() for v in axes.get("confidence") or []}
    out = []
    status = fields.get("status")
    if isinstance(status, str) and status.strip().lower() in conf_vocab:
        out.append(f"status {status!r} is a CONFIDENCE value — status "
                   "is the lifecycle axis (draft/verified/published/"
                   "archived); evidence strength belongs in confidence")
    conf = fields.get("confidence")
    if isinstance(conf, str) and conf.strip().lower() in status_vocab:
        out.append(f"confidence {conf!r} is a LIFECYCLE value — "
                   "confidence is the evidence axis (observed/inferred/"
                   "low/medium/high); lifecycle belongs in status")
    return out


# ---------------------------------------------------- lifecycle profile

def load_lifecycle_profile():
    """The gateway's lifecycle profile , loaded by
    path so validator and gateway apply ONE definition. Returns
    (profile, module) or (None, None) when absent/malformed —
    machinery inert, never a validation failure by itself."""
    import importlib.util
    mod_path = ROOT / "tools" / "gateway" / "gateway" / "profile.py"
    prof_path = ROOT / "tools" / "gateway" / "profiles" / "wiki-default.json"
    if not mod_path.is_file() or not prof_path.is_file():
        return None, None
    try:
        spec = importlib.util.spec_from_file_location("gw_profile", mod_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.load_profile(prof_path), mod
    except Exception:
        return None, None


# --------------------------------------------------------------- secrets

SECRET_NAME_PATTERNS = ("*.env", ".env*", "*.pem", "*.key", "*.p12",
                        "*.pfx", "*registry*.json", "*token*", "*secret*",
                        "credentials*")
SECRET_VALUE_RES = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\bwct1\.[a-z0-9-]+\.[A-Za-z0-9_\-]{16,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{24,}"),
]


def secret_scan():
    """Audit M4: a secret-shaped file in the tree is one `git add`
    away from living in history (and in the nightly Drive zip)
    forever. Filenames are checked across the whole tree; values
    are checked everywhere except raw/ — verbatim source material
    is swept at ingest, but the layers this repo writes (wiki/,
    tools/, scripts/, staging/, root) must never carry a live
    credential value. Returns [(rel_path, why), ...].
    """
    import fnmatch
    hits = []
    for p in sorted(ROOT.rglob("*")):
        if ".git" in p.parts or "__pycache__" in p.parts or not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        if any(fnmatch.fnmatch(p.name.lower(), pat)
               for pat in SECRET_NAME_PATTERNS):
            hits.append((rel, "secret-shaped filename — must not be "
                              "committed; move it to the gateway state "
                              "dir or a secure vault"))
            continue
        if rel.startswith("raw/"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for rx in SECRET_VALUE_RES:
            if rx.search(text):
                hits.append((rel, "secret-shaped value "
                                  f"({rx.pattern[:28]}…)"))
                break
    return hits


# ------------------------------------------------------------------ main

def main(argv):
    res = Resolvers()
    profile, _profile_mod = load_lifecycle_profile()
    pages = res.pages
    errors = []    # (page_rel, kind, detail)
    warnings = []  # (page_rel, kind, detail)
    grandfathered = []  # (page_rel, violation) — aggregated below
    n_clean = 0
    n_structural = 0
    n_cites = 0
    cited = set()  # repo-relative raw paths cited by >= 1 page

    # Duplicate stems are a wiki-level ambiguity defect: report once.
    dup_stems = {s: ps for s, ps in res.by_stem.items() if len(ps) > 1}
    for stem, ps in sorted(dup_stems.items()):
        warnings.append(("(wiki)", "duplicate page stem",
                         f"'{stem}' is shared by " + ", ".join(
                             str(p.relative_to(ROOT)) for p in ps)))

    for p in pages:
        rel_page = p.relative_to(ROOT).as_posix()
        if rel_page in STRUCTURAL:
            n_structural += 1
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        fields, body = parse_frontmatter(text)
        page_errors = 0
        if fields is None:
            errors.append((rel_page, "missing frontmatter",
                           "no --- frontmatter block"))
            continue

        for name in REQUIRED_FIELDS:
            if name not in fields or fields[name] is None or fields[name] == "":
                errors.append((rel_page, "missing field",
                               f"required field '{name}' is absent or empty"))
                page_errors += 1
        if page_errors:
            # Field-level checks below assume presence; skip deeper
            # checks on a page whose header is incomplete rather
            # than cascade secondary errors.
            if "sources" in fields:
                for entry in as_list(fields.get("sources")):
                    st, resolved, _d = res.resolve_source(entry)
                    if resolved:
                        cited.add(resolved)
            continue

        ptype = fields["type"]
        if isinstance(ptype, list) or ptype not in ALLOWED_TYPES:
            errors.append((rel_page, "bad type",
                           f"type {ptype!r} not in {sorted(ALLOWED_TYPES)}"))
        created = parse_date(fields["created"])
        updated = parse_date(fields["updated"])
        for name, val, parsed in (("created", fields["created"], created),
                                  ("updated", fields["updated"], updated)):
            if parsed is None:
                errors.append((rel_page, "bad date",
                               f"{name} {val!r} is not an ISO date"))
        if created and updated and updated < created:
            warnings.append((rel_page, "date order",
                             f"updated {updated} is before created {created}"))

        sources = as_list(fields.get("sources"))
        if not sources:
            warnings.append((rel_page, "no sources cited",
                             "sources list is empty"))
        for entry in sources:
            st, resolved, detail = res.resolve_source(entry)
            if resolved:
                cited.add(resolved)
            if st == "missing":
                errors.append((rel_page, "source not on disk",
                               f"{entry} ({detail})"))
            elif st == "unresolvable":
                errors.append((rel_page, "unresolvable source slug",
                               f"{entry} ({detail})"))
            elif st == "ambiguous":
                warnings.append((rel_page, "ambiguous source slug",
                                 f"{entry} -> {detail}"))
            elif st == "ok" and detail:
                warnings.append((rel_page, "source outside raw/",
                                 f"{entry} ({detail})"))

        if profile is not None:
            for v in _profile_mod.violations_for(profile, fields):
                # Versioned-schema severities
                # (pyrite pattern): a since-versioned field missing
                # from a NEW-schema page is an error in any mode;
                # missing from a LEGACY page it is grandfathered —
                # collected here and reported once, in aggregate,
                # below, so forty legacy pages do not become forty
                # warning lines.
                if v.get("rule") == "schema-grandfathered":
                    grandfathered.append((rel_page, v))
                elif v.get("severity") == "error":
                    errors.append((rel_page, "lifecycle profile",
                                   f"[{v['rule']}] {v['detail']}"))
                elif v.get("severity") == "warn":
                    warnings.append((rel_page, "lifecycle profile",
                                     f"[{v['rule']}] {v['detail']}"))
                else:
                    sink = errors if profile.get("mode") == "enforce" else warnings
                    sink.append((rel_page, "lifecycle profile",
                                 f"[{v['rule']}] {v['detail']}"))

        axes = (profile or {}).get("axes") or DEFAULT_AXES
        for detail in axis_conflation(fields, axes):
            warnings.append((rel_page, "axis conflation", detail))

        REL_FAMILY = {"supersedes", "superseded_by",
                      "replaced_by", "cites", "cited_by",
                      "corrects", "corrected_by", "extends",
                      "extended_by", "contradicts",
                      "derives_from", "derived_from", "based_on",
                      "part_of", "has_part", "see_also", "related"}
        REL_MAPPED = {"supersedes", "superseded_by",
                      "replaced_by", "cites", "cited_by",
                      "corrects", "corrected_by", "extends",
                      "contradicts", "derives_from"}
        for key in fields:
            if key in REL_FAMILY and key not in REL_MAPPED:
                warnings.append((rel_page, "relation vocabulary",
                                 f"relation field {key} is outside"
                                 " the closed relation vocabulary"
                                 " ([[relation-vocabulary]]) —"
                                 " reword into the vocabulary or"
                                 " leave the relation undeclared"))
        if str(fields.get("status") or "").strip() == "tombstoned" \
                and (not fields.get("tombstoned")
                     or not fields.get("tombstone_reason")):
            warnings.append((rel_page, "tombstone fields",
                             "tombstoned page lacks tombstone"
                             " fields (tombstoned /"
                             " tombstone_reason) — see"
                             " [[relation-vocabulary]]"))

        work_type = fields.get("work_type")
        if work_type is not None:
            wt = str(work_type).strip().strip("\"'")
            if wt not in ("record", "synthesis", "advice",
                          "speculation"):
                warnings.append((rel_page, "work_type value",
                                 f"work_type {wt!r} is outside the"
                                 " closed vocabulary (record /"
                                 " synthesis / advice /"
                                 " speculation)"))
            elif wt in ("synthesis", "advice") \
                    and not fields.get("methods"):
                warnings.append((rel_page, "work_type methods",
                                 f"work_type {wt} carries no"
                                 " methods: line (the auditable"
                                 " kinds state how the page was"
                                 " made)"))

        tags = as_list(fields.get("tags"))
        if not tags:
            warnings.append((rel_page, "no tags", "tags list is empty"))

        if not fields.get("as_of"):
            flat = strip_code(body).replace("\n", " ")
            for sent in SENTENCE_RE.split(flat):
                if VOL_NUM_RE.search(sent) and VOL_CUR_RE.search(sent):
                    warnings.append(
                        (rel_page, "volatile claim without as_of",
                         "present-tense quantitative claim with no "
                         "as_of date: " + " ".join(sent.split())[:110]))
                    break

        for target in LINK_RE.findall(strip_code(body)):
            target = target.strip()
            if not target:
                continue
            st, detail = res.resolve_link(target)
            if st == "broken":
                errors.append((rel_page, "broken wikilink",
                               f"[[{target}]]"))
            elif st == "ambiguous":
                warnings.append((rel_page, "ambiguous wikilink",
                                 f"[[{target}]] ({detail})"))

        n_cites += check_claim_citations(rel_page, body, errors)

        if not any(e[0] == rel_page for e in errors):
            n_clean += 1

    # ------------------------------------------- schema grandfathering
    if grandfathered:
        from collections import Counter
        groups = Counter((v.get("field"), v.get("since_version"))
                         for _r, v in grandfathered)
        for (field, since), n in sorted(groups.items()):
            warnings.append(
                ("(schema)", "schema grandfathering",
                 f"{n} legacy page(s) predate schema v{since} field "
                 f"{field!r} — grandfathered: warning-only for legacy "
                 "pages, an error for pages declaring the new version"))

    # ---------------------------------------------------------- coverage
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest_files = sorted((manifest.get("files") or {}).keys())
        manifest_note = f"per {MANIFEST_PATH.relative_to(ROOT).as_posix()}" \
                        f" (generated {manifest.get('generated_at')})"
    else:
        manifest_files = sorted(
            p.relative_to(ROOT).as_posix()
            for p in RAW.rglob("*") if p.is_file())
        manifest_note = "provenance manifest NOT FOUND — live disk scan used"
        warnings.append(("(coverage)", "no provenance manifest", manifest_note))
    rules, note_found = load_exemptions()
    if not note_found:
        warnings.append(("(coverage)", "no exemptions note",
                         f"{NOTE_PATH.relative_to(ROOT).as_posix()} not "
                         "present yet — nothing is exempted"))

    n_cited = n_exempt = 0
    unaccounted = []
    for rel in manifest_files:
        if rel in cited:
            n_cited += 1
        elif exemption_for(rel, rules):
            n_exempt += 1
        else:
            unaccounted.append(rel)
    for rel in unaccounted:
        errors.append(("(coverage)", "unaccounted raw file",
                       f"{rel} — cited by no page, not exempted"))

    # ---------------------------------------------------------- secrets
    for rel, why in secret_scan():
        errors.append(("(secrets)", "possible secret in tree",
                       f"{rel} — {why}"))

    # ------------------------------------------------------------ report
    print("== Wiki validation ==")
    print(f"Pages scanned: {len(pages)}  (structural: {n_structural},"
          f" content pages clean: {n_clean})")
    print(f"Claim-level citations checked: {n_cites}")
    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for page, kind, detail in errors:
            print(f"  - [{kind}] {page}: {detail}")
    if warnings:
        print(f"\nWARNINGS ({len(warnings)}):")
        for page, kind, detail in warnings:
            print(f"  - [{kind}] {page}: {detail}")
    print("\n== Coverage (context-engine standard) ==")
    print(f"  basis: {manifest_note}")
    print(f"  raw files total : {len(manifest_files)}")
    print(f"  cited by a page : {n_cited}")
    print(f"  exempted w/why  : {n_exempt}  ({len(rules)} exemption rule(s) loaded)")
    print(f"  UNACCOUNTED     : {len(unaccounted)}")
    for rel in unaccounted:
        print(f"    - {rel}")

    def by_kind(items):
        kinds = {}
        for _p, k, _d in items:
            kinds[k] = kinds.get(k, 0) + 1
        return ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())) or "none"

    print("\nSummary: " f"errors={len(errors)} ({by_kind(errors)}); "
          f"warnings={len(warnings)} ({by_kind(warnings)})")
    print("Result:", "FAIL" if errors else "PASS")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
