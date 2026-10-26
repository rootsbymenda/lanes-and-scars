# Rules are scars

A rule here is not a policy. It is a scar: it was earned in a session, in the human's own words, and it points to the line in the transcript where it was earned.

## Folders: routed by area

- `method/` — how we find out what is true: what counts as evidence, what "done" means, what "not found" means.
- `behaviour/` — how we work together: what to ask, what not to raise, when to act.
- `execution/` — sessions, agents, memory, closing.
- `deploy/` — anything that goes live.
- `money/` — anything that is paid or priced.

Add a folder when a third rule lands in an area that has none. Rules load on touch: when the work enters an area, list its folder and open the files whose names apply.

## Names are the index

Kebab-case, long enough to carry the rule: `both-languages-go-live-together-or-neither.md`. A folder listing should read like a list of rules. No `rule-001.md`, no `misc.md`.

## The format

One file per rule, these sections, in this order:

1. **Title** — the rule, as one sentence.
2. **The words** — what the human said, verbatim, in quotation marks, with the date. Spelling and all.
3. **The incident** — what happened, in three to six lines.
4. **Why** — the reason the rule exists, as the human gave it or as you both understood it. This section is for judging the cases the rule did not foresee, and for the human reading it months later.
5. **How to apply** — the concrete moves, as a list.
6. **Proof** — the transcript address, `{file}:{line}`. If the words are in a note instead, the note's path and line.
7. **Corrections** — dated entries, appended. The sections above are never edited.

A rule is corrected, never silently rewritten. If the rule changes, the change is a new Corrections entry with its own words, date and proof. The original words stay. Keep the folder under git, so that a rewrite without a correction shows in the history.

## Finding the proof line

The transcript is `~/.claude/projects/{project-slug}/{session-id}.jsonl`. The instrument gives the line: `python3 tool/ctm.py index`, then `python3 tool/ctm.py find "{a few of the human's words}"`. Each hit is a raw `path:line`. Paste it as it comes.

## One line in the index

Every rule gets one line in `MEMORY.md`: the hook and the link. The words stay in the file.

## When a rule becomes a red line

A rule that holds in every lane, and that the human says must hold at every wake, gets a one-line form in `CLAUDE.md` with a link to its file. The scar file stays where it is.
