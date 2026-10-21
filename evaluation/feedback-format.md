# Feedback record format (TB4-11, PLUR pattern)

One JSON object per line (JSONL): `{"id","ts","source": ask|portal,"page","kind": thumbs_up|thumbs_down|correction,"text"?}`. Corrections require text. Validate/triage: `scripts/wiki_feedback_triage.py`. Fixtures only — not wired into the Ask door.
