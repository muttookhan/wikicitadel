#!/usr/bin/env python3
"""wiki_okf_export.py — the OKF conformance export (WikiCitadel v1).

Emits every compiled wiki page as an **OKF v0.2** bundle (Open
Knowledge Format, Google Cloud) beside the Lens's llms.txt exports —
a sibling interchange artefact, never a replacement, and read-only
over the wiki: no page is mutated, the bundle is derived and can be
deleted and rebuilt like any Lens output.

Spec targeted: **OKF v0.2**, SPEC.md in the canonical home
GoogleCloudPlatform/open-knowledge-format (checked live:
still version 0.2; the spec moved there from
GoogleCloudPlatform/knowledge-catalog, whose okf/ copy is a frozen
snapshot — same 37,748-byte SPEC.md). The survey record that
motivated this build is docs/research-notes.md
("OKF emerged as a format", okf-harness, OKF byte-level
verification, okf-memory's generated-vs-verified trust tiers and
`stale_after` lifecycle field).

Field mapping (ours -> OKF v0.2). Omit rather than invent: where
our schema has no value for an OKF field, the field is left out and
the omission is recorded by the conformance check. Where OKF has
no field for ours, the value is preserved verbatim under the
`llm_wiki:` extension namespace (OKF section 4.1 permits arbitrary
extra keys; the rule for format conversion is "flag, never
drop"):

  title        -> title                 (verbatim)
  type         -> type                  (verbatim; OKF's only
                                         required key, a free string)
  tags         -> tags                  (verbatim; PLUS, when the
                    tag is registered in
                    evaluation/tag-registry.jsonl , an
                    entry under llm_wiki.tag_concepts carrying
                    the concept's prefLabel and scopeNote — the
                    label's meaning travels with the record
                    instead of dying at the export boundary.
                    An altLabel resolves to its concept and is
                    recorded as used_as; an unregistered tag
                    contributes no entry — inventing a meaning
                    for it is the registry check's opposite)
  sources      -> sources               (each raw-path string becomes
                    an entry {id, resource}: resource is the path
                    verbatim — it names an artifact in the canonical
                    repository's raw/ layer, external to the bundle,
                    which section 5.1 allows; id is the path's stem,
                    the join key OKF per-claim footnotes would use)
  status       -> status                (vocabulary mapped, below;
                    absent in ours -> omitted, OKF default `stable`
                    applies; original value preserved under
                    llm_wiki.status ONLY when the mapping changed it)
  created      -> llm_wiki.created      (ours is a date; OKF trust
  updated      -> llm_wiki.updated       timestamps are datetimes with
                                         an offset, and `generated`
                                         additionally requires an
                                         actor we do not record per
                                         page — so neither `generated`
                                         nor a fabricated datetime is
                                         emitted)
  confidence   -> llm_wiki.confidence   (OKF stores no score by
                                         design — signals, not scores;
                    and its `verified` family records actor+datetime
                    events we do not keep. Our confidence stays a
                    signal under the namespace; no page is stamped
                    `verified` it did not earn)
  claim        -> llm_wiki.claim        (claim-lifecycle opt-ins)
  as_of        -> llm_wiki.as_of        (a last-checked date is NOT
                                         `stale_after`, which is a
                                         future staleness deadline;
                                         the two are never conflated)
  ^[cite: ...] -> llm_wiki.inline_citations (a COUNT; the markers
                    stay in the body verbatim. OKF per-claim
                    attribution uses footnotes keyed to sources[].id;
                    converting our markers is a recorded deviation,
                    not silently performed)
  any other    -> llm_wiki.<key>        (verbatim, e.g. a future
  frontmatter                            outcome_* or _schema_version)

Status vocabulary map (ours -> OKF draft|stable|deprecated):
  draft -> draft; deprecated -> deprecated; superseded -> deprecated
  (no longer current, kept for history); archived -> deprecated;
  verified | published | active | needs-verification -> stable
  (live and current; the needs-verification flag survives under
  llm_wiki.status because the mapping changed the value's meaning).
An unrecognised status value is omitted from `status` and preserved
under llm_wiki.status instead of being guessed.

Bundle layout (mirrors the wiki tree, wiki/ stripped):

  <out>/index.md     OKF section 8 reserved file: our index body
                     with wikilinks rewritten to bundle-relative
                     markdown links, plus the bundle-root
                     `okf_version: "0.2"` frontmatter section 12
                     permits (the only frontmatter an index may
                     carry)
  <out>/log.md       OKF section 9 reserved file: our entries
                     regrouped under `## YYYY-MM-DD` headings,
                     newest first, each entry led by
                     `* **<Kind>**: <title>`; entry bodies verbatim.
                     (Our log's own preamble, which documents the
                     source format, is not carried over.)
  <out>/<section>/<page>.md   one OKF concept per compiled page,
                     body verbatim
  <out>/manifest.json  producer, spec source, git HEAD, per-file
                     SHA-256 + byte size + source path, counts.

Excluded, matching scripts/wiki_schema.py and
scripts/wiki_skill_export.py: wiki/access/ and wiki/talk/ are not
compiled pages (ledgers and dispute records, not concepts).

Conformance check (`check`): validates a bundle ON DISK against
SPEC section 11 plus the section 5/10 family rules — parseable YAML
frontmatter (PyYAML, the repo's declared tooling dependency), a
non-empty `type` on every concept, reserved files following
sections 8/9, and, when the optional families are present, their
shapes (status vocabulary; sources entries carrying `resource`;
generated/verified actor + ISO-8601-with-offset timestamps;
stale_after a datetime; Attested Computation carrying `runtime`).
Each file is reported PASS, PASS-WITH-OMISSIONS (conformant, with
the recorded omissions: missing recommended description/resource,
absent trust family, preserved extension namespace, unrewritten
wikilinks or cite markers in the body, external source paths), or
FAIL with the reason. Exit 0 when nothing fails, 1 on any FAIL.

Manually run only — deliberately NOT wired into the nightly sweep
or any cron:

    python3 scripts/wiki_okf_export.py export [--out DIR]
    python3 scripts/wiki_okf_export.py check [--bundle DIR] [--json PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
DEFAULT_OUT = ROOT / "exports" / "okf-bundle"

OKF_VERSION = "0.2"
SPEC_SOURCE = ("https://github.com/GoogleCloudPlatform/"
               "open-knowledge-format/blob/main/SPEC.md")
PRODUCER = "scripts/wiki_okf_export.py"

EXCLUDED_DIRS = {"access", "talk"}
STRUCTURAL = {"index.md", "log.md"}  # relative to wiki/ root

OKF_STATUSES = {"draft", "stable", "deprecated"}
STATUS_MAP = {
    "draft": "draft",
    "deprecated": "deprecated",
    "superseded": "deprecated",
    "archived": "deprecated",
    "verified": "stable",
    "published": "stable",
    "active": "stable",
    "needs-verification": "stable",
}
# Frontmatter keys with a defined mapping; anything else is
# preserved under the namespace rather than dropped.
MAPPED_KEYS = {"title", "type", "tags", "sources", "status",
               "created", "updated", "confidence", "claim", "as_of"}
NAMESPACE_ORDER = ["created", "updated", "status", "confidence",
                   "claim", "as_of", "inline_citations",
                   "tag_concepts"]

CITE_RE = re.compile(r"\^\[cite:")
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
ISO_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(\.\d+)?"
    r"(Z|[+-]\d{2}:\d{2})$")


# ------------------------------------------------------------ parsing

def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "wiki_validate", Path(__file__).resolve().parent
        / "wiki_validate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VALIDATE = _load_validator()
parse_frontmatter = VALIDATE.parse_frontmatter
as_list = VALIDATE.as_list


def _load_tags():
    """The tag-registry module , when present."""
    path = Path(__file__).resolve().parent / "wiki_tags.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("wiki_tags", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TAGS = _load_tags()


def load_tag_concepts():
    """The registered tag concepts the export enriches with,
    or None when there is no registry to travel with (the
    enrichment is omitted, never invented). A registry that
    exists but cannot be read refuses the export: corrupt
    governed state must not pass silently."""
    if TAGS is None:
        return None
    if not (ROOT / TAGS.REGISTRY_REL).is_file():
        return None
    try:
        _header, concepts = TAGS.load_registry(ROOT)
    except (OSError, ValueError) as exc:
        raise SystemExit("tag registry unreadable: %s" % exc)
    return concepts


def page_paths(wiki_dir: Path):
    """(concepts, structural): wiki-relative paths of the export set."""
    concepts, structural = [], []
    for path in sorted(wiki_dir.rglob("*.md")):
        rel = path.relative_to(wiki_dir)
        if rel.parts[0] in EXCLUDED_DIRS:
            continue
        if len(rel.parts) == 1 and rel.name in STRUCTURAL:
            structural.append(rel)
        else:
            concepts.append(rel)
    return concepts, structural


# ------------------------------------------------------- YAML emitter

_PLAIN_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-/]*$")
_RESERVED_WORDS = {"true", "false", "null", "yes", "no", "on", "off",
                   "~"}
_DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ].*)?$")
_NUMBER_LIKE = re.compile(r"^-?\d+(\.\d+)?$")


def yaml_scalar(value) -> str:
    """One YAML scalar, plain only when it cannot be misread."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if (text and _PLAIN_SAFE.match(text)
            and text.lower() not in _RESERVED_WORDS
            and not _DATE_LIKE.match(text)
            and not _NUMBER_LIKE.match(text)):
        return text
    return json.dumps(text, ensure_ascii=False)


