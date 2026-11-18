#!/usr/bin/env python3
"""wiki_transcribe.py — offline transcription seam (Marathon R3,
Tier B bundle "Graph, portal and capture forms", row 8).

Patterns: Handy / Buzz — fully OFFLINE transcription of recordings
the owner selects (both MIT; re-implemented seam from the idea).
Watch-folder mode stays OFF: only files named on the command line
(or passed to `transcribe()`) are ever processed. NO model
downloads, NO network — the engine is a local callable.

Engine interface: `engine(path) -> str` returning the transcript
text. The DEFAULT engine is unconfigured and refuses cleanly with
instructions (exit path status "refused"): a deployment configures
a local engine by dropping a `transcribe-engine.json` next to the
tree root naming a local command template, e.g.
{"command": ["whisper-cpp", "-f", "{file}", "-otxt", "-of", "{out}"]}
— the seam runs it locally; no engine ships with this build, so
the default behaviour everywhere is the clean refusal.

A successful run produces a transcript SOURCE file: markdown with
provenance frontmatter (source recording, engine name, transcribed
timestamp, `origin: offline-transcription`) written under
--out-dir (default raw/sources/transcripts/), ready for the normal
ingest path. The recording itself is never modified.

Exit 0 on a completed run (refusal is a stated result, printed as
JSON), 2 on a missing input file. Tests inject a fake engine.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

AUDIO_VIDEO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".mp4",
                    ".mov", ".mkv", ".webm"}

REFUSAL = ("no transcription engine configured. Transcription is "
           "offline-only in this wiki: install a local engine and "
           "name it in transcribe-engine.json at the tree root, "
           "e.g. {\"command\": [\"whisper-cpp\", \"-f\", \"{file}\", "
           "\"-otxt\", \"-of\", \"{out}\"]}. Nothing was downloaded "
           "and no network was used.")


class EngineUnconfigured(Exception):
    pass


def configured_engine(root):
    cfg_path = Path(root) / "transcribe-engine.json"
    if not cfg_path.exists():
        return None

    def engine(path):
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cmd = [part.replace("{file}", str(path))
               for part in cfg["command"]]
        subprocess.run(cmd, check=True, capture_output=True)
        out_txt = Path(str(path) + ".txt")
        return out_txt.read_text(encoding="utf-8") if out_txt.exists() else ""

    engine.engine_name = "configured-local"
    return engine


def transcribe(path, out_dir, engine=None, engine_name="fake",
               transcribed_at=""):
    p = Path(path)
    if p.suffix.lower() not in AUDIO_VIDEO_EXTS:
        return {"source": str(p), "status": "unsupported",
                "note": "not an audio/video file"}
    if engine is None:
        return {"source": str(p), "status": "refused", "note": REFUSAL}
    text = engine(p)
    dest = Path(out_dir) / (p.stem + "-transcript.md")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        "---\n"
        f'title: "Transcript — {p.name}"\n'
        "type: source\n"
        f"sources: [\"{p}\"]\n"
        "tags: [transcript]\n"
        "origin: offline-transcription\n"
        f"engine: {engine_name}\n"
        f"transcribed: {transcribed_at}\n"
        "---\n\n"
        f"# Transcript — {p.name}\n\n"
        f"{text.rstrip()}\n",
        encoding="utf-8")
    return {"source": str(p), "status": "transcribed",
            "transcript": str(dest), "engine": engine_name}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--transcribed-at", default="")
    ns = ap.parse_args(argv)
    for f in ns.files:
        if not Path(f).exists():
            print(f"missing: {f}", file=sys.stderr)
            return 2
    engine = configured_engine(ns.root)
    out = Path(ns.out_dir) if ns.out_dir else \
        Path(ns.root) / "raw" / "sources" / "transcripts"
    results = [transcribe(f, out, engine,
                          getattr(engine, "engine_name", "configured"),
                          ns.transcribed_at) for f in ns.files]
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
