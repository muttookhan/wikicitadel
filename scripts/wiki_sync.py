#!/usr/bin/env python3
"""Git sync helper for a wiki repository (gap 11, scoped form).

Wraps the custody discipline in one tool: pull before work, push on
integration, and NEVER resolve a divergence or a conflict silently.
Real-time co-editing is deliberately out of scope — git remains the
sync layer; this tool makes its state legible and its failures loud.

Subcommands:
  status            branch, ahead/behind vs the remote, dirty files,
                    and any conflicted paths (exit 1 if conflicted)
  pull              fetch + fast-forward only; a diverged branch is
                    reported, never merged or rebased (exit 2)
  push              push the current branch (refuses while conflicted)
  sync              pull, then push
  bundle            write ONE self-contained offline HTML reading
                    bundle (page index + full page texts + in-page
                    search, no external assets) for phone reading;
                    refuses while the tree is conflicted

Stdlib only. All git output is passed through; nothing is hidden.
"""
import argparse
import html
import re
import subprocess
import sys
from pathlib import Path


def git(root, *args, check=False):
    r = subprocess.run(["git", "-C", str(root), *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return r


def conflicted_paths(root):
    """Paths with unmerged entries, from git status porcelain."""
    r = git(root, "status", "--porcelain")
    out = []
    for line in r.stdout.splitlines():
        code = line[:2]
        if "U" in code or code in ("AA", "DD"):
            out.append(line[3:].strip())
    return out


def sync_state(root, remote="origin"):
    """Return a dict describing branch/ahead/behind/conflict state."""
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    git(root, "fetch", remote)
    counts = git(root, "rev-list", "--left-right", "--count",
                 f"HEAD...{remote}/{branch}").stdout.split()
    ahead = int(counts[0]) if len(counts) == 2 else 0
    behind = int(counts[1]) if len(counts) == 2 else 0
    dirty = [ln[3:].strip() for ln in
             git(root, "status", "--porcelain").stdout.splitlines() if ln.strip()]
    return {"branch": branch, "ahead": ahead, "behind": behind,
            "dirty": dirty, "conflicts": conflicted_paths(root)}


def cmd_status(root, remote):
    st = sync_state(root, remote)
    print(f"branch: {st['branch']}  ahead: {st['ahead']}  behind: {st['behind']}")
    if st["dirty"]:
        print(f"dirty files: {len(st['dirty'])}")
    if st["conflicts"]:
        print("CONFLICTED (resolve by hand; this tool never auto-resolves):")
        for p in st["conflicts"]:
            print(f"  {p}")
        return 1
    print("no conflicts")
    return 0


def cmd_pull(root, remote):
    st = sync_state(root, remote)
    if st["conflicts"]:
        print("refusing to pull: unresolved conflicts present", file=sys.stderr)
        return 1
    if st["ahead"] and st["behind"]:
        print(f"DIVERGED: local is {st['ahead']} ahead and {st['behind']} behind "
              f"{remote}/{st['branch']}. No merge or rebase attempted — "
              "reconcile by hand.", file=sys.stderr)
        return 2
    if st["behind"] == 0:
        print("already up to date")
        return 0
    r = git(root, "merge", "--ff-only", f"{remote}/{st['branch']}")
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


def cmd_push(root, remote):
    if conflicted_paths(root):
        print("refusing to push: unresolved conflicts present", file=sys.stderr)
        return 1
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    r = git(root, "push", remote, branch)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


# ----------------------------------------------------------------
# Offline reading bundle (mobile): ONE self-contained HTML file.
# ----------------------------------------------------------------

def _page_title(text, stem):
    """A page's title: frontmatter title, else first H1, else stem."""
    fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if fm:
        m = re.search(r"^title:\s*[\"']?(.*?)[\"']?\s*$", fm.group(1), re.M)
        if m and m.group(1):
            return m.group(1)
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else stem


def collect_pages(root):
    """Every compiled page under wiki/, in deterministic order:
    [{path (repo-relative), title, text}] sorted by path."""
    root = Path(root)
    wiki = root / "wiki"
    pages = []
    if wiki.is_dir():
        for p in sorted(wiki.rglob("*.md")):
            if p.is_file():
                text = p.read_text(encoding="utf-8", errors="replace")
                pages.append({"path": str(p.relative_to(root)),
                              "title": _page_title(text, p.stem),
                              "text": text})
    return pages


_BUNDLE_CSS = (
    "body{font-family:system-ui,sans-serif;margin:1rem auto;"
    "max-width:42rem;padding:0 1rem;line-height:1.6}"
    "article{border-top:1px solid #999;margin-top:2rem}"
    "pre{white-space:pre-wrap;word-wrap:break-word}"
    "#q{width:100%;font-size:1.1rem;padding:.5rem}")


def build_bundle(root):
    """The bundle HTML for a tree: page index + full page texts +
    in-page search, inline CSS/JS only, NO external assets, and
    deterministic (sorted pages, no timestamps) — the same tree
    always builds the byte-identical bundle."""
    pages = collect_pages(root)
    parts = ["<!DOCTYPE html>", '<html lang="en"><head>',
             '<meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, '
             'initial-scale=1">',
             "<title>Wiki reading bundle</title>",
             f"<style>{_BUNDLE_CSS}</style></head><body>",
             "<h1>Wiki reading bundle</h1>",
             '<input id="q" type="search" placeholder="Search pages" '
             'aria-label="Search pages">',
             "<nav><ul>"]
    for i, pg in enumerate(pages):
        parts.append(f'<li><a href="#p{i}">'
                     f'{html.escape(pg["title"])}</a> '
                     f'({html.escape(pg["path"])})</li>')
    parts.append("</ul></nav>")
    for i, pg in enumerate(pages):
        parts.append(f'<article id="p{i}" data-title="'
                     f'{html.escape(pg["title"], quote=True)}">')
        parts.append(f"<h2>{html.escape(pg['title'])}</h2>")
        parts.append(f"<p><em>{html.escape(pg['path'])}</em></p>")
        parts.append(f"<pre>{html.escape(pg['text'])}</pre>")
        parts.append("</article>")
    parts.append(
        "<script>var q=document.getElementById('q');"
        "q.addEventListener('input',function(){"
        "var needle=q.value.toLowerCase();"
        "document.querySelectorAll('article').forEach(function(a){"
        "a.style.display=(!needle||a.textContent.toLowerCase()"
        ".indexOf(needle)>=0)?'':'none';});});</script>")
    parts.append("</body></html>")
    return "\n".join(parts) + "\n", pages


def cmd_bundle(root, out=None):
    """Write the reading bundle. Refuses while the tree is
    conflicted — the same custody check push uses."""
    if conflicted_paths(root):
        print("refusing to bundle: unresolved conflicts present",
              file=sys.stderr)
        return 1
    text, pages = build_bundle(root)
    dest = Path(out) if out else Path(root) / "wiki-bundle.html"
    dest.write_text(text, encoding="utf-8")
    print(f"bundle: {dest} ({len(pages)} pages, {len(text)} bytes)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command",
                    choices=["status", "pull", "push", "sync", "bundle"])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--out", default=None,
                    help="bundle output path (bundle command only; "
                    "default: <root>/wiki-bundle.html)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if args.command == "bundle":
        return cmd_bundle(root, args.out)
    if args.command == "status":
        return cmd_status(root, args.remote)
    if args.command == "pull":
        return cmd_pull(root, args.remote)
    if args.command == "push":
        return cmd_push(root, args.remote)
    rc = cmd_pull(root, args.remote)
    if rc != 0:
        return rc
    return cmd_push(root, args.remote)


if __name__ == "__main__":
    sys.exit(main())