def dump_frontmatter(fields: dict) -> str:
    """Deterministic block-style YAML for the emitted field shapes:
    scalars, string lists (flow), sources (block list of flat maps),
    and the llm_wiki namespace (flat block map, whose values may
    themselves be block lists of flat maps — tag_concepts)."""
    lines = []
    for key, value in fields.items():
        if value is None:
            continue
        if key == "sources":
            lines.append("sources:")
            for entry in value:
                lines.append("  - id: " + yaml_scalar(entry["id"]))
                lines.append("    resource: "
                             + yaml_scalar(entry["resource"]))
        elif key == "llm_wiki":
            lines.append("llm_wiki:")
            for sub, subval in value.items():
                if isinstance(subval, list) and subval \
                        and isinstance(subval[0], dict):
                    # A list of flat maps (tag_concepts): block
                    # list under the namespace key.
                    lines.append("  %s:" % sub)
                    for entry in subval:
                        first = True
                        for ekey, evalue in entry.items():
                            prefix = "    - " if first else "      "
                            first = False
                            lines.append("%s%s: %s"
                                         % (prefix, ekey,
                                            yaml_scalar(evalue)))
                elif isinstance(subval, list):
                    items = ", ".join(yaml_scalar(v) for v in subval)
                    lines.append("  %s: [%s]" % (sub, items))
                else:
                    lines.append("  %s: %s"
                                 % (sub, yaml_scalar(subval)))
        elif isinstance(value, list):
            items = ", ".join(yaml_scalar(v) for v in value)
            lines.append("%s: [%s]" % (key, items))
        else:
            lines.append("%s: %s" % (key, yaml_scalar(value)))
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------ mapping

