# GROBID trial — protocol (Marathon R10 lane BA, Tier A)

GROBID (Apache-2.0), external tool — never vendored into the trees.
Board line: "A GROBID local trial — run GROBID on a bounded set of
already-held scholarly PDFs, output kept outside the wiki as ingest
staging until a human-checked sample passes." The bounded trial only;
a standing GROBID ingest sidecar is a separate Tier B question.

## Boundaries
- Docker is NOT installed in this VM; the Java-service path is used:
  a JRE obtained outside the trees + the GROBID service jar + grobid-home.
- Inputs are COPIES of already-held PDFs from `raw/sources/`; `raw/`
  is never modified. Outputs (TEI XML) stay OUTSIDE the trees in the
  lane trial staging area.
- Success = structured TEI output for at least one PDF + a
  human-checkable sample comparison recorded in the evidence file.

## Procedure
1. Record `docker --version` and `java -version` door checks.
2. Obtain a JRE (Temurin) outside the trees; verify `java -version`.
3. Obtain GROBID (release jars + grobid-home from the source archive)
   outside the trees.
4. Copy a bounded set of held PDFs (copies only) to the staging area.
5. Start the service with the staged grobid-home; POST each PDF to
   `/api/processFulltextDocument`; save the TEI responses outside the trees.
6. Human-checkable comparison: record, in the evidence, the TEI's
   title/authors against the PDF's visible first-page text.

Outcome and exact commands/errors: `evaluation/grobid-trial-evidence.json`.
An honest door failure is a complete result for this protocol; a trial
is claimed only when the evidence records TEI output on disk.
