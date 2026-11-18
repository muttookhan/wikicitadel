# Janome trial — protocol

Marathon R13 lane BA (ideas board line 198, Tier A). Janome
(Japan, Apache-2.0), bounded external-tool trial of Japanese
morphological tokenisation — not a library integration; the
library lives in a venv OUTSIDE the trees and no dependency
is added to either tree. In-tree deliverables are this
protocol, the evidence record
(`evaluation/janome-trial-evidence.json`), and the wrapper
`scripts/wiki_janome_trial.py`.

## Procedure

1. Obtain the library outside the trees:
   `python3 -m venv <lane>/trials/janome/venv` then
   `<venv>/bin/pip install janome`. If installation fails,
   record the exact door failure — that is a complete
   deliverable.
2. Take a held sample Japanese document (lane trials area,
   written for this trial; its sha256 is in the evidence).
3. Run: `python3 scripts/wiki_janome_trial.py run --sample
   <sample> --python <venv>/bin/python --result
   <result.json> --evidence <evidence.json>` — the runner
   tokenises the sample with Janome's `Tokenizer` and
   records each token's surface and part of speech.
4. Acceptance: the result artefact exists in the lane trials
   area, its sha256 is recorded in the evidence, and the
   token list is inspectable there.
