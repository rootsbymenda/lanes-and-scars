# claude-ground-truth

One search box over the records Claude Code keeps on your disk. Every hit is the `path:line` of the raw record.

## First: Claude Code deletes old transcripts

Anthropic's settings reference, under `cleanupPeriodDays`:

> "Claude Code runs the deletion as a background sweep after a session starts, as long as it can safely determine the retention period."
> (https://code.claude.com/docs/en/settings-reference#cleanupperioddays)

The same entry says the sweep shows no message and gives the default as 30 days: a whole number, minimum 1. Setting 0 fails validation; for long retention the reference suggests a large value such as 3650.

- Swept: transcripts, subagent transcripts, tool output files and plans. Not swept: `history.jsonl` (what you typed), except under the HIPAA configuration, and memory files ([what is cleaned up](https://code.claude.com/docs/en/claude-directory#cleaned-up-automatically)).
- Sessions started or last continued in Claude Desktop or Cowork are kept at any age unless [`desktopSessionCleanupPeriodDays`](https://code.claude.com/docs/en/settings-reference#desktopsessioncleanupperioddays) is set.
- A project's own `.claude/settings.json` can set a shorter value, and that value is reported to drive the sweep for every project on the machine ([anthropics/claude-code#90148](https://github.com/anthropics/claude-code/issues/90148)).

See what applies on your machine, and how old your oldest transcript is:

    python3 ctm.py retention

This tool never changes your settings. The index is not a backup: when Claude Code deletes a transcript, the next `index` run drops its text too. To keep a transcript, copy the file.

## Quick start

Python 3.10–3.14: CI runs the tests on each version for every push. Nothing to install.

1. Download one file, `ctm.py`, from this repository.
2. Build the index. Later runs read only what changed.

       python3 ctm.py index

3. Search:

       python3 ctm.py find login form --role user

```
2 matches for: login form   (best first, showing 2)

[1] transcripts | 2026-01-15 10:00Z | user/prompt | -work-demo-myapp | session aaaaaaaa
    ~/.claude/projects/-work-demo-myapp/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl:2
    please fix the >>login<< >>form<< so the error message shows

[2] history | 2026-01-15 10:00Z | user/prompt | -work-demo-myapp | session aaaaaaaa
    ~/.claude/history.jsonl:1
    please fix the >>login<< >>form<< so the error message shows

Matches per store: transcripts 1 | history 1 | tool-output 0 | memory 0 | claude-md 0 | plans 0
Not searched: docs (not configured)
Filters: --role user
```

(home folder shown as ~; last lines trimmed)

Paths are printed in full. To read the whole record behind a hit:

    sed -n '2p' ~/.claude/projects/-work-demo-myapp/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl | python3 -m json.tool

## The map

Memory orients. Transcripts adjudicate.

A memory note or a CLAUDE.md file says what someone decided to keep. A transcript line is what was said. When they disagree, the transcript line is the evidence. And when a search finds nothing, the useful question is which records it could not have seen.

So every `index` run writes a coverage map next to the index (`MAP.md`), and `python3 ctm.py map` prints it. It lists every store: where it lives, whether it exists, how much was indexed, the dates it covers, and what it cannot tell you. The rule it carries: say "not found" only after every store was searched, and name the stores that were empty, missing or not configured.

```
| Store | Status | Files | Rows | First | Last | Where it lives |
|---|---|--:|--:|---|---|---|
| transcripts | indexed | 3 | 20 | 2025-12-01 09:00Z | 2026-01-16 09:00Z | `~/.claude/projects/<project>/**/*.jsonl` |
| history | indexed | 1 | 4 | 2025-12-01 09:00Z | 2026-01-15 11:00Z | `~/.claude/history.jsonl` |
| tool-output | indexed | 1 | 1 | 2026-01-15 10:05Z | 2026-01-15 10:05Z | `~/.claude/projects/<project>/<session>/tool-results/*.txt` |
| memory | indexed | 3 | 4 | 2026-01-18 17:00Z | 2026-01-20 08:00Z | `~/.claude/projects/<project>/memory/**/*.md and ~/.claude/agent-memory/**/*.md` |
| claude-md | indexed | 1 | 1 | 2026-01-10 12:00Z | 2026-01-10 12:00Z | `~/.claude/CLAUDE.md` |
| plans | indexed | 1 | 1 | 2026-01-15 10:30Z | 2026-01-15 10:30Z | `~/.claude/plans/**/*.md` |
| docs | not configured | 0 | 0 | - | - | `none added (use --docs PATH)` |

## What each store cannot tell you

- transcripts: Only sessions still on disk. Claude Code's retention sweep deletes the transcripts (and
  subagent transcripts) of sessions not used for longer than cleanupPeriodDays; ...
- history: Only your side: what you typed and pasted, with the time and the project folder. ...
- memory: Notes kept to orient later sessions: curated, not a record of what happened. ...
```

(home folder shown as ~; header and last lines trimmed)

The map also carries the retention value in force, the shortest value found in any project, and the oldest transcript on disk.

A search with no hits prints the same picture in short:

```
No matches for: invoice
Searched (dates each store covers | what it cannot hold):
  transcripts  2025-12-01 09:00Z .. 2026-01-16 09:00Z | sessions unused for over 14 days are deleted; tool text cut at 8,000 chars
  history      2025-12-01 09:00Z .. 2026-01-15 11:00Z | your side only; not swept (except under the HIPAA configuration)
  tool-output  2026-01-15 10:05Z .. 2026-01-15 10:05Z | large outputs only, deleted with transcripts; tool text cut at 8,000 chars
  memory       2026-01-18 17:00Z .. 2026-01-20 08:00Z | curated notes, not a record
  claude-md    2026-01-10 12:00Z .. 2026-01-10 12:00Z | instructions, not events
  plans        2026-01-15 10:30Z .. 2026-01-15 10:30Z | intent, not what was done; deleted with transcripts
Not searched: docs (not configured)
```

(home folder shown as ~; last lines trimmed)

## Stores

| Store | Where | What is indexed |
|---|---|---|
| transcripts | `~/.claude/projects/<project>/**/*.jsonl`, subagents included | your prompts, Claude's replies and thinking text (when the transcript holds it), tool calls and tool output, session titles, summaries, prompts queued while Claude was working |
| history | `~/.claude/history.jsonl` | what you typed, and text you pasted |
| tool-output | `~/.claude/projects/<project>/<session>/tool-results/*.txt` | large tool outputs that Claude Code moved out of the transcript |
| memory | `~/.claude/projects/<project>/memory/**/*.md`, `~/.claude/agent-memory/**/*.md` | auto-memory notes |
| claude-md | `~/.claude/CLAUDE.md`, plus files given with `--claude-md` | standing instructions |
| plans | `~/.claude/plans/**/*.md` | saved plans |
| docs | folders given with `--docs` | your own `*.md` notes |

If `CLAUDE_CONFIG_DIR` is set, it is used in place of `~/.claude`: Anthropic's [settings page](https://code.claude.com/docs/en/settings) documents it as the place Claude Code then keeps settings and session history. `--claude-dir PATH` overrides both.

Not indexed: images, PDFs, file-history snapshots, uploads and caches, and the context Claude Code copies into a session. CLAUDE.md and memory are indexed from their own files; hook output and skill text are not indexed.

## Commands

### index

    python3 ctm.py index [--claude-md PATH] [--docs PATH] [--forget PATH] [--tool-chars N] [--full]

Finds every store and updates the index. A file whose size and modification time are unchanged is skipped. A transcript that only grew is read from the line where the last run stopped; one that was rewritten is read again. Big files are read line by line, never whole; memory use depends on the largest single record, not on file size.

- `--claude-md PATH`: also index a CLAUDE.md file, or the CLAUDE.md files in a project folder. Remembered.
- `--docs PATH`: also index the `*.md` files under a folder. Remembered.
- `--forget PATH`: stop indexing a path added before.
- `--tool-chars N`: characters indexed per tool call or tool output, default 8000; `0` indexes all of it and makes the index larger. Changing it rebuilds the index.
- `--full`: rebuild from scratch.
- `--db PATH`: where the index lives. Default `~/.local/share/claude-ground-truth/index.db` (or under `$XDG_DATA_HOME`).
- `-q`, `--quiet`: print nothing unless something fails.

### find

    python3 ctm.py find WORDS... [--store S] [--project P] [--since DATE] [--until DATE] [--role R] [--limit N] [--sort rank|old|new] [--raw]

Every word must appear in the same record. `"quotes"` keep a phrase together; a trailing `*` matches a prefix (`deploy*` finds deployed and deploying). There is no stemming.

- `--store`: one store only.
- `--project`: a project folder path, or part of its name (`--project myapp`).
- `--since`, `--until`: dates as `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM`, in UTC, both ends included. Markdown files have no per-line dates, so their file time is used and marked `(file time)`.
- `--role`: who wrote it, read from the record, never guessed:
  - `user`: typed by a person (prompts, queued prompts, pasted text);
  - `assistant`: written by Claude (replies, thinking text, subagents, the prompts one agent writes for another, messages from another session);
  - `tool`: tool calls and tool output;
  - `system`: added by Claude Code itself (titles, summaries, task notifications, notes it inserts).
  Markdown stores have no role. Older transcripts without these markers are counted as typed by a person.
- `--raw`: pass the query to SQLite FTS5 as written (`OR`, `NOT`, `NEAR`).

### map

    python3 ctm.py map

Prints the map written by the last `index` run.

### retention

    python3 ctm.py retention [--project-dir PATH]

Reads `cleanupPeriodDays` from your user settings and from every project settings file it can find: in each folder where sessions ran (read from the transcripts and from `history.jsonl`), and in the folders under each `--project-dir` (up to four levels down). In each folder the highest file that sets the key wins (project local, then shared project, then user), following the [precedence on the settings page](https://code.claude.com/docs/en/settings). It prints the value in force, the shortest value found and the file that sets it, the oldest transcript still on disk, and how to change it. Organization (managed) settings are not read; `/status` in Claude Code lists them.

## Privacy

- Local only. No network access, standard library only.
- It reads the Claude Code folder and writes only its index and `MAP.md`.
- The index holds a copy of your private text: prompts, code, command output, and anything pasted into a session, secrets included. Keep it private. On Linux and macOS it is created readable by you only. Do not sync, share or commit it. To remove it, delete the folder `~/.local/share/claude-ground-truth`.

## Limitations

- Claude Code's transcript format is not a documented interface. The parser reads the record types known in October 2026 and skips the rest; a format change can hide new record types until the parser learns them.
- Search is by whole words (SQLite FTS5, `unicode61` tokenizer). No stemming, no fuzzy matching. Languages written without spaces between words (Chinese, Japanese, Thai) search poorly.
- Tool calls and tool output are cut at 8,000 characters each unless `--tool-chars 0`. The map counts how many were cut.
- Images, PDFs and other binary files are not indexed.
- Transcripts that Claude Code already deleted cannot be found. The index keeps their text only if it was built before the sweep, and it keeps it only until the next `index` run notices the file is gone.
- If the Python build has no FTS5 in its `sqlite3` module, the tool says so and stops.

## Tests

From the repository root:

    python3 -m unittest discover -s tool/tests -t tool

The tests build a made-up Claude Code folder in a temporary directory. One of them indexes a 50 MB transcript in a child process and checks that memory grows by far less than the file size.

## License

MIT. See [LICENSE](../LICENSE).
