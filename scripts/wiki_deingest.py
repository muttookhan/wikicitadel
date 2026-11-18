#!/usr/bin/env python3
"""wiki_deingest.py — the de-ingest cascade, plan-first.

Pattern: VectifyAI/OpenKB (Apache-2.0)
removes a document completely: its compiled pages, images,
registry entry, and index state. Our version is governed by this
wiki's own rules, which are stricter:

  - the tool runs --dry-run BY DEFAULT and produces a complete
    removal PLAN with a plan hash (SHA-256 of the canonical plan),
    the same shape the gateway's plan-hash authorisation binds;
  - it deletes NOTHING on a dry run, and on --execute it acts
    only with an owner authorisation record whose plan_sha256
    matches the recomputed plan exactly;
  - it NEVER touches raw/: the source file itself, its provenance
    manifest entry, and any assets under raw/ are listed in the
    plan as OWNER ACTIONS (raw is immutable to tooling, and only
    the owner removes his own sources);
  - history is never rewritten: wiki/log.md entries about the
    source stay; the plan says so.

Plan contents:
  remove_pages    wiki pages derived SOLELY from this source
  review_pages    wiki pages citing it among other sources
                  (they need edits, never automatic removal)
  index_entries   wiki/index.md lines pointing at removed pages
  pageindex       PageIndex artefacts for the source
  owner_actions   everything under raw/ + the manifest entry
  stale_reports   evaluation artefacts that mention the source

    python3 scripts/wiki_deingest.py raw/sources/<doc>.md
    python3 scripts/wiki_deingest.py raw/sources/<doc>.md \
        --execute --authorisation owner-auth.json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN_DIR = ROOT / "evaluation" / "deingest"


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fc = _load("wiki_factcheck")
wv = fc._load_validate()


def compute_plan(root: Path, target_ref: str) -> dict:
    target_path = fc.resolve_source(root, target_ref)
    if target_path is None:
        direct = root / target_ref
        target_path = direct if direct.is_file() else None
    if target_path is None or not target_path.is_file():
        raise SystemExit(f"deingest: source not found: {target_ref}")
    target_rel = target_path.relative_to(root).as_posix()

    remove_pages, review_pages = [], []
    wiki = root / "wiki"
    for p in sorted(wiki.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if rel in ("wiki/index.md", "wiki/log.md"):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        fields, _body = wv.parse_frontmatter(text)
        if not fields:
            continue
        resolved = set()
        for entry in wv.as_list(fields.get("sources")):
            rp = fc.resolve_source(root, entry)
            if rp is not None:
                resolved.add(rp.relative_to(root).as_posix())
        if target_rel not in resolved:
            continue
        if resolved == {target_rel}:
            remove_pages.append(rel)
        else:
            review_pages.append(rel)

    # index.md lines that point at pages slated for removal.
    index_entries = []
    index_path = wiki / "index.md"
    if index_path.is_file():
        stems = {Path(r).stem for r in remove_pages}
        for line in index_path.read_text(
                encoding="utf-8", errors="ignore").splitlines():
            if any(f"[[{s}]]" in line or f"[[{s}|" in line for s in stems):
                index_entries.append(line.strip())

    # PageIndex artefacts for this source.
    pageindex = []
    pi_dir = root / "evaluation" / "pageindex"
    if pi_dir.is_dir():
        import importlib.util as iu
        spec = iu.spec_from_file_location(
            "wiki_pageindex", ROOT / "scripts" / "wiki_pageindex.py")
        pi = iu.module_from_spec(spec)
        spec.loader.exec_module(pi)
        slug = pi.slug_for(target_path)
        for cand in (pi_dir / f"{slug}.json", pi_dir / f"{slug}.md"):
            if cand.is_file():
                pageindex.append(cand.relative_to(root).as_posix())

    # Assets referenced by removed pages that live under raw/:
    # owner actions (tooling never edits raw/).
    owner_actions = [f"remove the source itself: {target_rel} "
                     "(owner only — raw/ is immutable to tooling)"]
    manifest = root / "raw" / "sources" / "provenance-manifest.json"
    if manifest.is_file():
        try:
            mj = json.loads(manifest.read_text(encoding="utf-8"))
            if target_rel in (mj.get("files") or {}):
                owner_actions.append(
                    "drop its entry from raw/sources/"
                    "provenance-manifest.json and regenerate the "
                    "manifest (owner only)")
        except json.JSONDecodeError:
            pass
    asset_refs = set()
    for rel in remove_pages:
        body = (root / rel).read_text(encoding="utf-8", errors="ignore")
        for m in re.findall(r"!\[\[([^\]]+)\]\]|!\[[^\]]*\]\(([^)]+)\)",
                            body):
            ref = m[0] or m[1]
            if ref:
                asset_refs.add(ref)
    for ref in sorted(asset_refs):
        owner_actions.append(f"asset referenced by a removed page: "
                             f"{ref} (owner decides)")

    stale_reports = []
    ev = root / "evaluation"
    if ev.is_dir():
        for p in sorted(ev.rglob("*.json")):
            if "deingest" in p.parts or "pageindex" in p.parts:
                continue
            try:
                if target_rel in p.read_text(encoding="utf-8",
                                              errors="ignore"):
                    stale_reports.append(p.relative_to(root).as_posix())
            except OSError:
                continue

    plan = {
        "kind": "deingest-plan",
        "version": 1,
        "target": target_rel,
        "computed": str(date.today()),
        "remove_pages": sorted(remove_pages),
        "review_pages": sorted(review_pages),
        "index_entries": index_entries,
        "pageindex": sorted(pageindex),
        "owner_actions": owner_actions,
        "stale_reports": stale_reports,
        "history_note": "wiki/log.md and the access ledgers are "
                        "append-only history and are NOT rewritten "
                        "by a de-ingest.",
    }
    canonical = json.dumps(plan, sort_keys=True, ensure_ascii=False)
    plan["plan_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return plan


def execute_plan(root: Path, plan: dict, authorisation: dict) -> list[str]:
    """Perform the tool-side removals. The caller has already
    verified the authorisation against the plan hash. raw/ is
    never touched here — by construction there is no code path
    that deletes under raw/."""
    if authorisation.get("plan_sha256") != plan["plan_sha256"]:
        raise SystemExit("deingest: authorisation plan hash does not "
                         "match the computed plan — refusing")
    if authorisation.get("authorised_by") != "owner":
        raise SystemExit("deingest: authorisation must be by the owner")
    done = []
    for rel in plan["remove_pages"]:
        (root / rel).unlink()
        done.append(f"removed page {rel}")
    index_path = root / "wiki" / "index.md"
    if plan["index_entries"] and index_path.is_file():
        lines = index_path.read_text(encoding="utf-8").splitlines()
        drop = set(plan["index_entries"])
        kept = [ln for ln in lines if ln.strip() not in drop]
        index_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        done.append(f"removed {len(lines) - len(kept)} index entr(ies)")
    for rel in plan["pageindex"]:
        (root / rel).unlink()
        done.append(f"removed pageindex artefact {rel}")
    return done


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", help="repo-relative raw source path or slug")
    ap.add_argument("--execute", action="store_true",
                    help="perform the tool-side removals (needs "
                         "--authorisation with a matching plan hash)")
    ap.add_argument("--authorisation", default=None,
                    help="JSON file: {plan_sha256, authorised_by: owner}")
    ap.add_argument("--out-dir", default=str(PLAN_DIR))
    args = ap.parse_args(argv)
    plan = compute_plan(ROOT, args.source)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-",
                  Path(plan["target"]).stem.lower()).strip("-")
    plan_file = out_dir / f"{slug}-plan.json"
    plan_file.write_text(json.dumps(plan, indent=2, ensure_ascii=False)
                         + "\n", encoding="utf-8")
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    print(f"\nplan written to {plan_file} — plan_sha256 "
          f"{plan['plan_sha256']}")
    if not args.execute:
        print("dry-run: nothing was deleted. To execute, the owner "
              "authorises this exact plan hash, then re-run with "
              "--execute --authorisation <record>.")
        return 0
    if not args.authorisation:
        print("refused: --execute requires --authorisation",
              file=sys.stderr)
        return 2
    auth = json.loads(Path(args.authorisation).read_text(encoding="utf-8"))
    done = execute_plan(ROOT, plan, auth)
    for d in done:
        print(f"  {d}")
    print("owner actions remain (raw/ is never touched by tooling):")
    for a in plan["owner_actions"]:
        print(f"  - {a}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
