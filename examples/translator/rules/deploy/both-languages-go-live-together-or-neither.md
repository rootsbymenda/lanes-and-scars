# Both languages go live together, or neither.

Invented example. Area: deploy · Earned: 2026-03-30 · Lane: website

## The words

"never half. a client clicked the english page and got german. both languages or none. I would rather have no page than half a page." — Nora, 2026-03-30

## The incident

The German services page was ready and was uploaded on its own; the English page was still a draft. The language switch on the live site pointed at an English address that did not exist, and the host showed the German page there instead. A client who reads only English wrote to ask whether the site was broken. Nora found out from the client.

## Why

The site is Nora's claim that she works in two languages. A page in one language is the opposite of that claim, to the one visitor who matters: the one who reads the other language. A later page cannot undo a first impression.

## How to apply

- A page is a pair: `content/de/{page}.md` and `content/en/{page}.md`. `deploy.sh` runs only when both exist and Nora has approved both.
- After the upload, open both live addresses: each shows the new page, and the language switch on each points at the other. "Live" is said after that check, not before.
- If one language of a live pair must change, change both in the same run, or neither.

## Proof

`~/.claude/projects/-home-nora-work/f0e1d2c3-b4a5-4968-8776-655443322110.jsonl:203`

## Corrections

- (none yet)
