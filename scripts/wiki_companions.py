#!/usr/bin/env python3
"""wiki_companions.py — companion-source unification (Marathon R3,
Tier B bundle "Graph, portal and capture forms", row 4).

Pattern: pin-llm-wiki's companion-source unification (Apache-2.0;
re-implemented from the idea). Sources that are companions of ONE
work — the repo, the paper, and the talk of the same project — are
unified under a companion group record instead of living as three
unrelated source pages.

Register format (a plain JSON file, default
`wiki/companion-groups.json` — data in the files, never a DB):

    {"groups": [{"id": "slug", "work": "Human title",
                 "members": ["wiki/sources/a.md", ...],
                 "shared_ids": {"repo": "...", "doi": "..."}}]}

A source page declares its identifiers in frontmatter: `repo:`,
`doi:`, `project:` (a shared project slug), `talk:`/`paper:` URLs.
The grouper PROPOSES groups: source pages sharing a normalized
identifier (same repo URL, same DOI, same project slug) form one
proposed group. Proposals are printed (JSON) or written with
--write-proposals to a proposals file — the register itself is
only ever changed by a recorded human act (`apply` merges a
proposals file into the register, refusing overlaps).

Subcommands:
    propose [--sources-dir D] [--out FILE]
    check   [--register FILE]   validate a register: every group
                                has >= 2 existing members, no source
                                sits in two groups, ids are unique.
    apply   --proposals FILE [--register FILE]

CLI: --root defaults to the tree root. Exit 0 ok, 1 check failures,
2 missing inputs.
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ID_FIELDS = ("repo", "doi", "project", "talk", "paper")


def parse_frontmatter(text):
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fm = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            fm[m.group(1).lower()] = m.group(2).strip().strip('"\'')
    return fm


def normalize(field, value):
    v = value.strip().lower()
    if field in ("repo", "talk", "paper"):
        v = re.sub(r"^https?://(www\.)?", "", v).rstrip("/")
        v = re.sub(r"\.git$", "", v)
    if field == "doi":
        v = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", v)
    return v


def source_ids(path):
    fm = parse_frontmatter(Path(path).read_text(encoding="utf-8",
                                                errors="replace"))
    ids = {}
    for f in ID_FIELDS:
        if fm.get(f):
            ids[f] = normalize(f, fm[f])
    links = re.findall(r"https?://[^\s)\]]+",
                       Path(path).read_text(encoding="utf-8",
                                            errors="replace"))
    for link in links:
        n = normalize("repo", link)
        if "github.com" in n:
            ids.setdefault("repo", n)
    return fm, ids


def propose(sources_dir, root):
    """Union-find over shared identifiers: sources linked by ANY
    shared id (directly or through a bridge source) form one group."""
    by_key = defaultdict(list)
    titles, all_ids = {}, {}
    for p in sorted(Path(sources_dir).rglob("*.md")):
        fm, ids = source_ids(p)
        rel = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
        titles[rel] = fm.get("title", p.stem)
        all_ids[rel] = ids
        for f, v in ids.items():
            by_key[(f, v)].append(rel)
    parent = {rel: rel for rel in all_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    shared = {}
    for (field, value), members in sorted(by_key.items()):
        if len(members) < 2:
            continue
        for m in members[1:]:
            parent[find(m)] = find(members[0])
        shared.setdefault(members[0], {})[field] = value
    clusters = defaultdict(list)
    for rel in all_ids:
        clusters[find(rel)].append(rel)
    groups = []
    for root_rel, members in sorted(clusters.items()):
        if len(members) < 2:
            continue
        ids = {}
        for m in members:
            ids.update(shared.get(m, {}))
            for f, v in all_ids[m].items():
                if len(by_key[(f, v)]) > 1:
                    ids[f] = v
        anchor = ids.get("project") or ids.get("repo") or root_rel
        slug = re.sub(r"[^a-z0-9]+", "-",
                      anchor.split("/")[-1].lower()).strip("-")
        groups.append({
            "id": slug or "group",
            "work": titles[sorted(members)[0]],
            "members": sorted(members),
            "shared_ids": ids,
            "proposal_only": True,
        })
    return {"groups": groups}


def check(register_path, root):
    problems = []
    data = json.loads(Path(register_path).read_text(encoding="utf-8"))
    seen_ids, seen_members = set(), {}
    for g in data.get("groups", []):
        if g["id"] in seen_ids:
            problems.append(f"duplicate group id: {g['id']}")
        seen_ids.add(g["id"])
        if len(g.get("members", [])) < 2:
            problems.append(f"group {g['id']}: fewer than 2 members")
        for m in g.get("members", []):
            if m in seen_members:
                problems.append(f"{m} in two groups: {seen_members[m]} "
                                f"and {g['id']}")
            seen_members[m] = g["id"]
            if not (root / m).exists():
                problems.append(f"group {g['id']}: member missing: {m}")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose")
    p.add_argument("--sources-dir", default=None)
    p.add_argument("--out", default=None)
    c = sub.add_parser("check")
    c.add_argument("--register", default=None)
    a = sub.add_parser("apply")
    a.add_argument("--proposals", required=True)
    a.add_argument("--register", default=None)
    ns = ap.parse_args(argv)
    root = Path(ns.root)
    register = Path(ns.register) if getattr(ns, "register", None) \
        else root / "wiki" / "companion-groups.json"
    if ns.cmd == "propose":
        sdir = Path(ns.sources_dir) if ns.sources_dir \
            else root / "wiki" / "sources"
        if not sdir.is_dir():
            print(f"missing sources dir: {sdir}", file=sys.stderr)
            return 2
        result = propose(sdir, root)
        text = json.dumps(result, indent=2)
        if ns.out:
            Path(ns.out).write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0
    if ns.cmd == "check":
        if not register.exists():
            print(f"missing register: {register}", file=sys.stderr)
            return 2
        problems = check(register, root)
        print(json.dumps({"register": str(register), "ok": not problems,
                          "problems": problems}, indent=2))
        return 1 if problems else 0
    # apply
    if not Path(ns.proposals).exists():
        print(f"missing proposals: {ns.proposals}", file=sys.stderr)
        return 2
    props = json.loads(Path(ns.proposals).read_text(encoding="utf-8"))
    data = json.loads(register.read_text(encoding="utf-8")) \
        if register.exists() else {"groups": []}
    taken = {m for g in data["groups"] for m in g["members"]}
    added = []
    for g in props.get("groups", []):
        if taken & set(g["members"]):
            print(f"refused (member already grouped): {g['id']}",
                  file=sys.stderr)
            return 1
        g = {k: v for k, v in g.items() if k != "proposal_only"}
        data["groups"].append(g)
        added.append(g["id"])
    register.parent.mkdir(parents=True, exist_ok=True)
    register.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"applied": added, "register": str(register)},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
