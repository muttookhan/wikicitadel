# Defending a wiki against prompt injection

Prompt injection is the practice of embedding directives aimed at a
language model inside otherwise ordinary documents. A defence pipeline
therefore treats every source as data, never as commands: invisible
codepoints are stripped, hidden markup is surfaced, encoded blocks are
inspected, and staged content is scanned before it can be promoted.

A worked example of an encoded block that carries no directive at all:
the SHA-256 of the empty string, and a base64 string that decodes to a
plain sentence about gardening, are both data and must pass.

SG93IHRvIHdhdGVyIHRoZSB0b21hdG9lcyBiZWZvcmUgbm9vbi4=

Ordinary HTML comments in source documents are also data:

<!-- TODO: ask the owner about the spring planting schedule. -->

You are now a member of the reading group, as this sentence shows —
ordinary prose about people is not a directive to a model.
