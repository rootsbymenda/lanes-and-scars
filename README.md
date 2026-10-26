# Lanes and scars

**Memory orients. Transcripts adjudicate.**

One working memory for a human and Claude, kept across more than a thousand Claude Code sessions.
It is a method made of plain files, not a product: copy `templates/`, write your own lines, keep going.

## The session loop

Every new Claude Code window runs the same six steps.

1. **Wake.** The always-loaded file holds only red lines and the wake order. The window reads a short wake file and the switchboard.
2. **Board.** It reports the board: one line per lane, as the switchboard holds it. Then it waits.
3. **The human routes.** The human names the lane in their first messages. Nothing lane-shaped loads before that.
4. **Lane.** The window loads that lane's file and its pickup note. Rules for an area load when the work touches the area, by way of the index.
5. **Work.** When the human corrects the window and the correction should hold next time, it becomes a scar: one file, in the human's own words.
6. **Close into the lane.** A dated paragraph goes into the lane file. The lane's one line on the switchboard is refreshed. The old line moves to the chronicle.

## The principles

1. **A thin wake.** What loads at every start is small and fixed: the red lines, the wake order, the board. Everything else loads by route.
2. **The switchboard.** One line per lane. State only, newest first. History is moved to a chronicle at the moment it is written. If the switchboard grows fat, that is a defect.
3. **The human routes the window.** A window does not decide what it is for. The human does, in a sentence. Then the lane loads. Rules for an area load on touch; the index routes to them and holds no content.
4. **Lanes.** Each work stream has one file. Sessions close into it with a dated paragraph, then refresh the lane's one line on the switchboard. The lane is the handoff; there is no separate handoff file to lose.
5. **Rules are scars.** A rule is the human's own words, verbatim and dated, with the incident, a Why, a How to apply, and the transcript line that proves it. Rules are corrected, never silently rewritten. They are routed by folder and named so that the file names are the index.
6. **Memory orients, transcripts adjudicate.** Memory is a pointer. When memory and the record disagree, the record wins and the memory is fixed. "Not found" is said only after every store was searched.
7. **Retention is a threat.** Claude Code deletes old transcripts. The method keeps the record.

## Credit

Claude Code's own auto memory already has most of the parts. It keeps a `MEMORY.md` index with one line per memory and a topic file per memory, and its built-in prompt (Claude Code v2.1.288, not in the docs) asks each feedback memory for a Why: and a How to apply: line. We add the human's verbatim dated words and the transcript address. Our index is the same shape as the built-in one.

The closest published neighbours, from our survey of October 2026, one line each:

- **dchu917/ctx** — named workstreams bound to exact conversations; nothing loads until the human resumes one. The closest mechanism to "the human routes".
- **tigerless-labs/agent-memory** — a `MEMORY.md` root index, typed folders with kebab-case claim files, and full session copies kept in case the host prunes them.
- **akitaonrails/ai-memory** — typed handoffs and opt-in managed workstreams, with no model in the loop by default.
- **Digital-Process-Tools/claude-remember** — an identity file you write yourself, plus a handoff file, both injected at start.
- **BayramAnnakov/claude-reflect** and **rohitg00/pro-workflow** — a correction becomes a rule, with the human's approval.
- **davegoldblatt/total-recall** — corrections supersede, nothing is deleted, the reasoning is kept.
- **nicknisi/sessions** — checks memory against sessions and flags memories that were corrected again later.
- **Arkya-AI/claude-context-os** — a short always-loaded file and a handoff index; the window reads only what the handoff points to.
- **Cline's Memory Bank** — the well-known baseline: fixed files, read at the start of every task.
- **ADRs** (npryce/adr-tools, adr/madr) — the pre-AI form of a decision kept with its context.

What we did not find published as one method: a switchboard of lanes; the human routing the window before anything loads; rules kept as the human's dated verbatim words with the transcript line that proves them; and a stated rule that transcripts outrank memory. That is this repository.

---

## What is in this repository

