# PySastrawi stemming trial — protocol

Marathon R11 lane BB (ideas board line 159, Tier A). PySastrawi
(Indonesia), bounded external-tool trial of Indonesian stemming
for retrieval over Indonesian/Malay sources — not a library
integration; the package lives in a venv OUTSIDE the trees and
no dependency is added to either tree. In-tree deliverables are
this protocol, the evidence record
(`evaluation/pysastrawi-trial-evidence.json`), and the wrapper
`scripts/wiki_pysastrawi_trial.py`.

## Licence trap (board line duty)

PySastrawi's CODE is MIT, but its bundled dictionary is
CC-BY-NC-SA 3.0 and must NOT be redistributed with either tree
— above all not the public tree. The dictionary therefore
stays inside the lane-workspace venv; only trial OUTPUTS
(stemmed text, per-word stem map) and the evidence record
enter the trees. Nothing from the installed package is copied
into a tree by this trial.

## Procedure

1. Obtain the package outside the trees:
   `python3 -m venv <lane>/trials/pysastrawi/venv` then
   `<venv>/bin/pip install PySastrawi`. If installation fails,
   record the exact door failure — that is a complete
   deliverable.
2. Take a held sample Indonesian document (lane trials area,
   written for this trial; its sha256 is in the evidence).
3. Run: `python3 scripts/wiki_pysastrawi_trial.py run --sample
   <sample> --python <venv>/bin/python --result <result.json>
   --evidence <evidence.json>` — the runner stems the sample
   (`StemmerFactory().create_stemmer().stem(...)`) and records
   a per-word stem map.
4. Acceptance: the result artefact exists in the lane trials
   area, its sha256 is recorded in the evidence, and the stem
   map is inspectable there.
