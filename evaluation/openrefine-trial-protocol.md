# OpenRefine bench trial — protocol

Marathon R10 lane BB (ideas board R8 research, Tier A). OpenRefine
(BSD-3-Clause), external bench tool on the Kopia precedent: the
tool and its Java runtime live OUTSIDE the trees; outputs stay
outside the trees; in-tree deliverables are this protocol, the
evidence record (`evaluation/openrefine-trial-evidence.json`),
and the wrapper `scripts/wiki_openrefine_trial.py`.

## Procedure

1. Obtain OpenRefine (official release tarball) + a JRE outside
   the trees; record versions in the evidence.
2. Copy a tabular/bibliographic working file from the corpus
   into the trials area (never clean an in-tree original).
3. Run: `python3 scripts/wiki_openrefine_trial.py run --refine
   <refine> --input <copy> --operations <ops.json> --work <dir>
   --evidence <file>` — headless server on a throwaway port /
   workspace, create project, apply operations, export cleaned
   rows AND the operation history (get-operations) alongside the
   output, so the transformation is citable.
4. The evidence records input hash, operations applied, output
   hash, and the history artefact location. A door failure is
   recorded exactly in the evidence and is never a trial result.
