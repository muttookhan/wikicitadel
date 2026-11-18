# kraken OCR trial — protocol (Marathon R10 lane BA, Tier A)

kraken (Apache-2.0), external tool — installed in a venv OUTSIDE the
trees; no runtime dependency is added to either tree.
Board line: "A kraken OCR trial — kraken in a venv against a bounded
set of already-held scans, ALTO/PageXML kept as ingest staging
outside the wiki."

## Boundaries
- The corpus check comes first: `raw/` is searched for held scans/
  images. If none are held, the trial runs on a synthetic test image
  generated for the trial and labelled synthetic everywhere.
- Inputs are copies / generated fixtures outside the trees; `raw/`
  is never modified. OCR output stays outside the trees as staging.
- Success = ALTO or PageXML output WITH coordinates for at least
  one input + the evidence record.

## Procedure
1. Create a venv outside the trees; `pip install kraken` (route
   TMPDIR to a roomy mount if /tmp is a small tmpfs — recorded in
   the evidence when it bites).
2. `kraken --version`; binarize + segment + OCR the bounded input
   set; write `.alto.xml` (or PageXML) beside the staging copies.
3. Verify the output parses as XML and contains coordinate-bearing
   elements (String/HPOS/VPOS or TextLine Coords).

Outcome and exact commands/errors: `evaluation/kraken-trial-evidence.json`.