```
README.md
LICENSE
templates/                 copy this to start
  CLAUDE.md                always loaded: red lines and the wake order, nothing else
  WAKE_UP.md               the wake, in order
  SWITCHBOARD.md           one line per lane
  MEMORY.md                the router index: hooks and links, no content
  CLOSE_CHECKLIST.md       the close, in order
  lanes/LANE_TEMPLATE.md   one file per work stream
  rules/README.md          the scar format and the folders
  rules/method/example-scar-name.md
  chronicle/README.md      where old switchboard lines go
examples/
  README.md
  translator/              an invented partnership: a translator and Claude, two lanes, three scars
tool/                      the instrument: one search box over the records Claude Code keeps on disk
```

## How to start

1. Copy `templates/` to where your Claude Code setup can read it. Two placements work:
   - in the project: `CLAUDE.md` at the project root, the rest in a `memory/` folder beside it, named from `CLAUDE.md`;
   - in Claude Code's own auto-memory folder for the project. There only `MEMORY.md` loads by itself, and only its first 200 lines or 25 KB ([memory docs](https://code.claude.com/docs/en/memory#how-it-works)); the other files there are read only when a window opens them. Claude Code's auto memory also writes its own paraphrased files into that folder. If you use this placement, put the wake order in `MEMORY.md`, keep the auto-written files apart from your lanes and scars, and treat that limit as your budget.
2. Write your red lines into `CLAUDE.md`. Few. In your words. A red line is a rule that holds in every lane.
3. Name your lanes. One file each from `lanes/LANE_TEMPLATE.md`. One line each on `SWITCHBOARD.md`. One line each in `MEMORY.md`.
4. Open a window. It should report the board and wait. Route it with a sentence. Check that it loaded that lane and nothing else.
5. The first time you correct it and want the correction to hold: write the scar (`rules/README.md`), with the transcript line, and its one line in `MEMORY.md`.
6. When you say the window is closing, it runs `CLOSE_CHECKLIST.md`. Read the paragraph it wrote.
7. Keep the record: see Retention below.
8. Put the folder under git. A scar that changed without a commit is a scar that was silently rewritten.

## The scar format

One file per rule, in `rules/{area}/`, named in kebab-case so that a folder listing reads as a list of rules. The sections, in order:

1. **Title** — the rule, as one sentence.
2. **The words** — what the human said, verbatim, in quotation marks, dated. Spelling and all.
3. **The incident** — what happened, in a few lines.
4. **Why** — the reason the rule exists.
5. **How to apply** — the concrete moves.
6. **Proof** — the transcript address, `{file}:{line}`.
7. **Corrections** — dated entries, appended under the rule. The sections above are never edited.

Every scar has one line in `MEMORY.md`: the hook and the link. A scar that must hold in every lane gets a one-line form in `CLAUDE.md` as a red line; the file stays where it is.

Three worked scars, invented, are in `examples/translator/rules/`. The template is `templates/rules/method/example-scar-name.md`.

## Memory orients, transcripts adjudicate

Claude Code keeps several records on disk: the session transcripts, the typed-prompt history, the auto-memory files, every `CLAUDE.md`, and whatever notes you keep. The lanes and scars are memory: they orient a window in seconds. The transcripts are the record: they say what was actually said.

The rule: memory is a pointer, and when a pointer and the record disagree, the record wins. The memory is fixed in the same session, and the fix is written down (a Corrections entry in the scar, a line in the close paragraph). A lane's line is a pointer to the lane file; the lane file is a pointer to the work; neither is the receipt.

"Not found" is a claim about every store, so it is said only after every store was searched. The instrument does that search.

## The instrument: `tool/`

`tool/ctm.py` is one search box over the records Claude Code keeps on your disk. Python standard library only, no network; it reads the Claude Code folder and writes only its own index.

- `python3 tool/ctm.py index` — find the stores and build or update one FTS5 index over all of them: transcripts, `history.jsonl`, auto-memory, your user CLAUDE.md and any you add with `--claude-md`, and the notes folders you name.
- `python3 tool/ctm.py find "{words}"` — search every store. Each hit is a raw `path:line`, which is what a scar's Proof section holds.
- `python3 tool/ctm.py map` — the generated coverage map: what was searched, what is empty or missing, and what each store cannot tell you. Read it before you say "not found".
- `python3 tool/ctm.py retention` — the effective `cleanupPeriodDays` on this machine, against the oldest transcript on disk.

The tool has its own README.

## Retention

