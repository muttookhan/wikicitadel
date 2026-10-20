---
title: "%:title"
capture_kind: filing
captured: %U
capture_date: %:date
captured_by: %:by
provenance: %a
destination: %:destination
status: draft
confidence: observed
sources: []
tags: []
# TODO (capture) — sensitivity: answer before ingest. One of
# public | internal | personal | family-sensitive | export-only |
# credential-adjacent (evaluation/sensitivity.json). While this
# line stands unanswered the draft is UNCLASSIFIED, and the
# ingest converter refuses unclassified material a home in raw/
# The compile stamp below stays empty for the same
# reason: a capture is not yet a compile.
sensitivity: TODO
compiled_prompt:
compiled_converter:
compiled_date:
---

<!-- CAPTURE TEMPLATE — filing.
     The block below is a DRAFT of a WIKI FILING in the standing
     [[agent-filing-order]] shape — the filing order's own field
     grammar, not capture prompts. This draft is not a filing
     until it is SENT through the filings channel (email to the wiki's filings inbox, e.g. you@example.com); on pickup it is preserved verbatim
     under raw/filings/<agent>/, ingested through the gateway and
     entered on the sender's ledger page. The capture tool
     writes NONE of that: it stages this draft only, and never
     bypasses the flow. Rules from the filing order: never
     invent; mark guesses as guesses; decisions are the owner's
     alone — file them as "decision needed", never as decided;
     never put passwords, keys or codes in a filing. -->

%?

WIKI FILING
From: %:by
Date: %:date
Topic: %:title
Type: %^{fact / work done / decision needed / proposal / correction}
What happened: %^{short and concrete}
Evidence: %^{where this came from — file, link, message, or "my own run"}
Uncertain: %^{anything you are not sure of, or "nothing"}
Related: %^{people, projects, pages it touches}
