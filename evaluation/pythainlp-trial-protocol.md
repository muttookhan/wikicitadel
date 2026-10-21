# PyThaiNLP trial — protocol

Marathon R11 lane BB (ideas board line 158, Tier A). PyThaiNLP
(Thailand, Apache-2.0), bounded external-tool trial of Thai
tokenisation/segmentation — not a library integration; the
library lives in a venv OUTSIDE the trees and no dependency is
added to either tree. In-tree deliverables are this protocol,
the evidence record (`evaluation/pythainlp-trial-evidence.json`),
and the wrapper `scripts/wiki_pythainlp_trial.py`.

## Procedure

1. Obtain the library outside the trees:
   `python3 -m venv <lane>/trials/pythainlp/venv` then
   `<venv>/bin/pip install pythainlp python-crfsuite`
   (python-crfsuite is the optional dependency of the default
   `crfcut` sentence segmenter; without it `sent_tokenize`
   fails with ModuleNotFoundError — that failure was hit and
   cured by the install during the R11 run, and is recorded
   here rather than hidden). If installation fails, record the
   exact door failure — that is a complete deliverable.
2. Take a held sample Thai document (lane trials area, written
   for this trial; its sha256 is in the evidence).
3. Run: `python3 scripts/wiki_pythainlp_trial.py run --sample
   <sample> --python <venv>/bin/python --result <result.json>
   --evidence <evidence.json>` — the runner segments sentences
   (`sent_tokenize`, default engine) and tokenises words
   (`word_tokenize`, engine `newmm`).
4. Acceptance: the result artefact exists in the lane trials
   area, its sha256 is recorded in the evidence, and the token
   list is inspectable there.
