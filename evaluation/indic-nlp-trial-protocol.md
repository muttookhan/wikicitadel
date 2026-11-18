# Indic NLP normalisation trial — protocol

Marathon R11 lane BB (ideas board line 157, Tier A). Indic NLP
Library (India, MIT), external-tool trial only — not a library
integration; the library lives in a venv OUTSIDE the trees and
no dependency is added to either tree. In-tree deliverables are
this protocol, the evidence record
(`evaluation/indic-nlp-trial-evidence.json`), and the wrapper
`scripts/wiki_indic_nlp_trial.py`.

## Procedure

1. Obtain the library outside the trees:
   `python3 -m venv <lane>/trials/indic/venv` then
   `<venv>/bin/pip install indic-nlp-library`; record the
   version in the evidence. If installation fails, record the
   exact door failure — that is a complete deliverable; never
   claim an unrun trial.
2. Take a held sample Indic-language document (lane trials
   area, written for this trial; its sha256 is in the
   evidence).
3. Run: `python3 scripts/wiki_indic_nlp_trial.py run --sample
   <sample> --python <venv>/bin/python --result <result.json>
   --evidence <evidence.json>` — the runner normalises with the
   Hindi normaliser (`IndicNormalizerFactory`) and splits with
   `sentence_tokenize.sentence_split(..., lang="hi")`.
4. Acceptance: the result artefact exists in the lane trials
   area, its sha256 is recorded in the evidence, and the
   normalised text + sentence list are inspectable there.

## Notes from the R11 run

- Library 0.92 renamed the factory method
  (`create_normalizer` -> `get_normalizer`); the wrapper's
  runner accepts either spelling.
- Narrowing, recorded not hidden: the splitter returned a
  fifth, fragmentary segment (a lone closing quote) for the
  sample's quoted final sentence — segmentation of quoted
  speech is imperfect in this release.
