#!/usr/bin/env python3
"""wiki_good_enough.py — the good-enough-practices checker
(W6, build list 2026-10-22).

Clean re-implementation of an idea: Wilson et al., "Good
Enough Practices in Scientific Computing" (PLOS Comput
Biol 13(6): e1005510, 2017; CC-BY 4.0) names a short floor
of baseline practices a research project either meets or
visibly doesn't. This tool applies that floor to THIS
wiki, restated in our words in the checklist definition
(evaluation/good-enough-checklist.json — the citation to
the paper lives there and on every report).

Each practice is judged against the tree itself, never
against a document claiming the practice is done:

  met               the evidence artefact stands in the
                    tree and the checker examined it
  not-met           the mechanical check reaches a
                    verdict and it is no — the measured
                    fact is printed as the evidence
  manual            no honest mechanical check reaches
                    this practice; the verdict carries
                    the question a human answers
  not-applicable    the definition states a standing
                    reason the practice does not apply

Verdict bases are stated per practice: "verified-in-tree"
(the artefact itself was examined) vs "recorded" (the
practice is discharged by a system outside this tree and
the in-tree record of it is the evidence).

The checker is READ-ONLY over the tree it judges: the
only writes it ever makes are the report artefacts named
by an explicit --out. Dates are inputs (--today); the
same tree + the same date give byte-identical reports.

Usage:
  python3 scripts/wiki_good_enough.py check
      [--root DIR] [--today YYYY-MM-DD]
      [--checklist evaluation/good-enough-checklist.json]
      [--out PREFIX] [--json]

  --out PREFIX writes PREFIX.json + PREFIX.md.
  Exit: 0 = report produced; 1 = at least one practice
  not-met (findings — the report is the deliverable);
  2 = usage / definition error.
Stdlib only.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent

TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".txt", ".yaml",
                 ".yml", ".csv", ""}
ROOT_ALLOWLIST = {
    "AGENTS.md", "README.md", "Home.md", "purpose.md",
    "CONVERSATION-LOG.md", "owner-rights-reversal-notice.md",
    "azure-pipelines.yml", ".gitignore", ".gitattributes",
    "LICENSE", "LICENCE", "COPYING",
    "LICENSE.md", "LICENCE.md", "COPYING.md",
}
LAYOUT_DIRS = ("raw", "wiki", "scripts", "evaluation",
               "templates", "tools")
COMPILE_STAMP_THRESHOLD = 0.50
DOCSTRING_THRESHOLD = 0.95
OPEN_FORMAT_THRESHOLD = 0.99
CHANGELOG_MAX_AGE_DAYS = 14


# -- helpers -----------------------------------------------------------------

def _count_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(
        encoding="utf-8", errors="ignore").splitlines()
        if line.strip())


def _git(root: Path, *args) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


# -- mechanical checks ---------------------------------------------------------
# Each returns (verdict, basis, evidence[list of str], detail[str]).

def check_raw_layer(root, today):
    raw = root / "raw"
    n = sum(1 for p in raw.rglob("*") if p.is_file()) \
        if raw.is_dir() else 0
    lock_path = root / "evaluation" / "citation-lockfile.json"
    locked = 0
    if lock_path.is_file():
        try:
            doc = json.loads(lock_path.read_text(
                encoding="utf-8", errors="ignore"))
            cites = doc.get("citations") or doc.get("entries") \
                or doc
            locked = len(cites) if hasattr(cites, "__len__") \
                else 0
        except (ValueError, OSError):
            locked = 0
    met = raw.is_dir() and n >= 100 and locked >= 1
    return ("met" if met else "not-met", "verified-in-tree",
            [f"raw/ ({n} files)",
             f"evaluation/citation-lockfile.json "
             f"({locked} locked citations)"],
            f"raw layer holds {n} files; the citation "
            f"lockfile pins {locked} citations by hash.")


def check_backups(root, today):
    remotes = _git(root, "remote")
    remote_names = remotes.splitlines() if remotes else []
    ckpt = _count_lines(root / "evaluation" / "checkpoints.jsonl")
    witness = Path.home() / "workspace" / "wiki-checkpoints"
    witnessed = witness.is_dir()
    met = bool(remote_names) and ckpt >= 1 and witnessed
    return ("met" if met else "not-met", "verified-in-tree",
            [f"git remotes: {', '.join(remote_names) or 'none'}",
             f"evaluation/checkpoints.jsonl "
             f"({ckpt} lines)",
             "~/workspace/wiki-checkpoints "
             + ("(present, outside the repo)"
                if witnessed else "(ABSENT)")],
            "Canonical remote + signed checkpoint register "
            "+ an off-repo witness copy are the in-tree "
            "legs; the nightly Drive archives ride on the "
            "same checkpoint record.")


def check_compile_stamps(root, today):
    wiki = root / "wiki"
    pages = [p for p in wiki.rglob("*.md")
             if p.name not in ("index.md", "log.md")] \
        if wiki.is_dir() else []
    stamped = 0
    for p in pages:
        head = p.read_text(encoding="utf-8",
                           errors="ignore")[:2500]
        m = re.search(r"^compiled_date:\s*(\S.*)$", head,
                      re.M)
        if m and m.group(1).strip() not in ("", "null", "~"):
            stamped += 1
    frac = (stamped / len(pages)) if pages else 0.0
    met = frac >= COMPILE_STAMP_THRESHOLD
    return ("met" if met else "not-met", "verified-in-tree",
            [f"compiled pages examined: {len(pages)}",
             f"pages with a filled compiled_date stamp: "
             f"{stamped} ({frac:.1%})",
             "scripts/wiki_stamp.py (the stamping tool)"],
            f"Compile stamps stand filled on {stamped} of "
            f"{len(pages)} compiled pages "
            f"({frac:.1%} vs the "
            f"{COMPILE_STAMP_THRESHOLD:.0%} floor). The "
            "steps are recorded centrally (wiki/log.md, "
            "evaluation/research-log.jsonl) but not on "
            "the artefacts themselves.")


def check_identifier_registers(root, today):
    ev = []
    ok = True
    for name in ("claim-index.jsonl", "tag-registry.jsonl",
                 "decisions-register.jsonl"):
        n = _count_lines(root / "evaluation" / name)
        ev.append(f"evaluation/{name} ({n} lines)")
        ok = ok and n >= 1
    return ("met" if ok else "not-met", "verified-in-tree",
            ev, "Identifier-bearing registers all stand "
            "and are populated.")


def check_program_headers(root, today):
    files = sorted((root / "scripts").glob("*.py"))
    withdoc = 0
    for f in files:
        try:
            tree = ast.parse(f.read_text(
                encoding="utf-8", errors="ignore"))
            if ast.get_docstring(tree):
                withdoc += 1
        except SyntaxError:
            pass
    frac = (withdoc / len(files)) if files else 0.0
    met = bool(files) and frac >= DOCSTRING_THRESHOLD
    return ("met" if met else "not-met", "verified-in-tree",
            [f"scripts/*.py examined: {len(files)}",
             f"with a module docstring: {withdoc} "
             f"({frac:.1%})"],
            f"{withdoc} of {len(files)} programs open "
            f"with a docstring (floor "
            f"{DOCSTRING_THRESHOLD:.0%}).")


def check_licence_file(root, today):
    names = {p.name.lower() for p in root.iterdir()
             if p.is_file()} if root.is_dir() else set()
    found = names & {"license", "licence", "copying",
                     "license.md", "licence.md", "copying.md"}
    met = bool(found)
    ev = ([f"{sorted(found)[0]} at the tree root"]
          if met else
          ["named absence: no LICENSE / LICENCE / COPYING "
           "file at the tree root"])
    detail = ("A licence file stands at the root." if met
              else "No licence file stands in this tree. "
              "The public edition (WikiCitadel, a separate "
              "tree) carries MIT; this private tree carries "
              "its licence discipline as a rule in prose, "
              "which is not a licence a holder can rely on.")
    return ("met" if met else "not-met", "verified-in-tree",
            ev, detail)


def check_test_suite(root, today):
    tdir = root / "scripts" / "tests"
    n = len(list(tdir.glob("test_*.py"))) if tdir.is_dir() \
        else 0
    met = n >= 50
    return ("met" if met else "not-met", "verified-in-tree",
            [f"scripts/tests/ ({n} test files)"],
            f"The suite stands at {n} test files inside "
            "the project.")


def check_overview_docs(root, today):
    readme = (root / "README.md").is_file()
    overview = (root / "wiki" / "overview.md").is_file()
    met = readme and overview
    return ("met" if met else "not-met", "verified-in-tree",
            [f"README.md ({'present' if readme else 'ABSENT'})",
             f"wiki/overview.md "
             f"({'present' if overview else 'ABSENT'})"],
            "The start-here documents stand.")


def check_canonical_home(root, today):
    remotes = _git(root, "remote")
    names = remotes.splitlines() if remotes else []
    met = "azure" in names
    return ("met" if met else "not-met", "verified-in-tree",
            [f"git remotes: {', '.join(names) or 'none'}"],
            "One canonical remote (azure) is the shared "
            "home every seat pulls and pushes.")


def check_filings_critique(root, today):
    base = root / "raw" / "filings"
    agents = {}
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if d.is_dir():
                n = sum(1 for p in d.rglob("*")
                        if p.is_file())
                if n:
                    agents[d.name] = n
    met = len(agents) >= 2
    ev = [f"raw/filings/{a}/ ({n} files)"
          for a, n in agents.items()] or \
        ["raw/filings/ (no agent filings stand)"]
    return ("met" if met else "not-met", "verified-in-tree",
            ev,
            f"Filings — the critique channel — stand from "
            f"{len(agents)} distinct agents.")


def check_standard_layout(root, today):
    missing = [d for d in LAYOUT_DIRS
               if not (root / d).is_dir()]
    met = not missing
    return ("met" if met else "not-met", "verified-in-tree",
            [("all of " + ", ".join(LAYOUT_DIRS) + " present")
             if met else
             "missing directories: " + ", ".join(missing)],
            "The standard layout stands.")


def _name_violations(paths):
    return sorted(p.name for p in paths
                  if " " in p.name
                  or any(c.isupper() for c in p.name))


def check_file_names(root, today):
    wiki = root / "wiki"
    pages = list(wiki.rglob("*.md")) if wiki.is_dir() else []
    progs = list((root / "scripts").glob("*.py"))
    bad = _name_violations(pages) + _name_violations(progs)
    met = not bad
    ev = [f"wiki/**/*.md examined: {len(pages)}",
          f"scripts/*.py examined: {len(progs)}",
          f"violations: {len(bad)}"]
    if bad:
        ev.append("offenders: " + ", ".join(bad[:10]))
    return ("met" if met else "not-met", "verified-in-tree",
            ev, "House naming style holds over every file "
            "we name." if met else
            f"{len(bad)} file names break the house style.")


def check_root_tidy(root, today):
    loose = sorted(
        p.name for p in root.iterdir()
        if p.is_file() and p.name not in ROOT_ALLOWLIST)
    met = not loose
    ev = (["root holds only the standing documents"]
          if met else
          ["loose files at the root: " + ", ".join(loose)])
    detail = ("The root is tidy." if met else
              "Working scraps stand at the project root: "
              + ", ".join(loose)
              + ". (Two of these — the loose prompt files "
              "— are already an item on the owner's "
              "board, from Grok's filings.)")
    return ("met" if met else "not-met", "verified-in-tree",
            ev, detail)


def check_version_control(root, today):
    commits = _git(root, "rev-list", "--count", "HEAD")
    tracked = _git(root, "ls-files")
    n_commits = int(commits) if commits and \
        commits.isdigit() else 0
    n_tracked = len(tracked.splitlines()) if tracked else 0
    met = n_commits >= 100 and n_tracked >= 1000
    return ("met" if met else "not-met", "verified-in-tree",
            [f"commits: {n_commits}",
             f"tracked files: {n_tracked}"],
            f"History stands at {n_commits} commits over "
            f"{n_tracked} tracked files.")


_LOG_DATE = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\]",
                       re.M)


def check_changelog(root, today):
    log = root / "wiki" / "log.md"
    dates = []
    if log.is_file():
        dates = [date.fromisoformat(d) for d in
                 _LOG_DATE.findall(log.read_text(
                     encoding="utf-8", errors="ignore"))]
    newest = max(dates) if dates else None
    age = (today - newest).days if newest else None
    met = newest is not None and \
        age <= CHANGELOG_MAX_AGE_DAYS
    newest_s = newest.isoformat() if newest else "none"
    ev = [f"wiki/log.md ({len(dates)} dated entries)",
          f"newest entry: {newest_s}"]
    return ("met" if met else "not-met", "verified-in-tree",
            ev,
            f"The log's newest entry is {age} day(s) old "
            f"against the run date (floor "
            f"{CHANGELOG_MAX_AGE_DAYS} days)."
            if newest else "No dated log entries found.")


def check_checkpoints(root, today):
    n = _count_lines(root / "evaluation" / "checkpoints.jsonl")
    d = root / "evaluation" / "checkpoints.d"
    records = len([p for p in d.glob("*.json")
                   if not p.name.endswith(".sig")]) \
        if d.is_dir() else 0
    met = n >= 1 and records >= 1
    return ("met" if met else "not-met", "verified-in-tree",
            [f"evaluation/checkpoints.jsonl ({n} lines)",
             f"evaluation/checkpoints.d/ "
             f"({records} checkpoint records)"],
            "Signed, witnessed state checkpoints stand.")


def check_open_formats(root, today):
    wiki = root / "wiki"
    files = [p for p in wiki.rglob("*") if p.is_file()] \
        if wiki.is_dir() else []
    text = [p for p in files
            if p.suffix.lower() in TEXT_SUFFIXES]
    frac = (len(text) / len(files)) if files else 0.0
    met = bool(files) and frac >= OPEN_FORMAT_THRESHOLD
    return ("met" if met else "not-met", "verified-in-tree",
            [f"files under wiki/: {len(files)}",
             f"plain-text formats: {len(text)} "
             f"({frac:.1%})"],
            f"{frac:.1%} of the compiled layer is plain "
            f"text (floor {OPEN_FORMAT_THRESHOLD:.0%}).")


def check_decision_records(root, today):
    n = _count_lines(
        root / "evaluation" / "decisions-register.jsonl")
    synth = root / "wiki" / "syntheses"
    pages = [p.name for p in synth.glob("*decision*.md")] \
        if synth.is_dir() else []
    met = n >= 1 and bool(pages)
    return ("met" if met else "not-met", "verified-in-tree",
            [f"evaluation/decisions-register.jsonl "
             f"({n} lines)",
             "wiki/syntheses/ decisions pages: "
             + (", ".join(sorted(pages)) or "none")],
            "The decision register and its compiled "
            "pages stand.")


CHECKS = {
    "raw_layer": check_raw_layer,
    "backups": check_backups,
    "compile_stamps": check_compile_stamps,
    "identifier_registers": check_identifier_registers,
    "program_headers": check_program_headers,
    "licence_file": check_licence_file,
    "test_suite": check_test_suite,
    "overview_docs": check_overview_docs,
    "canonical_home": check_canonical_home,
    "filings_critique": check_filings_critique,
    "standard_layout": check_standard_layout,
    "file_names": check_file_names,
    "root_tidy": check_root_tidy,
    "version_control": check_version_control,
    "changelog": check_changelog,
    "checkpoints": check_checkpoints,
    "open_formats": check_open_formats,
    "decision_records": check_decision_records,
}


# -- the run -----------------------------------------------------------------

def build_report(root: Path, today: date, checklist: dict):
    results = []
    for prac in checklist["practices"]:
        kind = prac["check"]
        base = {"id": prac["id"],
                "category": prac["category"],
                "statement": prac["statement"],
                "paper": prac["paper"],
                "evidence_rule": prac["evidence_rule"]}
        if kind == "manual":
            base.update({
                "verdict": "manual", "basis": "manual",
                "evidence": [prac["evidence_rule"]],
                "detail": "A judgement call — the checker "
                          "states the question and does "
                          "not guess the answer."})
        elif kind == "not-applicable":
            base.update({
                "verdict": "not-applicable",
                "basis": "not-applicable",
                "evidence": [prac["evidence_rule"]],
                "detail": "Standing reason recorded in "
                          "the checklist definition."})
        else:
            fn = CHECKS.get(kind)
            if fn is None:
                raise ValueError(
                    f"checklist names unknown check "
                    f"{kind!r} for practice {prac['id']}")
            verdict, basis, evidence, detail = fn(root,
                                                  today)
            base.update({"verdict": verdict,
                         "basis": basis,
                         "evidence": evidence,
                         "detail": detail})
        results.append(base)
    counts = {v: 0 for v in checklist["verdicts"]}
    for r in results:
        counts[r["verdict"]] += 1
    return {
        "tool": "scripts/wiki_good_enough.py",
        "kind": "good-enough-practices-report",
        "as_of": today.isoformat(),
        "checklist_version": checklist["version"],
        "source": checklist["source"],
        "counts": counts,
        "practices": results,
    }


def render_md(report: dict) -> str:
    c = report["counts"]
    lines = [
        "# Good-enough practices — scoreboard", "",
        f"As of {report['as_of']} — generated by "
        f"`scripts/wiki_good_enough.py` against the "
        f"checklist in "
        f"`evaluation/good-enough-checklist.json` "
        f"(v{report['checklist_version']}). The checker "
        f"judges the tree by its artefacts, never by "
        f"documents claiming a practice is done.", "",
        f"**Met {c['met']} · Not met {c['not-met']} · "
        f"Manual {c['manual']} · "
        f"Not applicable {c['not-applicable']}** "
        f"of {sum(c.values())} practices.", "",
        f"> {report['source']}", "",
    ]
    cat = None
    for r in report["practices"]:
        if r["category"] != cat:
            cat = r["category"]
            lines += [f"## {cat}", ""]
        lines += [
            f"### {r['id']} — {r['verdict'].upper()}"
            f" ({r['basis']})", "",
            f"{r['statement']}", "",
            f"- Paper: {r['paper']}",
            f"- Evidence rule: {r['evidence_rule']}",
        ]
        for e in r["evidence"]:
            lines.append(f"- Evidence: {e}")
        lines += [f"- Finding: {r['detail']}", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Good-enough-practices checker")
    ap.add_argument("command", choices=["check"])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--today")
    ap.add_argument("--checklist", type=Path,
                    default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    today = (date.fromisoformat(args.today)
             if args.today else date.today())
    checklist_path = args.checklist or (
        args.root / "evaluation" /
        "good-enough-checklist.json")
    try:
        checklist = json.loads(checklist_path.read_text(
            encoding="utf-8"))
        report = build_report(args.root, today, checklist)
    except (OSError, ValueError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if args.out:
        args.out.with_suffix(".json").write_text(
            json.dumps(report, ensure_ascii=False,
                       sort_keys=True, indent=1) + "\n",
            encoding="utf-8")
        args.out.with_suffix(".md").write_text(
            render_md(report), encoding="utf-8")
        print(f"wrote {args.out}.json + {args.out}.md")
    if args.json:
        print(json.dumps(report, ensure_ascii=False,
                         sort_keys=True, indent=1))
    else:
        c = report["counts"]
        print(f"good-enough: met {c['met']} · "
              f"not-met {c['not-met']} · "
              f"manual {c['manual']} · "
              f"not-applicable {c['not-applicable']}")
        for r in report["practices"]:
            if r["verdict"] == "not-met":
                print(f"  NOT-MET {r['id']}: "
                      f"{r['detail']}")
    return 1 if report["counts"]["not-met"] else 0


if __name__ == "__main__":
    sys.exit(main())