def source_id(path: str, taken: set) -> str:
    stem = Path(path).stem.lower()
    base = re.sub(r"[^a-z0-9]+", "-", stem).strip("-") or "source"
    candidate, n = base, 2
    while candidate in taken:
        candidate = "%s-%d" % (base, n)
        n += 1
    taken.add(candidate)
    return candidate


def map_page(fields: dict, body: str, tag_concepts=None) -> dict:
    """Our frontmatter + body -> the OKF frontmatter dict to emit.
    tag_concepts, when given, is the tag registry's concept
    list: the page's registered tags additionally travel as
    llm_wiki.tag_concepts (prefLabel + scopeNote)."""
    out = {}
    out["type"] = fields.get("type")
    if fields.get("title") is not None:
        out["title"] = fields["title"]
    tags = as_list(fields.get("tags"))
    if tags:
        out["tags"] = [str(t) for t in tags]

    sources = [str(s) for s in as_list(fields.get("sources"))]
    if sources:
        taken = set()
        out["sources"] = [{"id": source_id(s, taken), "resource": s}
                          for s in sources]

    namespace = {}
    raw_status = fields.get("status")
    if raw_status is not None:
        raw_status = str(raw_status)
        mapped = STATUS_MAP.get(raw_status)
        if mapped is not None:
            out["status"] = mapped
            if mapped != raw_status:
                namespace["status"] = raw_status
        else:
            namespace["status"] = raw_status
    for key in ("created", "updated", "confidence", "claim", "as_of"):
        if fields.get(key) is not None:
            namespace[key] = fields[key]
    cites = len(CITE_RE.findall(body))
    if cites:
        namespace["inline_citations"] = cites
    for key in sorted(fields):
        if key not in MAPPED_KEYS and fields[key] is not None:
            namespace[key] = fields[key]
    if tag_concepts is not None and tags:
        entries = TAGS.tag_concepts_for(tags, tag_concepts)
        if entries:
            namespace["tag_concepts"] = entries

    if namespace:
        ordered = {}
        for key in NAMESPACE_ORDER:
            if key in namespace:
                ordered[key] = namespace[key]
        for key in namespace:
            if key not in ordered:
                ordered[key] = namespace[key]
        out["llm_wiki"] = ordered
    return out


