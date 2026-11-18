"""Consultation measurement — ai-engineering-spec §6.

Computed from the Black Box gateway ledger alone (plus staging
metadata for proposal citations), without interviewing any agent
(§6.3 pass/fail (c)). Per task = one gateway session.

Signals per task:
  consulted          >=1 search/read in the session
  read_before_write  first read/search ts < first staging/write ts
  citation_coverage  |cites ∩ in-session read set| / |cites|
  consultation_depth distinct pages read / pages cited
                     (< 1 = citation without reading: integrity incident)
  gap_honesty        insufficient-evidence answers listing searched
                     lanes / all such answers — only computable when
                     Ask answers are ledgered with lane data; reported
                     as null (not faked) when the data does not exist.
"""
from __future__ import annotations

import json
from pathlib import Path

READ_ACTIONS = {"search", "read_page", "read_source", "graph_neighbors", "read_decision"}
WRITE_ACTIONS = {"stage_proposal", "promote", "handoff_create"}


def _session_tasks(entries: list[dict]) -> dict:
    tasks: dict[str, dict] = {}
    for e in entries:
        sid = e.get("session_id")
        if not sid or sid == "genesis":
            continue
        t = tasks.setdefault(
            sid,
            {
                "session_id": sid,
                "actor": e.get("actor"),
                "reads": set(),
                "read_events": 0,
                "first_read_seq": None,
                "first_write_seq": None,
                "proposal_ids": [],
            },
        )
        action = e.get("action")
        seq = e.get("seq")
        # Order is taken from the ledger sequence, not the wall clock:
        # ledger timestamps have one-second resolution, so two events
        # in the same second are unordered by ts but always ordered
        # by seq. read_before_write is therefore a seq comparison.
        if action in READ_ACTIONS:
            t["read_events"] += 1
            for f in e.get("files_read") or []:
                t["reads"].add(f)
            if t["first_read_seq"] is None:
                t["first_read_seq"] = seq
        if action in WRITE_ACTIONS:
            if t["first_write_seq"] is None:
                t["first_write_seq"] = seq
        if action == "stage_proposal":
            for f in e.get("files_written") or []:
                pid = Path(f).stem
                if pid.startswith("prop-"):
                    t["proposal_ids"].append(pid)
    return tasks


def compute_metrics(entries: list[dict], proposals: dict[str, dict]) -> dict:
    """proposals: proposal_id -> proposal metadata (for citations)."""
    tasks = _session_tasks(entries)
    per_identity: dict[str, dict] = {}
    for t in tasks.values():
        actor = t["actor"] or "unknown"
        rep = per_identity.setdefault(actor, {"identity": actor, "tasks": [], "violations": []})
        cites: list[str] = []
        for pid in t["proposal_ids"]:
            cites.extend((proposals.get(pid) or {}).get("cites") or [])
        cites_set = set(cites)
        consulted = t["read_events"] > 0
        rbw = None
        if t["first_write_seq"] is not None:
            rbw = bool(t["first_read_seq"] is not None and t["first_read_seq"] < t["first_write_seq"])
        coverage = None
        depth = None
        if cites_set:
            coverage = round(len(cites_set & t["reads"]) / len(cites_set), 4)
            depth = round(len(t["reads"]) / len(cites_set), 4)
        task_report = {
            "session_id": t["session_id"],
            "consulted": consulted,
            "read_before_write": rbw,
            "distinct_pages_read": len(t["reads"]),
            "pages_cited": len(cites_set),
            "citation_coverage": coverage,
            "consultation_depth": depth,
            "gap_honesty": None,
        }
        rep["tasks"].append(task_report)
        if not consulted:
            rep["violations"].append({"session_id": t["session_id"], "signal": "consulted",
                                      "detail": "task completed with zero wiki consultation"})
        if rbw is False:
            rep["violations"].append({"session_id": t["session_id"], "signal": "read_before_write",
                                      "detail": "first write precedes first read"})
        if coverage is not None and coverage < 0.9:
            rep["violations"].append({"session_id": t["session_id"], "signal": "citation_coverage",
                                      "detail": f"coverage {coverage} < 0.9"})
        if depth is not None and depth < 1:
            rep["violations"].append({"session_id": t["session_id"], "signal": "consultation_depth",
                                      "detail": f"depth {depth} < 1: citation without reading (integrity incident)"})
    return {"identities": per_identity}


def load_proposals(staging_dir: Path) -> dict:
    out = {}
    for sub in ("proposed", "quarantine"):
        d = Path(staging_dir) / sub
        if d.exists():
            for p in d.glob("prop-*.json"):
                try:
                    meta = json.loads(p.read_text(encoding="utf-8"))
                    out[meta["proposal_id"]] = meta
                except Exception:
                    continue
    return out
