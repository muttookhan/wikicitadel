#!/usr/bin/env python3
"""Local filesystem watcher — Black Box Door C (design §5.2).

SUPPLEMENTARY capture for direct filesystem work on the maintainer
machine that bypasses the gateway. Standalone script. Installing
it as a service is an owner gate decision; the shipped
`wikicitadel-watcher.service` is a template unit (fill in your
paths), and in the reference deployment it runs as a systemd user
service with its state dir under wiki/access/.

Honesty rules from the design, implemented literally:
- attribution is weak and labelled: every change entry carries
  attribution "unattributed-local" (a process name is recorded only
  if the host exposes one — polling cannot, so `process` stays null);
- read capture is best-effort/write-focused — this watcher records
  create/modify/move/delete only and does not pretend to record reads;
- .git/ internals, generated caches, and the ledger/state paths
  themselves are excluded (no feedback loops);
- a restart writes a visible GAP MARKER (last heartbeat, restart
  time) into the watcher ledger instead of leaving a silent hole.

Polling snapshot/diff (stdlib only). Chain rules are the same as the
gateway ledger (gateway.ledger), in its own file watcher-YYYY.jsonl.

Usage:
  python3 watcher.py --root <tree> --state-dir <dir> --once
  python3 watcher.py --root <tree> --state-dir <dir> --interval 5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway.ledger import Ledger, git_head, utcnow  # noqa: E402

HASH_CAP = 8_000_000
EXCLUDED_DIRS = {".git", "__pycache__", ".mypy_cache", ".pytest_cache"}


def snapshot(root: Path, exclude: set[Path]) -> dict:
    state = {}
    for path in sorted(root.rglob("*")):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        rp = path.resolve()
        if rp in exclude or any(str(rp).startswith(str(e) + "/") for e in exclude):
            continue
        if not path.is_file():
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        digest = None
        if st.st_size <= HASH_CAP:
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                digest = None
        rel = str(path.relative_to(root))
        state[rel] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": digest}
    return state


class Watcher:
    def __init__(self, root: Path, state_dir: Path):
        self.root = root.resolve()
        self.state_dir = state_dir.resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / "watcher-state.json"
        ledger_file = self.state_dir / f"watcher-{utcnow()[:4]}.jsonl"
        self.ledger = Ledger(ledger_file, id_prefix="wc", wiki_root=self.root)
        self.exclude = {self.state_dir, self.ledger.path.resolve().parent}
        self.previous: dict = {}
        self._started = False
        self._baseline_pending = False

    def start(self) -> None:
        """Begin a run: genesis if new, gap marker if restarting."""
        if self.ledger.seq < 0:
            self.ledger.append_genesis("watcher/1", str(self.root))
        if self.state_file.exists():
            prev = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.previous = prev.get("snapshot", {})
            self.ledger.append(
                {
                    "actor": "local-watcher",
                    "auth_method": "none",
                    "client": "watcher.py",
                    "session_id": "watcher",
                    "task_ref": None,
                    "direction_source": {"kind": "approved-workflow", "ref": "door-c"},
                    "action": "watcher_gap",
                    "tool": None,
                    "files_read": [],
                    "files_written": [],
                    "result": "allow",
                    "commit_shas": [],
                    "observer": "local-watcher",
                    "last_heartbeat": prev.get("heartbeat"),
                    "restart_ts": utcnow(),
                    "git_head": git_head(self.root),
                }
            )
        else:
            # First ever run: the first tick establishes the baseline
            # silently — files that already exist were not created
            # under observation and must not be reported as creates.
            self._baseline_pending = True
        self._started = True

    def tick(self) -> list[dict]:
        if not self._started:
            self.start()
        current = snapshot(self.root, self.exclude)
        if self._baseline_pending:
            self._baseline_pending = False
            self.previous = current
            self.state_file.write_text(
                json.dumps({"heartbeat": utcnow(), "snapshot": current}, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return []
        events = []
        prev_paths = set(self.previous)
        cur_paths = set(current)
        for rel in sorted(cur_paths - prev_paths):
            events.append(self._event("create", rel, current[rel]))
        for rel in sorted(prev_paths - cur_paths):
            events.append(self._event("delete", rel, self.previous[rel]))
        for rel in sorted(cur_paths & prev_paths):
            if current[rel] != self.previous[rel]:
                events.append(self._event("modify", rel, current[rel]))
        self.previous = current
        self.state_file.write_text(
            json.dumps({"heartbeat": utcnow(), "snapshot": current}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return events

    def _event(self, kind: str, rel: str, info: dict) -> dict:
        return self.ledger.append(
            {
                "actor": "local-watcher",
                "auth_method": "none",
                "client": "watcher.py",
                "session_id": "watcher",
                "task_ref": None,
                "direction_source": {"kind": "approved-workflow", "ref": "door-c"},
                "action": "watcher_event",
                "tool": None,
                "files_read": [],
                "files_written": [rel] if kind != "delete" else [],
                "result": "allow",
                "commit_shas": [],
                "observer": "local-watcher",
                "event_kind": kind,
                "path": rel,
                "size": info.get("size"),
                "content_sha256": info.get("sha256"),
                "process": None,
                "attribution": "unattributed-local",
            }
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="watcher")
    parser.add_argument("--root", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true", help="single snapshot/diff pass, then exit")
    args = parser.parse_args(argv)
    watcher = Watcher(Path(args.root), Path(args.state_dir))
    watcher.start()
    if args.once:
        events = watcher.tick()
        print(json.dumps({"events": len(events)}))
        return 0
    try:
        while True:
            watcher.tick()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
