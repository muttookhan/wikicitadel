"""Black Box ledger — append-only, hash-chained event log (design §5.3).

Canonical serialisation: UTF-8 JSON, sorted keys, no insignificant
whitespace. entry_hash = SHA-256(prev_hash || canonical(entry without
entry_hash)). seq is monotonic within a ledger. The genesis entry
names the schema version, repository, and git HEAD at activation.

Tokens, secrets, file contents and full search/question text are
never stored: search entries carry a query hash + query length and
the result page IDs only.

The chain proves internal consistency only (Addendum 1); the anchor
step records the chain head into a file the maintainer commits into
the Azure-canonical git history, outside the writer's control.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

GENESIS_PREV = "0" * 64


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def entry_digest(prev_hash: str, entry_without_hash: dict) -> str:
    return hashlib.sha256(prev_hash.encode("utf-8") + canonical(entry_without_hash)).hexdigest()


def git_head(wiki_root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(wiki_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


class Ledger:
    """One hash-chained JSONL ledger file (gateway or watcher)."""

    def __init__(self, path: Path, id_prefix: str = "bb", wiki_root: Path | None = None):
        self.path = Path(path)
        self.id_prefix = id_prefix
        self.wiki_root = wiki_root
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seq = -1
        self.head = GENESIS_PREV
        if self.path.exists():
            last = None
            with self.path.open("rb") as fh:
                for line in fh:
                    if line.strip():
                        last = line
            if last is not None:
                entry = json.loads(last)
                self.seq = int(entry["seq"])
                self.head = entry["entry_hash"]

    @property
    def next_seq(self) -> int:
        return self.seq + 1

    def append(self, fields: dict) -> dict:
        seq = self.seq + 1
        entry = dict(fields)
        entry.setdefault("ts", utcnow())
        entry["seq"] = seq
        entry["entry_id"] = f"{self.id_prefix}-{seq:06d}"
        entry["prev_hash"] = self.head
        digest = entry_digest(self.head, entry)
        entry["entry_hash"] = digest
        with self.path.open("ab") as fh:
            fh.write(canonical(entry) + b"\n")
            fh.flush()
            import os

            os.fsync(fh.fileno())
        self.seq = seq
        self.head = digest
        return entry

    def append_genesis(self, schema_version: str, repository: str) -> dict:
        if self.seq >= 0:
            raise RuntimeError("ledger already has entries; genesis must be first")
        return self.append(
            {
                "actor": "system",
                "auth_method": "none",
                "client": "gateway",
                "session_id": "genesis",
                "task_ref": None,
                "direction_source": {"kind": "approved-workflow", "ref": "phase-3-activation"},
                "action": "genesis",
                "tool": None,
                "files_read": [],
                "files_written": [],
                "result": "allow",
                "commit_shas": [],
                "schema_version": schema_version,
                "repository": repository,
                "git_head": git_head(self.wiki_root) if self.wiki_root else None,
            }
        )


def read_entries(path: Path) -> list[dict]:
    entries = []
    with Path(path).open("rb") as fh:
        for line in fh:
            if line.strip():
                entries.append(json.loads(line))
    return entries


def verify_chain(path: Path) -> dict:
    """Recompute the chain. Returns {ok, entries, bad_seq, reason}."""
    prev = GENESIS_PREV
    count = 0
    try:
        entries = read_entries(path)
    except FileNotFoundError:
        return {"ok": False, "entries": 0, "bad_seq": None, "reason": "ledger file missing"}
    for entry in entries:
        seq = entry.get("seq")
        if seq != count:
            return {"ok": False, "entries": count, "bad_seq": seq,
                    "reason": f"seq discontinuity: expected {count}, found {seq}"}
        if entry.get("prev_hash") != prev:
            return {"ok": False, "entries": count, "bad_seq": seq,
                    "reason": "prev_hash does not match previous entry_hash"}
        body = {k: v for k, v in entry.items() if k != "entry_hash"}
        if entry_digest(prev, body) != entry.get("entry_hash"):
            return {"ok": False, "entries": count, "bad_seq": seq,
                    "reason": "entry_hash mismatch (content altered)"}
        prev = entry["entry_hash"]
        count += 1
    return {"ok": True, "entries": count, "bad_seq": None, "reason": None, "head": prev}


def anchor(ledger_path: Path, out_path: Path, wiki_root: Path | None) -> dict:
    """Record the chain head for commit into git (Addendum 1).

    Writes an anchor JSON file and returns it together with a
    git-trailer block the maintainer can place in the anchor commit.
    """
    result = verify_chain(ledger_path)
    if not result["ok"]:
        raise RuntimeError(f"refusing to anchor a broken chain: {result['reason']} at seq {result['bad_seq']}")
    record = {
        "schema": "blackbox-anchor/1",
        "ledger": Path(ledger_path).name,
        "seq": result["entries"] - 1,
        "entry_hash": result["head"],
        "entries": result["entries"],
        "git_head": git_head(wiki_root) if wiki_root else None,
        "anchored_at": utcnow(),
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    record["git_trailers"] = (
        f"Blackbox-Ledger: {record['ledger']}\n"
        f"Blackbox-Seq: {record['seq']}\n"
        f"Blackbox-Head: {record['entry_hash']}\n"
        f"Operation: anchor-blackbox-head"
    )
    return record