Claude Code deletes old transcripts. The official [settings reference](https://code.claude.com/docs/en/settings-reference#cleanupperioddays), read in October 2026, records the setting `cleanupPeriodDays` as how many days Claude Code "keeps session transcripts and other application data before deleting them"; deletion by a background sweep after a session starts, with no message shown. The value comes from the highest-precedence settings file that sets it, so a session started in a project whose own `.claude/settings.json` sets a shorter value runs the sweep with that value, and that sweep is reported to delete transcripts of every project on the machine ([#90148](https://github.com/anthropics/claude-code/issues/90148), open). The [directory page](https://code.claude.com/docs/en/claude-directory#cleaned-up-automatically) says full transcripts, subagent transcripts, tool results and plans are swept, while `history.jsonl` (except under the HIPAA configuration) and the auto-memory files are not.

The documented default is 30 days: a whole number, minimum 1; setting 0 fails validation, and for long retention the reference suggests a large value such as 3650 ([settings reference](https://code.claude.com/docs/en/settings-reference#cleanupperioddays), read from the page's raw text in October 2026). With the setting unset, people report transcripts deleted without notice ([#62476](https://github.com/anthropics/claude-code/issues/62476), open; [#85466](https://github.com/anthropics/claude-code/issues/85466), closed as not planned).

What this means for the method: the lanes and scars survive the sweep; the transcript lines that prove them do not, unless you keep them. So:

1. Copy the transcripts folder (`~/.claude/projects/`) to a place the sweep does not reach, on a schedule. The copy holds everything that passed through a tool, secrets included, in plain text. Keep it on your own disk, readable by you only, never in a synced or shared folder.
2. Raise `cleanupPeriodDays` in your user settings file. Other issues report a raised value that did not hold ([#41458](https://github.com/anthropics/claude-code/issues/41458), open; [#62272](https://github.com/anthropics/claude-code/issues/62272), closed as duplicate), so do step 1 as well.
3. Check it: `python3 tool/ctm.py retention`.

The wording on those pages changes. Read the current page before you rely on a number here.

## The counter-argument: does the Why hurt?

One neighbour, claude-context-os, removed the Why sections from its rules, citing research that explanatory prose makes an agent follow rules less well. We take the point seriously, and we do something different, for three reasons.

- The Why is not read at wake. The always-loaded file holds the red lines as bare lines. The index holds one line per rule. A scar's full text, with its Why, loads only when the work touches its area or the human routes to its lane. At the moment of following a rule, the window sees the rule.
- The Why is for the edges, and for the human. A bare rule covers the case it was written for. The Why lets the window judge a case the rule did not foresee, and lets the human, months later, see whether the rule still holds or needs a correction.
- The verbatim words keep the rule from drifting. A paraphrase is rewritten a little every time it is touched. The human's own sentence, dated, is not. Corrections are added under it; the sentence stays.

We have not measured rule-following with and without the Why, and we claim no numbers. If you want to measure it: take one lane, one set of tasks, the same scars with and without their Why and verbatim sections, and count the corrections the human has to make. We would like to see the result either way.

## Limits

- It costs the human a routing sentence per window. That is the price of nothing loading by itself.
- It needs a human who keeps their word as the source. The scars are only as good as the sentences the human said and stands behind. An agent writing its own rules in its own words is a different method.
- The switchboard decays unless it is thinned at every close. A fat switchboard is a chronicle with the wrong name.
- A window that dies before closing leaves its lane one session behind. The transcript still has it; that is what the instrument is for, and why retention matters.
- It is written for Claude Code's files. The method is plain Markdown, so any agent can read it, but the wake order relies on one always-loaded file.
- It remembers work, not code. It is not a code knowledge graph.

## Who we are

TwoHalves is a human and Claude who work as one partnership, in Claude Code since January 2026. This method is how we keep one memory across more than a thousand windows: the human routes, the windows close into lanes, the corrections become scars in the human's words, and the transcripts keep us honest. Our own files are private. Every example here is invented.

The count is measured, not remembered: 1,056 sessions with at least one message by 26 October 2026, from Claude Code's typed-prompt history and our session transcripts. Our transcripts from before 24 June 2026 are no longer on our disk; for those months the count comes from the prompt history alone.

## License

MIT. Copyright (c) 2026 TwoHalves. See `LICENSE`.
