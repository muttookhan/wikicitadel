# CETEIcean rendering prototype — protocol (Marathon R10 lane BA, Tier A)

CETEIcean (BSD-2-Clause) — pattern only, nothing vendored.
Board line: "A CETEIcean rendering prototype — one reversible
prototype page rendering a held TEI file (e.g. a GROBID output)
without transforming the source."

## Contract
- The prototype page lives in the lane workspace (trial staging),
  NOT wired into the Lens. It is clearly marked PROTOTYPE.
- Rendering is read-only: the page fetches/parses the TEI and maps
  elements to CETEI-style custom elements in the browser; the TEI
  file on disk is never written (verify by hash before/after).
- Input preference: a real GROBID TEI output if the GROBID trial
  produced one; otherwise a TEI-shaped fixture created for the
  trial and labelled FIXTURE in its own header comment.
- Reversible: delete the prototype folder; nothing else changes.

Outcome: `evaluation/ceteicean-prototype-evidence.json`.
