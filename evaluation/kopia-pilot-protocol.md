# Kopia adoption pilot — protocol + restore-test procedure

Marathon R9 lane BB (ideas board R7 research, Tier A). Kopia
(Apache-2.0) piloted for the checkpoint-witness / off-repo
snapshot tier. Status and evidence for this lane's own run:
`evaluation/kopia-pilot-evidence.json`.

## Boundaries

- The pilot copy is a SIDE-COPY only. It is never the backup
  of record — what counts as the backup of record remains
  the owner's decision.
- The existing Drive zip flow is untouched by this pilot.
- A pilot NEVER snapshots a real tree: `scripts/wiki_kopia_pilot.py`
  refuses its own repository root as a source. Copy the tree
  first, snapshot the copy.
- Kopia is an external binary living OUTSIDE the trees; no
  runtime dependency is added to either tree.

## Procedure (what the wrapper runs)

1. Obtain kopia (official release tarball) outside the trees
   and record `kopia --version`.
2. Make the pilot copy: `cp -a <tree> /tmp/<name>-copy`.
3. Run: `python3 scripts/wiki_kopia_pilot.py run
   --source /tmp/<name>-copy --work /tmp/kopia-pilot-work
   --kopia /path/to/kopia
   --evidence evaluation/kopia-pilot-evidence.json`
   The wrapper creates a throwaway filesystem repository
   under the work dir (pilot-only password, config/cache/log
   all under the work dir), snapshots the copy, restores the
   snapshot to a separate directory, and compares SHA-256
   hashes file-for-file against the source copy (.git
   excluded from the hash comparison).
4. A restore counts as VERIFIED only when the evidence JSON
   records `verified: true` with `hashes_match: true` and
   equal file counts. Any failure is recorded in the evidence
   with the failing step and its stderr tail — a door failure
   is a statement about the door, never a restore result.

## Restore test (manual equivalent)

```
export KOPIA_PASSWORD=<pilot password>
kopia repository connect filesystem --path <work>/repo
kopia snapshot list
kopia restore <snapshot-id> <separate-restore-dir>
# then compare hashes against the source copy
```