def render_concept(fields: dict, body: str,
                   tag_concepts=None) -> str:
    return "---\n" + dump_frontmatter(
        map_page(fields, body, tag_concepts)) + "---\n" + body


# ------------------------------------------------- reserved files

def transform_index(text: str, stem_to_rel: dict) -> tuple[str, int]:
    """Our index body -> OKF section 8 index. Returns (text,
    unresolved-link count). Wikilinks become bundle-relative
    markdown links; unresolvable targets degrade to plain labels."""
    unresolved = 0

    def repl(match):
        nonlocal unresolved
        inner = match.group(1)
        target, _, label = inner.partition("|")
        target = target.strip()
        label = label.strip() or target
        key = target[len("wiki/"):] if target.startswith("wiki/") \
            else target
        rel = stem_to_rel.get(key) or stem_to_rel.get(
            Path(key).name)
        if rel is None:
            unresolved += 1
            return label
        return "[%s](%s)" % (label, rel)

    lines = []
    for line in text.splitlines():
        line = WIKILINK_RE.sub(repl, line)
        if line.startswith("- "):
            line = "* " + line[2:]
            # the one-line summary separator after a link: — -> -
            line = re.sub(r"(\]\([^)]*\)) — ", r"\1 - ", line)
        lines.append(line)
    body = "\n".join(lines).rstrip("\n") + "\n"
    return '---\nokf_version: "%s"\n---\n\n' % OKF_VERSION + body, \
        unresolved


LOG_ENTRY_RE = re.compile(
    r"^## \[(\d{4}-\d{2}-\d{2})\] (\S+) \| (.*)$")


def transform_log(text: str) -> str:
    """Our append-only log -> OKF section 9 log: entries regrouped
    under `## YYYY-MM-DD` headings, newest first, each led by a
    `* **Kind**: Title` line; entry bodies verbatim."""
    entries = []  # (date, kind, title, body_lines)
    current = None
    for line in text.splitlines():
        m = LOG_ENTRY_RE.match(line)
        if m:
            current = (m.group(1), m.group(2), m.group(3), [])
            entries.append(current)
        elif current is not None:
            current[3].append(line)
    by_date = {}
    for date, kind, title, body_lines in entries:
        by_date.setdefault(date, []).append((kind, title, body_lines))
    out = ["# Log", ""]
    for date in sorted(by_date, reverse=True):
        out.append("## " + date)
        out.append("")
        for kind, title, body_lines in by_date[date]:
            kind_word = kind[:1].upper() + kind[1:]
            out.append("* **%s**: %s" % (kind_word, title))
            body = "\n".join(body_lines).strip("\n")
            if body.strip():
                out.append("")
                out.append(body)
            out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


