# Graph shape validation — SHACL-pattern report

SHACL-pattern validation (W3C SHACL / SHACL-AF pattern, house re-implementation): shapes target node classes and property annotations, never path lists. This report is NOT the output of a conformant SHACL processor; shapes.ttl beside it carries the same shapes for a real engine.

Corpus commit: a02b5394ba2cde30b72b0afc95e4d31513fcb3ac · triples validated: 2048 · canonical SHA-256: `911a82fc2bcdd5799e1a0f98fa802ffdae3ac33317ca48bd022be3c6b1befc0b`

**Conforms: False** · violations: 40

## Shapes

| Shape | Targets checked | Violations |
|---|---|---|
| wkshape:PageTypeShape | 40 | 0 |
| wkshape:PageTypeVocabularyShape | 2 | 0 |
| wkshape:RelationVocabularyShape | 101 | 0 |
| wkshape:DeclaredInverseShape | 5 | 0 |
| wkshape:EdgeProvenanceShape | 101 | 0 |
| wkshape:ClaimShape | 9 | 0 |
| wkshape:CitationShape | 12 | 0 |
| wkshape:TombstoneShape | 1 | 1 |
| wkshape:TagRegistrationShape | 39 | 39 |

## Violations

- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/automation · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/build · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/capture · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/decisions · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/demo · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/did · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/evaluation · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/founding · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/governance · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/graphify · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/i18n · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/identifiers · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/judging · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/kr-r1 · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/lead · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/lightmem · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/machinery · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/marathon · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/marathon-r3 · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/mcp · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/memory · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/people · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/proposals · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/purpose · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/ranking · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/record · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/registry · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/reme · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/retrieval · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/round-10 · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/round-11 · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/round-12 · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/round-13 · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/sage-wiki · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/search · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/sources · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/tools · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/triage · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TagRegistrationShape** · https://wikicitadel.example.org/tag/vanillaflava · skos:scopeNote — tag in use carries no skos:scopeNote — the export found no registry row to join it to (unregistered tag in use, or a registry row without a scopeNote)
- **wkshape:TombstoneShape** · https://wikicitadel.example.org/wiki/concepts/standing-approval.md · dcterms:isReplacedBy — tombstoned page declares no replacement in the graph (no page stands in dcterms:replaces to it — the graph form of its is-superseded-by declaration)

## Gaps — what this report cannot check

- Tombstone reason/date: AGENTS.md's tombstone rule also requires `tombstoned: <date>` and `tombstone_reason: <why>`; neither field is in the linked-data export's mapping table, so no triple carries them and that half of the rule cannot be checked over this export. (No page in the corpus is tombstoned today, so the gap is latent, not live.)
- Declared-inverse agreement is checked over the exported graph's direct triples; the exporter emits a declared pair together, so this shape guards the export's internal consistency and any future pipeline change — whether the two PAGES' frontmatter declarations agree is the wiki validator / lint's ground, not this report's.
- Citation resolution is checked against the corpus on disk at validation time (the resolve rule is about files); a validation run without a corpus root skips that clause and says so in its notes.
