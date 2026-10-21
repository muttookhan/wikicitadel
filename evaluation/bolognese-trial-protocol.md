# Bolognese metadata-conversion trial — protocol

Marathon R10 lane BB (ideas board R8 research, Tier A).
Bolognese (DataCite, MIT; Ruby gem), reversible CLI trial only —
not a library integration; Ruby is introduced nowhere inside
the trees. The gem lives OUTSIDE the trees; outputs and diffs
stay outside the trees; in-tree deliverables are this protocol,
the evidence record (`evaluation/bolognese-trial-evidence.json`),
and the wrapper `scripts/wiki_bolognese_trial.py`.

## Procedure

1. Obtain Ruby + `gem install bolognese` outside the trees;
   record versions in the evidence. If Ruby/gem installation
   fails, record the exact door failure — that is a complete
   deliverable; never claim an unrun trial.
2. Take a bounded set of held bibliographic records, one file
   per record (bolognese converts one record per invocation).
3. Run: `python3 scripts/wiki_bolognese_trial.py run --records
   <files...> --out-dir <dir> --evidence <file> --bolognese
   <exe>` — BibTeX -> CSL JSON (the 2.7.0 writer is named
   `citeproc`), with a before/after unified diff per record as
   the acceptance check.
