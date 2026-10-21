# Kiwi morphological-analysis trial protocol

Marathon R13 lane BB (ideas board line 200, Round 11 RB, Tier A).
Kiwi (bab2min/Kiwi, Apache-2.0) via the `kiwipiepy` Python binding.

## Procedure

1. Create a venv OUTSIDE the trees (lane trials area):
   `python3 -m venv venv`
2. With `PIP_CACHE_DIR` inside the lane workspace:
   `venv/bin/pip install kiwipiepy` (installed 0.24.1 +
   kiwipiepy_model 0.24.0 in this run).
3. Held sample: three Korean sentences written for this trial
   (recorded in the evidence with its sha256; the sample lives in
   the lane trials area, not in the trees).
4. Run: `scripts/wiki_kiwi_trial.py run --sample <sample>
   --evidence evaluation/kiwi-trial-evidence.json
   --python <venv>/bin/python --work-dir <trials area>`
   The wrapper writes a fixed runner into the trials area, runs
   tokenisation + sentence splitting there, and records token
   count, sentence count, the result hash and the tool version.

## Acceptance

- Evidence `ran: true` with token/sentence counts and hashes, or
  an honest `door_failure` with stage, command and exact error.
- Nothing Korean-sample-derived is committed except the evidence
  record; the venv and result JSON stay outside the trees (the
  result hash binds them).
