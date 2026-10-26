# Index: the router

This file routes. It holds no content: one line per entry, a hook and a link.
Keep it short enough to load whole at every start. If it grows, move the detail into the file it points to.
Claude Code's own auto memory uses this same shape, a `MEMORY.md` with one line per memory; if you keep this file in that folder, it loads by itself.

## Start here

- [WAKE_UP.md](WAKE_UP.md) first · [SWITCHBOARD.md](SWITCHBOARD.md) is the board · [CLOSE_CHECKLIST.md](CLOSE_CHECKLIST.md) at close.

## Lanes

- [{lane-name}](lanes/{lane-name}.md) — {what this lane is, in five words}
- [{lane-name}](lanes/{lane-name}.md) — {what this lane is, in five words}

## Rules, by folder: load on touch

List the folder when the work enters its area. The kebab-case file names are the index; open the ones whose names apply.

- `rules/method/` — how we find out what is true.
- `rules/behaviour/` — how we work together.
- `rules/execution/` — sessions, agents, memory, closing.
- `rules/deploy/` — load before anything goes live.
- `rules/money/` — load before anything is paid or priced.

## Hot rules

One line per rule that bit recently. Hook and link only; the words are in the file.

- [{kebab-case-name}](rules/{area}/{kebab-case-name}.md) — {the hook, one line}