# -------------------------------------------------------------- build

def git_head() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, timeout=10)
        if proc.returncode == 0:
            return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def build_bundle(wiki_dir: Path, out_dir: Path) -> dict:
    concepts, structural = page_paths(wiki_dir)

    # Pre-validate: every concept must parse and carry a type, or
    # the export refuses rather than emitting a partial bundle.
    parsed = {}
    problems = []
    for rel in concepts:
        fields, body = parse_frontmatter(
            (wiki_dir / rel).read_text(encoding="utf-8"))
        if fields is None:
            problems.append("%s: no parseable frontmatter" % rel)
        elif not str(fields.get("type") or "").strip():
            problems.append("%s: frontmatter has no type" % rel)
        else:
            parsed[rel] = (fields, body)
    if problems:
        raise SystemExit("export refused:\n  " + "\n  ".join(problems))

    if out_dir.exists():
        for old in sorted(out_dir.rglob("*.md")):
            old.unlink()
        manifest_old = out_dir / "manifest.json"
        if manifest_old.exists():
            manifest_old.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []  # (bundle_rel, source_rel, text)

    tag_concepts = load_tag_concepts()

    stem_to_rel = {}
    for rel in concepts:
        stem_to_rel.setdefault(rel.stem, rel.as_posix())
    for rel in concepts:
        fields, body = parsed[rel]
        text = render_concept(fields, body, tag_concepts)
        written.append((rel.as_posix(), ("wiki/" + rel.as_posix()),
                        text))

    for rel in structural:
        source_text = (wiki_dir / rel).read_text(encoding="utf-8")
        if rel.name == "index.md":
            text, _unresolved = transform_index(source_text,
                                                stem_to_rel)
        else:
            text = transform_log(source_text)
        written.append((rel.as_posix(), "wiki/" + rel.as_posix(),
                        text))

    files_meta = []
    for bundle_rel, source_rel, text in sorted(written):
        dest = out_dir / bundle_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode("utf-8")
        dest.write_bytes(data)
        files_meta.append({
            "path": bundle_rel,
            "source": source_rel,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        })

    manifest = {
        "format": "OKF",
        "okf_version": OKF_VERSION,
        "spec_source": SPEC_SOURCE,
        "producer": PRODUCER,
        "generated_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "git_head": git_head(),
        "source_root": "wiki/",
        "counts": {
            "concepts": len(concepts),
            "reserved_files": len(structural),
            "files": len(files_meta),
        },
        "files": files_meta,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return manifest


# ------------------------------------------------------------ check

def _is_iso_dt(value) -> bool:
    return isinstance(value, str) and bool(ISO_DT_RE.match(value))


def _check_family(fm: dict, problems: list):
    """OKF section 5/10 family rules, applied when present."""
    status = fm.get("status")
    if status is not None and status not in OKF_STATUSES:
        problems.append("status %r not in the OKF vocabulary "
                        "(draft|stable|deprecated)" % (status,))
    sources = fm.get("sources")
    if sources is not None:
        if not isinstance(sources, list):
            problems.append("sources is not a list")
        else:
            for i, entry in enumerate(sources):
                if not isinstance(entry, dict):
                    problems.append("sources[%d] is not a mapping"
                                    % i)
                elif not str(entry.get("resource") or "").strip():
                    problems.append("sources[%d] lacks the required "
                                    "resource" % i)
                elif "last_modified" in entry and not _is_iso_dt(
                        entry["last_modified"]):
                    problems.append("sources[%d].last_modified is "
                                    "not an ISO 8601 datetime with "
                                    "offset" % i)
    window = fm.get("usage_window")
    if window is not None:
        if not isinstance(window, dict) or not (
                _is_iso_dt(window.get("from"))
                and _is_iso_dt(window.get("to"))):
            problems.append("usage_window lacks ISO 8601 from/to "
                            "datetimes")
    generated = fm.get("generated")
    if generated is not None:
        if not isinstance(generated, dict) or not str(
                generated.get("by") or "").strip():
            problems.append("generated lacks the required by actor")
        elif "at" in generated and not _is_iso_dt(generated["at"]):
            problems.append("generated.at is not an ISO 8601 "
                            "datetime with offset")
    verified = fm.get("verified")
    if verified is not None:
        events = verified if isinstance(verified, list) else [verified]
        for i, event in enumerate(events):
            if not isinstance(event, dict) or not str(
                    event.get("by") or "").strip():
                problems.append("verified[%d] lacks a by actor" % i)
            elif "at" in event and not _is_iso_dt(event["at"]):
                problems.append("verified[%d].at is not an ISO 8601 "
                                "datetime with offset" % i)
    if "stale_after" in fm and not _is_iso_dt(fm["stale_after"]):
        problems.append("stale_after is not an ISO 8601 datetime "
                        "with offset")
    if fm.get("type") == "Attested Computation" and not str(
            fm.get("runtime") or "").strip():
        problems.append("Attested Computation lacks the required "
                        "runtime")


def _omissions(fm: dict, body: str, bundle_root: Path,
               bundle_rel: str) -> list:
    """Recorded omissions/deviations for a conformant concept."""
    notes = []
    if not fm.get("description"):
        notes.append("no description (OKF-recommended; not invented)")
    if not fm.get("resource"):
        notes.append("no resource URI (OKF-recommended; not invented)")
    if "generated" not in fm and "verified" not in fm:
        notes.append("no generated/verified trust family (source "
                     "records no per-page actor or verification "
                     "events; trust tier derives as unverified)")
    if isinstance(fm.get("llm_wiki"), dict) and fm["llm_wiki"]:
        notes.append("extension namespace llm_wiki carries: "
                     + ", ".join(str(k) for k in fm["llm_wiki"]))
    if WIKILINK_RE.search(body):
        notes.append("body keeps [[wikilinks]] verbatim (not "
                     "rewritten to OKF markdown links; tolerated "
                     "by SPEC sections 6/11)")
    if CITE_RE.search(body):
        notes.append("body keeps ^[cite:] markers verbatim (OKF "
                     "per-claim attribution uses footnotes keyed "
                     "to sources[].id)")
    for entry in fm.get("sources") or []:
        if isinstance(entry, dict):
            resource = str(entry.get("resource") or "")
            if resource and not resource.startswith(
                    ("http://", "https://", "/")):
                target = bundle_root / resource
                if not target.exists():
                    notes.append("sources point outside the bundle "
                                 "(%s — into the canonical repo's "
                                 "raw/ layer; external sources are "
                                 "legal under SPEC section 5.1)"
                                 % resource)
                    break
    return notes


def _split_frontmatter(text: str):
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def check_bundle(bundle_dir: Path) -> dict:
    """Validate a bundle on disk. Returns the report dict."""
    import yaml  # PyYAML: the repo's declared tooling dependency

    results = []
    md_files = sorted(
        p for p in bundle_dir.rglob("*.md")
        if p.is_file())
    for path in md_files:
        rel = path.relative_to(bundle_dir).as_posix()
        text = path.read_text(encoding="utf-8")
        fm_text, body = _split_frontmatter(text)
        problems, notes = [], []

        if path.name in STRUCTURAL and len(
                path.relative_to(bundle_dir).parts) == 1:
            # Reserved filename at the bundle root.
            if path.name == "index.md":
                if fm_text is not None:
                    try:
                        fm = yaml.safe_load(fm_text) or {}
                        extra = set(fm) - {"okf_version"}
                        if extra:
                            problems.append(
                                "index.md frontmatter carries keys "
                                "beyond okf_version: %s"
                                % ", ".join(sorted(extra)))
                    except yaml.YAMLError as exc:
                        problems.append("index.md frontmatter is "
                                        "not parseable YAML: %s"
                                        % exc)
                if not re.search(r"^\* \[", body, re.M):
                    problems.append("index.md body has no section-8 "
                                    "list entries")
            else:  # log.md
                dates = re.findall(r"^## (\d{4}-\d{2}-\d{2})$",
                                   body, re.M)
                if not dates:
                    problems.append("log.md has no section-9 "
                                    "`## YYYY-MM-DD` headings")
                elif dates != sorted(dates, reverse=True):
                    problems.append("log.md date headings are not "
                                    "newest-first")
                stray = [h for h in re.findall(r"^## (.+)$", body,
                                                re.M)
                         if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", h)]
                if stray:
                    problems.append("log.md carries non-date ## "
                                    "headings: %s"
                                    % "; ".join(stray[:3]))
            verdict = "FAIL" if problems else "PASS"
            results.append({"path": rel, "kind": "reserved",
                            "verdict": verdict,
                            "problems": problems, "omissions": notes})
            continue

        # Concept documents.
        if fm_text is None:
            problems.append("no YAML frontmatter block (SPEC 11.1)")
            results.append({"path": rel, "kind": "concept",
                            "verdict": "FAIL", "problems": problems,
                            "omissions": notes})
            continue
        try:
            fm = yaml.safe_load(fm_text)
        except yaml.YAMLError as exc:
            problems.append("frontmatter is not parseable YAML: %s"
                            % exc)
            results.append({"path": rel, "kind": "concept",
                            "verdict": "FAIL", "problems": problems,
                            "omissions": notes})
            continue
        if not isinstance(fm, dict):
            problems.append("frontmatter is not a mapping")
            results.append({"path": rel, "kind": "concept",
                            "verdict": "FAIL", "problems": problems,
                            "omissions": notes})
            continue
        if not str(fm.get("type") or "").strip():
            problems.append("frontmatter lacks a non-empty type "
                            "(SPEC 11.2)")
        _check_family(fm, problems)
        if not problems:
            notes = _omissions(fm, body, bundle_dir, rel)
        verdict = ("FAIL" if problems else
                   "PASS-WITH-OMISSIONS" if notes else "PASS")
        results.append({"path": rel, "kind": "concept",
                        "verdict": verdict, "problems": problems,
                        "omissions": notes})

    counts = {"PASS": 0, "PASS-WITH-OMISSIONS": 0, "FAIL": 0}
    for r in results:
        counts[r["verdict"]] += 1
    return {"bundle": str(bundle_dir), "okf_version": OKF_VERSION,
            "spec_source": SPEC_SOURCE, "counts": counts,
            "files": results}


def print_report(report: dict):
    counts = report["counts"]
    print("OKF %s conformance — %s" % (report["okf_version"],
                                       report["bundle"]))
    for r in report["files"]:
        line = "  %-9s %s" % (r["verdict"], r["path"])
        print(line)
        for problem in r["problems"]:
            print("      FAIL: " + problem)
        for note in r["omissions"]:
            print("      note: " + note)
    print("Counts: PASS %d · PASS-WITH-OMISSIONS %d · FAIL %d "
          "(of %d files)" % (counts["PASS"],
                             counts["PASS-WITH-OMISSIONS"],
                             counts["FAIL"], len(report["files"])))


# --------------------------------------------------------------- CLI

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="OKF v0.2 conformance export for the LLM Wiki "
                    "(see module docstring).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser(
        "export", help="Build the OKF bundle, then check it.")
    p_export.add_argument("--out", default=str(DEFAULT_OUT),
                          help="bundle output dir (default: "
                               "%(default)s)")

    p_check = sub.add_parser(
        "check", help="Check an emitted bundle on disk.")
    p_check.add_argument("--bundle", default=str(DEFAULT_OUT),
                         help="bundle dir (default: %(default)s)")
    p_check.add_argument("--json", default=None,
                         help="also write the report as JSON here")

    args = parser.parse_args(argv)

    if args.command == "export":
        out_dir = Path(args.out)
        manifest = build_bundle(WIKI, out_dir)
        print("Bundle written: %s (%d concepts, %d reserved files)"
              % (out_dir, manifest["counts"]["concepts"],
                 manifest["counts"]["reserved_files"]))
        report = check_bundle(out_dir)
        print_report(report)
        return 1 if report["counts"]["FAIL"] else 0

    report = check_bundle(Path(args.bundle))
    print_report(report)
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    return 1 if report["counts"]["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
