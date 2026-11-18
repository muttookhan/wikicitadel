# Annotorious annotation prototype — protocol (Marathon R10 lane BA, Tier A)

Annotorious (BSD-3-Clause) — pattern only, nothing vendored, no
hosted service. Board line: "An Annotorious annotation prototype —
a reversible Lens/portal prototype storing annotations as JSON
files alongside (never inside) the images they annotate."

## Contract
- The prototype page lives in the lane workspace (trial staging),
  NOT wired into the Lens, and is clearly marked PROTOTYPE.
- Annotations are W3C Web Annotation JSON objects stored in a
  separate `.annotations.json` file ALONGSIDE the image; the image
  bytes are never modified (verify by hash before/after).
- The in-tree machinery is the shape checker:
  `scripts/wiki_annotation_check.py check FILE...` validates
  @context, type, id, target.source, and FragmentSelector xywh.
- Reversible: delete the prototype folder; nothing else changes.

Outcome: `evaluation/annotorious-prototype-evidence.json`.
