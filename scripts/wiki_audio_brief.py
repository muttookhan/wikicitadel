#!/usr/bin/env python3
"""Audio-briefing script generator (gap 15, scoped form).

Turns a wiki page (or the Briefing's waiting items) into a timed,
spoken-style narration SCRIPT — plain text with section markers and
estimated durations — ready to hand to any TTS engine or to record.
The scoped form generates the script only: no audio is synthesised
(no TTS engine ships with the wiki), and the script says so in its
header rather than pretending to be an audio file.

Usage:
  python3 scripts/wiki_audio_brief.py wiki/concepts/example.md
  python3 scripts/wiki_audio_brief.py --page wiki/overview.md --out brief.txt

Reading speed assumption: 150 words/minute, stated in the output.
Stdlib only.
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WPM = 150


def strip_markdown(text):
    """Reduce markdown to speakable prose, conservatively."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("```"):
            continue
        s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)          # images -> alt
        s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)           # links -> text
        s = re.sub(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]",
                   lambda m: (m.group(2)[1:] if m.group(2) else m.group(1)), s)
        s = re.sub(r"\^\[cite:[^\]]*\]", "", s)                  # cite markers
        s = re.sub(r"[*_`#>]+", "", s)
        s = s.strip()
        if s and not s.startswith("---"):
            out.append(s)
    return out


def drop_frontmatter(text):
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def title_of(text, fallback):
    m = re.search(r"^title:\s*\"?([^\"\n]+)\"?\s*$", text, re.M)
    if m:
        return m.group(1).strip()
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else fallback


def build_script(title, lines, wpm=WPM):
    words = sum(len(s.split()) for s in lines)
    minutes = words / wpm
    header = [
        f"# Audio briefing script: {title}",
        f"# Estimated duration: {minutes:.1f} minutes at {wpm} wpm "
        f"({words} words). Script only — no audio is generated.",
        "",
        f"[OPEN] {title}.",
        "",
    ]
    body = []
    for s in lines:
        body.append(s)
        body.append("")
    return "\n".join(header + body + ["[END]"])


def script_for_page(path, root=ROOT):
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    text = p.read_text(encoding="utf-8")
    title = title_of(text, p.stem.replace("-", " "))
    lines = strip_markdown(drop_frontmatter(text))
    # drop the H1 line if it merely repeats the title
    lines = [s for s in lines if s.lower() != title.lower()]
    return build_script(title, lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("page", help="wiki page path (repo-relative or absolute)")
    ap.add_argument("--out", default=None, help="write here instead of stdout")
    args = ap.parse_args(argv)
    script = script_for_page(args.page)
    if args.out:
        Path(args.out).write_text(script + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(script)
    return 0


if __name__ == "__main__":
    sys.exit(main())
