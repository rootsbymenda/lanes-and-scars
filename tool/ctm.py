#!/usr/bin/env python3
"""One search box over the records Claude Code keeps on your disk.

    python3 ctm.py index                 build or update the index
    python3 ctm.py find "login form"     search every store; each hit is a path:line
    python3 ctm.py map                   what was searched, what is empty or missing
    python3 ctm.py retention             how long Claude Code keeps transcripts here

Python: tested on 3.12; CI runs 3.10–3.14. Standard library only (sqlite3 with FTS5). No network access.
It only reads the Claude Code folder; it writes only its own index and map.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import time

TOOL_NAME = "claude-ground-truth"  # the only place the name is defined
VERSION = "0.1.0"
SCHEMA_VERSION = "1"

# Anthropic's settings reference, read on 2026-10-26: cleanupPeriodDays is a whole number of days,
# minimum 1, default 30; 0 fails validation; a background sweep after a session starts deletes
# transcripts older than that without a message. Sessions started or last continued in Claude Desktop
# or Cowork are kept at any age unless desktopSessionCleanupPeriodDays is set.
DOCS_URL = "https://code.claude.com/docs/en/settings-reference#cleanupperioddays"
DOCS_QUOTE = ("Claude Code runs the deletion as a background sweep after a session starts, "
              "as long as it can safely determine the retention period.")
DOCS_DEFAULT_DAYS = 30
DOCS_DESKTOP_URL = "https://code.claude.com/docs/en/settings-reference#desktopsessioncleanupperioddays"
DOCS_SWEPT_URL = "https://code.claude.com/docs/en/claude-directory#cleaned-up-automatically"
PROJECT_SWEEP_ISSUE = "https://github.com/anthropics/claude-code/issues/90148"
RETENTION_KEY = "cleanupPeriodDays"
DESKTOP_RETENTION_KEY = "desktopSessionCleanupPeriodDays"

DEFAULT_TOOL_CHARS = 8000
BATCH_ROWS = 2000
BATCH_CHARS = 4 * 1024 * 1024
ANCHOR_BYTES = 1024

STORE_ORDER = ("transcripts", "history", "tool-output", "memory", "claude-md", "plans", "docs")
JSONL_STORES = ("transcripts", "history")
ROLES = ("user", "assistant", "tool", "system")
UTC = dt.timezone.utc


class CtmError(Exception):
    """A problem reported to the user without a traceback."""


# ----------------------------------------------------------------- locations

def resolve_claude_dir(arg: str | None) -> tuple[str, str]:
    """The Claude Code folder and how it was chosen."""
    if arg:
        return os.path.abspath(os.path.expanduser(arg)), "--claude-dir"
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        return os.path.abspath(os.path.expanduser(env)), "CLAUDE_CONFIG_DIR"
    return os.path.join(os.path.expanduser("~"), ".claude"), "default location"


def default_db() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, TOOL_NAME, "index.db")


def db_path(arg: str | None) -> str:
    return os.path.abspath(os.path.expanduser(arg)) if arg else default_db()


def map_path(db: str) -> str:
    return os.path.join(os.path.dirname(db), "MAP.md")


def slugify(path: str) -> str:
    """Claude Code names a project folder after its path, every other character turned into '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


# --------------------------------------------------------------------- time

_TS = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?$")


def iso(moment: dt.datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_ts(value) -> str | None:
    """ISO-8601 text or epoch seconds/milliseconds -> 'YYYY-MM-DDTHH:MM:SSZ' (UTC)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        secs = value / 1000.0 if value > 1e11 else float(value)
        try:
            return iso(dt.datetime.fromtimestamp(secs, UTC))
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    m = _TS.match(value.strip())
    if not m:
        return None
    y, mo, d, h, mi, s, tz = m.groups()
    try:
        moment = dt.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0), tzinfo=UTC)
    except ValueError:
        return None
    if tz and tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        moment -= sign * dt.timedelta(hours=int(tz[1:3]), minutes=int(tz[-2:]))
    return iso(moment)


def ns_iso(ns: int) -> str:
    return iso(dt.datetime.fromtimestamp(ns / 1e9, UTC))


def plural(count: int, word: str) -> str:
    return f"{count:,} {word}" + ("" if count == 1 else "s")


def short_time(ts: str | None) -> str:
    return f"{ts[:10]} {ts[11:16]}Z" if ts else "-"


def bound(text: str, upper: bool) -> str:
    """--since/--until value -> comparable timestamp. Upper bounds are exclusive."""
    text = text.strip()
    try:
        day = dt.date.fromisoformat(text)
    except ValueError:
        day = None
    if day is not None:
        if upper:
            day += dt.timedelta(days=1)
        return f"{day.isoformat()}T00:00:00Z"
    ts = norm_ts(text)
    if ts is None:
        raise CtmError(f"Not a date: {text!r}. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM (UTC).")
    if upper:
        ts = iso(dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) + dt.timedelta(seconds=1))
    return ts


# ---------------------------------------------------------------- discovery

@dataclasses.dataclass
class Source:
    store: str
    path: str
    project: str | None = None
    session: str | None = None
    sub: bool = False
    kind: str = ""


def _md_files(base: str) -> list[str]:
    """*.md under base (or base itself when it is a .md file). Hidden folders are skipped."""
    if os.path.isfile(base):
        return [base] if base.lower().endswith(".md") else []
    found = []
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.lower().endswith(".md") and not name.startswith("."):
                found.append(os.path.join(root, name))
    return found


def _claude_md_files(path: str) -> list[str]:
    """A CLAUDE.md file, or the CLAUDE.md files in a project folder."""
    if os.path.isdir(path):
        names = ("CLAUDE.md", "CLAUDE.local.md", os.path.join(".claude", "CLAUDE.md"))
        return [os.path.join(path, n) for n in names if os.path.isfile(os.path.join(path, n))]
    return [path] if os.path.isfile(path) else []


def _project_dirs(pdir: str, info: dict) -> list[os.DirEntry]:
    """Project folders, each real folder once (a folder linked to another is skipped)."""
    if not os.path.isdir(pdir):
        return []
    entries = []
    with os.scandir(pdir) as it:
        for entry in it:
            try:
                if entry.is_dir() and not entry.name.startswith("."):
                    entries.append(entry)
            except OSError:
                continue
    entries.sort(key=lambda e: (e.is_symlink(), e.name))
    kept, seen = [], set()
    for entry in entries:
        real = os.path.realpath(entry.path)
        if real in seen:
            info["aliases"] += 1
            continue
        seen.add(real)
        kept.append(entry)
    return kept


def discover(cdir: str, claude_mds: list[str], docs: list[str]) -> tuple[list[Source], dict]:
    """Every file of every store, each real file once."""
    found: list[Source] = []
    seen: set[tuple[int, int]] = set()
    info = {"aliases": 0, "bad_names": 0}

    def add(src: Source) -> None:
        try:
            src.path.encode("utf-8")
        except UnicodeEncodeError:
            info["bad_names"] += 1
            return
        try:
            st = os.stat(src.path)
        except OSError:
            return
        if not stat.S_ISREG(st.st_mode) or (st.st_dev, st.st_ino) in seen:
            return
        seen.add((st.st_dev, st.st_ino))
        found.append(src)

    for entry in _project_dirs(os.path.join(cdir, "projects"), info):
        slug = entry.name
        for root, dirs, files in os.walk(entry.path):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            rel = os.path.relpath(root, entry.path)
            parts = [] if rel == "." else rel.split(os.sep)
            for name in sorted(files):
                if name.startswith("."):
                    continue
                path, low = os.path.join(root, name), name.lower()
                if parts and parts[0] == "memory":
                    if low.endswith(".md"):
                        add(Source("memory", path, project=slug, kind="memory"))
                elif low.endswith(".jsonl"):
                    sub = "subagents" in parts or name.startswith("agent-")
                    session = parts[0] if parts else name[: -len(".jsonl")]
                    add(Source("transcripts", path, project=slug, session=session, sub=sub))
                elif low.endswith(".txt") and "tool-results" in parts:
                    add(Source("tool-output", path, project=slug, session=parts[0], kind="output"))
    add(Source("history", os.path.join(cdir, "history.jsonl")))
    for path in _md_files(os.path.join(cdir, "agent-memory")):
        add(Source("memory", path, kind="agent-memory"))
    for path in _claude_md_files(os.path.join(cdir, "CLAUDE.md")) + [p for c in claude_mds for p in _claude_md_files(c)]:
        add(Source("claude-md", path, kind="claude-md"))
    for path in _md_files(os.path.join(cdir, "plans")):
        add(Source("plans", path, kind="plan"))
    for folder in docs:
        for path in _md_files(folder):
            add(Source("docs", path, kind="doc"))
    return found, info


def store_places(cdir: str, claude_mds: list[str], docs: list[str]) -> dict[str, dict]:
    """Where each store lives and whether that place exists (for the map)."""
    j = os.path.join
    pdir = j(cdir, "projects")
    md_candidates = [j(cdir, "CLAUDE.md")] + claude_mds
    return {
        "transcripts": {"where": j(pdir, "<project>", "**", "*.jsonl"), "present": os.path.isdir(pdir)},
        "history": {"where": j(cdir, "history.jsonl"), "present": os.path.isfile(j(cdir, "history.jsonl"))},
        "tool-output": {"where": j(pdir, "<project>", "<session>", "tool-results", "*.txt"),
                        "present": os.path.isdir(pdir)},
        "memory": {"where": j(pdir, "<project>", "memory", "**", "*.md") + " and " + j(cdir, "agent-memory", "**", "*.md"),
                   "present": os.path.isdir(pdir) or os.path.isdir(j(cdir, "agent-memory"))},
        "claude-md": {"where": ", ".join(md_candidates), "present": any(os.path.exists(p) for p in md_candidates)},
        "plans": {"where": j(cdir, "plans", "**", "*.md"), "present": os.path.isdir(j(cdir, "plans"))},
        "docs": {"where": ", ".join(docs) if docs else "none added (use --docs PATH)",
                 "present": any(os.path.exists(p) for p in docs), "configured": bool(docs)},
    }


# --------------------------------------------------------------- extraction

def _s(value) -> str:
    return value if isinstance(value, str) else ""


def _block_text(content) -> str:
    """Text of a tool result or prompt: a string, or the text blocks of a list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


def _flatten(value, key: str, out: list[str], depth: int = 0) -> None:
    """Tool input as 'key: value' lines, strings kept raw (JSON escapes would split words)."""
    if depth > 30:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(v, f"{key}.{k}" if key else str(k), out, depth + 1)
    elif isinstance(value, list):
        for v in value:
            _flatten(v, key, out, depth + 1)
    elif value is not None:
        out.append(f"{key}: {value}" if key else str(value))


def _call_text(block: dict) -> str:
    lines = [str(block.get("name") or "tool")]
    _flatten(block.get("input"), "", lines)
    return "\n".join(lines)


def _marks(*values) -> list[str]:
    return [v.replace("_", "-").lower() for v in values if isinstance(v, str) and v]


def _who(marks: list[str], is_meta: bool, sidechain: bool, human_kind: str) -> tuple[str, str]:
    """Role and kind of text on the user side of a transcript. Who wrote it is read, never guessed."""
    for mark in marks:
        if mark == "task-notification":
            return "system", "task-notification"
        if mark == "peer":
            return "assistant", "peer-message"
    if sidechain:
        return "assistant", "agent-prompt"
    if "human" in marks:
        return "user", human_kind
    if marks:
        return "system", marks[0]
    if is_meta:
        return "system", "meta"
    return "user", human_kind


def extract_transcript(o: dict, src: Source):
    """(timestamp, session, project, [(role, kind, text)]) for one transcript line."""
    kind_of_line = o.get("type")
    ts = norm_ts(o.get("timestamp"))
    sid = o.get("sessionId")
    session = sid if isinstance(sid, str) and sid else src.session
    sidechain = src.sub or o.get("isSidechain") is True
    out: list[tuple[str, str, str]] = []
    if kind_of_line in ("user", "assistant"):
        msg = o.get("message")
        if not isinstance(msg, dict):
            return ts, session, src.project, out
        if kind_of_line == "assistant":
            text_role, text_kind = "assistant", ("agent-text" if sidechain else "text")
        elif o.get("isCompactSummary") is True:
            text_role, text_kind = "system", "compact-summary"
        else:
            origin = o.get("origin")
            marks = _marks(origin.get("kind") if isinstance(origin, dict) else None, o.get("turnOrigin"))
            text_role, text_kind = _who(marks, o.get("isMeta") is True, sidechain, "prompt")
        texts, thinking, calls, results = [], [], [], []
        content = msg.get("content")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    texts.append(_s(block.get("text")))
                elif btype == "thinking":
                    thinking.append(_s(block.get("thinking")))
                elif btype in ("tool_use", "server_tool_use", "mcp_tool_use"):
                    calls.append(_call_text(block))
                elif isinstance(btype, str) and btype.endswith("tool_result"):
                    results.append(_block_text(block.get("content")))
        groups = ((text_role, text_kind, texts), ("assistant", "thinking", thinking),
                  ("tool", "call", calls), ("tool", "result", results))
        for role, kind, parts in groups:
            body = "\n\n".join(p for p in parts if p.strip())
            if body:
                out.append((role, kind, body))
    elif kind_of_line == "summary":
        out.append(("system", "summary", _s(o.get("summary"))))
    elif kind_of_line == "custom-title":
        out.append(("system", "title", _s(o.get("customTitle"))))
    elif kind_of_line == "system":
        subtype = o.get("subtype")
        out.append(("system", subtype if isinstance(subtype, str) and subtype else "system", _s(o.get("content"))))
    elif kind_of_line == "attachment":
        att = o.get("attachment")
        if isinstance(att, dict) and att.get("type") == "queued_command":
            origin = att.get("origin")
            mode = att.get("commandMode")
            marks = _marks(origin.get("kind") if isinstance(origin, dict) else None, mode if mode != "prompt" else None)
            role, kind = _who(marks, att.get("isMeta") is True, sidechain, "queued")
            out.append((role, kind, _block_text(att.get("prompt"))))
            ts = ts or norm_ts(att.get("timestamp"))
    return ts, session, src.project, [(r, k, t) for r, k, t in out if t.strip()]


def extract_history(o: dict, src: Source):
    """(timestamp, session, project, [(role, kind, text)]) for one history.jsonl line."""
    ts = norm_ts(o.get("timestamp"))
    sid = o.get("sessionId")
    project = o.get("project")
    rows = [("user", "prompt", _s(o.get("display")))]
    pasted = o.get("pastedContents")
    if isinstance(pasted, dict):
        for key in sorted(pasted, key=str):
            item = pasted[key]
            if isinstance(item, dict):
                rows.append(("user", "paste", _s(item.get("content"))))
    return (ts, sid if isinstance(sid, str) and sid else None,
            slugify(project) if isinstance(project, str) and project else None,
            [(r, k, t) for r, k, t in rows if t.strip()])


def _parse(raw: bytes):
    """A JSON line -> value; {} for a blank line; None when it cannot be read."""
    text = raw.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except ValueError:
        try:
            return json.loads(text.decode("utf-8", "replace"))
        except (ValueError, RecursionError):
            return None
    except RecursionError:
        return None


_SURROGATE = re.compile("[\ud800-\udfff]")


def _clean(text: str) -> str:
    """SQLite needs valid UTF-8; transcripts can hold lone surrogates from cut-off text."""
    if _SURROGATE.search(text) is None:
        return text
    return text.encode("utf-8", "replace").decode("utf-8")


def _chunks(lines, headings: bool = True, soft: int = 1500, hard: int = 6000):
    """(first line number, text) pieces of a text file: split at headings, or at blank lines once big."""
    buf: list[str] = []
    size = start = 0
    for number, line in enumerate(lines, 1):
        if buf and ((headings and line.startswith("#")) or size >= hard or (size >= soft and not line.strip())):
            yield start, "".join(buf)
            buf, size = [], 0
        if not buf:
            if not line.strip():
                continue
            start = number
        buf.append(line)
        size += len(line)
    if buf:
        yield start, "".join(buf)


# ------------------------------------------------------------------ storage

SCHEMA_SQL = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE files(
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    store TEXT NOT NULL,
    project TEXT,
    session TEXT,
    size INTEGER NOT NULL DEFAULT -1,
    mtime_ns INTEGER NOT NULL DEFAULT 0,
    mtime_iso TEXT,
    off INTEGER NOT NULL DEFAULT 0,
    lines INTEGER NOT NULL DEFAULT 0,
    head TEXT,
    tail TEXT,
    nrows INTEGER NOT NULL DEFAULT 0,
    first_ts TEXT,
    last_ts TEXT,
    cut INTEGER NOT NULL DEFAULT 0,
    bad INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE rows(
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    line INTEGER NOT NULL,
    ts TEXT,
    role TEXT,
    kind TEXT,
    session TEXT,
    project TEXT,
    cut INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX rows_by_file ON rows(file_id, line);
"""


def _require_fts5() -> None:
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    except sqlite3.OperationalError:
        raise CtmError("This Python's sqlite3 module has no FTS5 support, which the index needs. "
                       "Use a Python build linked against SQLite 3.9 or newer with FTS5 enabled.") from None


def connect(path: str, create: bool) -> sqlite3.Connection:
    _require_fts5()
    if create:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    elif not os.path.isfile(path):
        raise CtmError(f"No index at {path}. Run: python3 ctm.py index")
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def _meta(con: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM meta")}


def _set_meta(con: sqlite3.Connection, **values) -> None:
    con.executemany("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    [(k, v if isinstance(v, str) else json.dumps(v)) for k, v in values.items()])


def ensure_schema(con: sqlite3.Connection, reset: bool = False) -> None:
    has_meta = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
    if has_meta and not reset:
        if _meta(con).get("schema") == SCHEMA_VERSION:
            return
    for table in ("fts", "rows", "files", "meta"):
        con.execute(f"DROP TABLE IF EXISTS {table}")
    con.executescript(SCHEMA_SQL)
    try:
        con.execute("CREATE VIRTUAL TABLE fts USING fts5(body, tokenize='unicode61 remove_diacritics 2')")
    except sqlite3.OperationalError:
        con.execute("CREATE VIRTUAL TABLE fts USING fts5(body, tokenize='unicode61')")
    _set_meta(con, schema=SCHEMA_VERSION)
    con.commit()


def check_schema(con: sqlite3.Connection) -> dict[str, str]:
    try:
        meta = _meta(con)
    except sqlite3.DatabaseError:
        raise CtmError("The index file is not readable. Run: python3 ctm.py index --full") from None
    if meta.get("schema") != SCHEMA_VERSION:
        raise CtmError("The index was built by another version. Run: python3 ctm.py index --full")
    return meta


def _sha(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _anchors(path: str, off: int) -> tuple[str | None, str | None]:
    """Hashes of the first and the last KiB before `off`: how we know a file only grew."""
    if off <= 0:
        return None, None
    with open(path, "rb") as f:
        head = _sha(f.read(min(ANCHOR_BYTES, off)))
        n = min(ANCHOR_BYTES, off)
        f.seek(off - n)
        tail = _sha(f.read(n))
    return head, tail


def _delete_rows(con: sqlite3.Connection, file_id: int, after_line: int | None = None) -> None:
    if after_line is None:
        con.execute("DELETE FROM fts WHERE rowid IN (SELECT id FROM rows WHERE file_id=?)", (file_id,))
        con.execute("DELETE FROM rows WHERE file_id=?", (file_id,))
    else:
        con.execute("DELETE FROM fts WHERE rowid IN (SELECT id FROM rows WHERE file_id=? AND line>?)",
                    (file_id, after_line))
        con.execute("DELETE FROM rows WHERE file_id=? AND line>?", (file_id, after_line))


def _save_file(con, file_id, path, off, lines, bad, size, mtime_ns) -> None:
    head, tail = _anchors(path, off)
    con.execute("UPDATE files SET off=?, lines=?, bad=?, size=?, mtime_ns=?, mtime_iso=?, head=?, tail=? WHERE id=?",
                (off, lines, bad, size, mtime_ns, ns_iso(mtime_ns) if mtime_ns else None, head, tail, file_id))


def _update_stats(con, file_id) -> None:
    n, first, last, cut = con.execute(
        "SELECT COUNT(*), MIN(ts), MAX(ts), COALESCE(SUM(cut), 0) FROM rows WHERE file_id=?", (file_id,)).fetchone()
    con.execute("UPDATE files SET nrows=?, first_ts=?, last_ts=?, cut=? WHERE id=?", (n, first, last, cut, file_id))


class Writer:
    """Buffers index rows and writes them in batches."""

    def __init__(self, con: sqlite3.Connection, tool_chars: int):
        self.con = con
        self.tool_chars = tool_chars
        self.next_id = (con.execute("SELECT MAX(id) FROM rows").fetchone()[0] or 0) + 1
        self.batch: list[tuple] = []
        self.chars = 0

    def full(self) -> bool:
        return len(self.batch) >= BATCH_ROWS or self.chars >= BATCH_CHARS

    def add(self, file_id, line, ts, role, kind, session, project, text, cut=0) -> int:
        if role == "tool" and self.tool_chars and len(text) > self.tool_chars:
            text, cut = text[: self.tool_chars], 1
        row_id = self.next_id
        self.next_id += 1
        self.batch.append((row_id, file_id, line, ts, role, kind, session and _clean(session),
                           project and _clean(project), cut, _clean(text)))
        self.chars += len(text)
        return row_id

    def flush(self) -> None:
        if not self.batch:
            return
        self.con.executemany("INSERT INTO rows(id, file_id, line, ts, role, kind, session, project, cut) "
                             "VALUES (?,?,?,?,?,?,?,?,?)", [b[:9] for b in self.batch])
        self.con.executemany("INSERT INTO fts(rowid, body) VALUES (?, ?)", [(b[0], b[9]) for b in self.batch])
        self.batch.clear()
        self.chars = 0


def index_jsonl(w: Writer, src: Source, st: os.stat_result, rec: dict, existed: bool) -> tuple[str, int]:
    """Index a JSONL file line by line. A file that only grew is read from where the last run stopped."""
    con, file_id = w.con, rec["id"]
    extract = extract_transcript if src.store == "transcripts" else extract_history
    start_off = start_line = bad = 0
    mode = "re-read" if existed else "new"
    if existed and rec["off"] > 0 and st.st_size >= rec["off"]:
        if _anchors(src.path, rec["off"]) == (rec["head"], rec["tail"]):
            start_off, start_line, bad, mode = rec["off"], rec["lines"], rec["bad"], "appended"
    if mode == "appended":
        _delete_rows(con, file_id, after_line=start_line)  # rows of a last line that was still being written
    else:
        _delete_rows(con, file_id)
    off, line, added = start_off, start_line, 0
    with open(src.path, "rb") as f:
        f.seek(start_off)
        for raw in f:
            complete = raw.endswith(b"\n")
            number = line + 1
            obj = _parse(raw)
            if obj is None:
                if complete:
                    bad += 1
            elif isinstance(obj, dict):
                ts, session, project, rows = extract(obj, src)
                for role, kind, text in rows:
                    w.add(file_id, number, ts, role, kind, session, project, text)
                    added += 1
            if not complete:
                break  # indexed if readable, read again next run
            off, line = off + len(raw), number
            if w.full():
                w.flush()
                _save_file(con, file_id, src.path, off, line, bad, -1, 0)
                con.commit()
    w.flush()
    _save_file(con, file_id, src.path, off, line, bad, st.st_size, st.st_mtime_ns)
    _update_stats(con, file_id)
    con.commit()
    return mode, added


def index_text(w: Writer, src: Source, st: os.stat_result, rec: dict, existed: bool) -> tuple[str, int]:
    """Index a markdown or text file in pieces; each piece keeps its first line number."""
    con, file_id = w.con, rec["id"]
    _delete_rows(con, file_id)
    budget = w.tool_chars if src.store == "tool-output" else 0
    role = "tool" if src.store == "tool-output" else None
    used = added = 0
    last_id, stopped = None, False
    with open(src.path, "rb") as f:
        lines = (raw.decode("utf-8", "replace") for raw in f)
        for start, text in _chunks(lines, headings=src.store != "tool-output"):
            cut = 0
            if budget:
                room = budget - used
                if room <= 0:
                    stopped = True
                    break
                if len(text) > room:
                    text, cut = text[:room], 1
                used += len(text)
            last_id = w.add(file_id, start, None, role, src.kind, src.session, src.project, text, cut)
            added += 1
            if w.full():
                w.flush()
            if cut:
                break
    w.flush()
    if stopped and last_id is not None:
        con.execute("UPDATE rows SET cut=1 WHERE id=?", (last_id,))
    _save_file(con, file_id, src.path, 0, 0, 0, st.st_size, st.st_mtime_ns)
    _update_stats(con, file_id)
    con.commit()
    return ("re-read" if existed else "new"), added


# --------------------------------------------------------------- settings

def read_setting(path: str, key: str) -> tuple[str, object]:
    """('no file' | 'unreadable' | 'not set' | 'set', value)."""
    if not os.path.isfile(path):
        return "no file", None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return "unreadable", None
    if not isinstance(data, dict) or key not in data:
        return "not set", None
    return "set", data[key]


def check_days(state: str, value) -> tuple[str, int | None]:
    """A cleanupPeriodDays value as the settings reference defines it: a whole number of days, minimum 1."""
    if state != "set":
        return state, None
    whole = isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if isinstance(value, bool) or not whole:
        return f"invalid ({json.dumps(value)}: not a whole number of days)", None
    if value < 1:
        return f"invalid ({json.dumps(value)}: fails validation, the minimum is 1)", None
    return "set", int(value)


def _git_root(path: str) -> str | None:
    current = path
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def session_folders(cdir: str) -> set[str]:
    """Folders Claude Code sessions ran in, read from transcript (cwd) and history.jsonl (project) records."""
    found: set[str] = set()
    for root, dirs, files in os.walk(os.path.join(cdir, "projects")):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "memory"]
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            try:
                with open(os.path.join(root, name), "rb") as f:
                    for number, raw in enumerate(f):
                        if number >= 200:
                            break
                        if b'"cwd"' in raw:
                            obj = _parse(raw)
                            if isinstance(obj, dict) and isinstance(obj.get("cwd"), str):
                                found.add(obj["cwd"])
                                break
            except OSError:
                continue
    try:
        with open(os.path.join(cdir, "history.jsonl"), "rb") as f:
            for raw in f:
                if b'"project"' in raw:
                    obj = _parse(raw)
                    if isinstance(obj, dict) and isinstance(obj.get("project"), str):
                        found.add(obj["project"])
    except OSError:
        pass
    return {p for p in found if p}


def settings_folders_below(path: str, depth: int = 4) -> list[str]:
    """`path` and folders under it (a few levels deep) that hold a .claude settings file."""
    skip = {"node_modules", "__pycache__", "venv", "site-packages"}
    found = []
    top = path.rstrip(os.sep).count(os.sep)
    for root, dirs, _ in os.walk(path):
        if any(os.path.isfile(os.path.join(root, ".claude", n)) for n in ("settings.json", "settings.local.json")):
            found.append(root)
        if root.count(os.sep) - top >= depth:
            dirs[:] = []
        else:
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in skip)
    return found


def retention_info(cdir: str, given: list[str]) -> dict:
    """cleanupPeriodDays in every settings file this tool can find, and the shortest value in force.

    Project folders come from the records themselves (where sessions ran) and from `given` paths.
    For each folder the highest file that sets the key wins: project local, then shared project.
    """
    cdir_real = os.path.realpath(cdir)
    user_path = os.path.join(cdir, "settings.json")
    user_state, user_days = check_days(*read_setting(user_path, RETENTION_KEY))
    folders = {os.path.abspath(p) for p in session_folders(cdir)}
    from_sessions = len(folders)
    for path in given:
        path = os.path.abspath(os.path.expanduser(path))
        folders.add(path)
        if os.path.isdir(path):
            folders.update(settings_folders_below(path))
    files: list[dict] = []
    seen: dict[str, tuple[str, int | None]] = {}
    overrides: list[dict] = []
    existing = sorted(f for f in folders if os.path.isdir(f))
    for folder in existing:
        root = _git_root(folder)
        layers = []
        if root and root != folder:
            layers.append(("project local settings", os.path.join(root, ".claude", "settings.local.json")))
        layers.append(("project local settings", os.path.join(folder, ".claude", "settings.local.json")))
        layers.append(("shared project settings", os.path.join(folder, ".claude", "settings.json")))
        effective = None
        for label, path in layers:
            if os.path.realpath(os.path.dirname(path)) == cdir_real:
                continue  # this folder's .claude is the Claude Code folder itself: user settings
            if path not in seen:
                seen[path] = check_days(*read_setting(path, RETENTION_KEY))
                if seen[path][0] != "no file":
                    files.append({"label": label, "path": path, "state": seen[path][0], "days": seen[path][1]})
            days = seen[path][1]
            if effective is None and days is not None:
                effective = {"folder": folder, "days": days, "label": label, "path": path}
        if effective:
            overrides.append(effective)
    if user_days is not None:
        base = {"days": user_days, "from": "user settings"}
    else:
        base = {"days": DOCS_DEFAULT_DAYS, "from": "the documented default (no valid value set)"}
    shortest = min(overrides, key=lambda o: (o["days"], o["folder"]), default=None)
    if shortest is not None and shortest["days"] >= base["days"]:
        shortest = None
    desktop_state, desktop_value = read_setting(user_path, DESKTOP_RETENTION_KEY)
    return {"user": {"path": user_path, "state": user_state, "days": user_days}, "files": files,
            "base": base, "shortest": shortest, "days": shortest["days"] if shortest else base["days"],
            "folders": len(existing), "gone": len(folders) - len(existing), "from_sessions": from_sessions,
            "given": len(given),
            "desktop": {"state": desktop_state, "value": desktop_value}}


# ------------------------------------------------------------------ index

def _merge_paths(old: list[str], new: list[str], forget: list[str]) -> list[str]:
    drop = {os.path.abspath(os.path.expanduser(p)) for p in forget}
    merged: list[str] = []
    for p in list(old) + [os.path.abspath(os.path.expanduser(p)) for p in new]:
        if p not in drop and p not in merged:
            merged.append(p)
    return merged


def cmd_index(args) -> int:
    started = time.monotonic()
    os.umask(0o077)  # the index holds private text
    cdir, how = resolve_claude_dir(args.claude_dir)
    db = db_path(args.db)
    con = connect(db, create=True)
    ensure_schema(con)
    meta = _meta(con)
    old_chars = meta.get("tool_chars")
    tool_chars = args.tool_chars if args.tool_chars is not None else int(old_chars or DEFAULT_TOOL_CHARS)
    if tool_chars < 0:
        raise CtmError("--tool-chars must be 0 (no limit) or more")
    claude_mds = _merge_paths(json.loads(meta.get("claude_md") or "[]"), args.claude_md, args.forget)
    docs = _merge_paths(json.loads(meta.get("docs") or "[]"), args.docs, args.forget)
    if args.full or (old_chars is not None and int(old_chars) != tool_chars):
        if not args.full and not args.quiet:
            print(f"Tool text limit changed ({old_chars} -> {tool_chars} characters): rebuilding the index.")
        ensure_schema(con, reset=True)

    sources, info = discover(cdir, claude_mds, docs)
    known = {r["path"]: dict(r) for r in con.execute("SELECT * FROM files")}
    wanted = {s.path for s in sources}
    removed = 0
    for path, rec in known.items():
        if path not in wanted:
            _delete_rows(con, rec["id"])
            con.execute("DELETE FROM files WHERE id=?", (rec["id"],))
            removed += 1
    con.commit()

    w = Writer(con, tool_chars)
    counts = {"new": 0, "appended": 0, "re-read": 0, "unchanged": 0}
    rows_added, failed = 0, 0
    show = not args.quiet and sys.stderr.isatty()
    last_note = time.monotonic()
    for number, src in enumerate(sources, 1):
        try:
            st = os.stat(src.path)
        except OSError:
            continue
        rec = known.get(src.path)
        if rec is not None and rec["store"] != src.store:
            _delete_rows(con, rec["id"])
            con.execute("DELETE FROM files WHERE id=?", (rec["id"],))
            rec = None
        if rec is not None and rec["size"] == st.st_size and rec["mtime_ns"] == st.st_mtime_ns:
            counts["unchanged"] += 1
            continue
        existed = rec is not None
        if rec is None:
            cur = con.execute("INSERT INTO files(path, store, project, session) VALUES (?,?,?,?)",
                              (src.path, src.store, src.project, src.session))
            rec = {"id": cur.lastrowid, "off": 0, "lines": 0, "bad": 0, "head": None, "tail": None}
        try:
            index_one = index_jsonl if src.store in JSONL_STORES else index_text
            mode, added = index_one(w, src, st, rec, existed)
        except OSError as exc:
            w.batch.clear()
            w.chars = 0
            con.rollback()
            failed += 1
            print(f"skipped {src.path}: {exc}", file=sys.stderr)
            continue
        counts[mode] += 1
        rows_added += added
        if show and time.monotonic() - last_note > 1:
            last_note = time.monotonic()
            print(f"\r  {number}/{len(sources)} files, {rows_added:,} rows added", end="", file=sys.stderr)
    if show:
        print(file=sys.stderr)

    retention = retention_info(cdir, [p for p in claude_mds if os.path.isdir(p)])
    used_names = {"projects", "history.jsonl", "CLAUDE.md", "plans", "agent-memory"}
    try:
        others = sorted(n for n in os.listdir(cdir) if n not in used_names and not n.startswith("."))
    except OSError:
        others = []
    seconds = time.monotonic() - started
    last_run = dict(counts, removed=removed, failed=failed, rows_added=rows_added, seconds=round(seconds, 2))
    _set_meta(con, built_at=iso(dt.datetime.now(UTC)), claude_dir=cdir, claude_dir_how=how,
              tool_chars=str(tool_chars), claude_md=claude_mds, docs=docs,
              stores=store_places(cdir, claude_mds, docs), unsearched=others,
              retention=retention, notes=info, last_run=last_run)
    con.commit()
    text = build_map(con, db)
    with open(map_path(db), "w", encoding="utf-8") as f:
        f.write(text)
    if not args.quiet:
        print(f"Indexed in {seconds:.1f} s: {counts['new']} new, {counts['appended']} grown, "
              f"{counts['re-read']} changed, {counts['unchanged']} unchanged, {removed} removed files; "
              f"{rows_added:,} rows added.")
        for row in store_rows(con):
            span = f"{short_time(row['first'])} .. {short_time(row['last'])}" if row["files"] else ""
            print(f"  {row['store']:<12} {row['status']:<15} {row['files']:>7,} files {row['rows']:>12,} rows   {span}")
        size_mb = os.path.getsize(db) / (1024 * 1024)
        print(f"Index: {db} ({size_mb:.1f} MB)")
        print(f"Map:   {map_path(db)}")
    con.close()
    return 0


# -------------------------------------------------------------------- map

def _tool_note(tool_chars: int, cut: int) -> str:
    if not tool_chars:
        return "Tool calls and tool output are indexed in full."
    longer = f"{plural(cut, 'record')} {'was' if cut == 1 else 'were'} longer"
    return (f"Tool calls and tool output are indexed up to {tool_chars:,} characters each "
            f"({longer}; the rest of each is not searchable).")


def store_rows(con: sqlite3.Connection) -> list[dict]:
    meta = _meta(con)
    places = json.loads(meta.get("stores") or "{}")
    stats = {r[0]: r for r in con.execute(
        "SELECT store, COUNT(*), COALESCE(SUM(nrows), 0), MIN(COALESCE(first_ts, mtime_iso)), "
        "MAX(COALESCE(last_ts, mtime_iso)), COALESCE(SUM(cut), 0), COALESCE(SUM(bad), 0) FROM files GROUP BY store")}
    out = []
    for store in STORE_ORDER:
        place = places.get(store, {})
        _, files, rows, first, last, cut, bad = stats.get(store, (store, 0, 0, None, None, 0, 0))
        if files:
            status = "indexed"
        elif store == "docs" and not place.get("configured"):
            status = "not configured"
        elif not place.get("present"):
            status = "missing"
        else:
            status = "empty"
        out.append({"store": store, "status": status, "files": files, "rows": rows, "first": first,
                    "last": last, "cut": cut, "bad": bad, "where": place.get("where", "?")})
    return out


CANNOT = {
    "transcripts": "Only sessions still on disk. Claude Code's retention sweep deletes the transcripts (and "
                   "subagent transcripts) of sessions not used for longer than cleanupPeriodDays; sessions started "
                   "or last continued in Claude Desktop or Cowork are kept unless desktopSessionCleanupPeriodDays "
                   "is set. {tool_note} Images, PDFs, and context that Claude Code adds to a session (CLAUDE.md, "
                   "memory, hook output, skill text) are not indexed from transcripts.",
    "history": "Only your side: what you typed and pasted, with the time and the project folder. No replies, "
               "no tool output. Large pastes kept only as a hash are not in it. The retention sweep does not "
               "delete it (except under the HIPAA configuration), so it can reach back further than the "
               "transcripts.",
    "tool-output": "Large tool outputs that Claude Code saved as files instead of keeping them in the transcript. "
                   "The retention sweep deletes them with the transcripts. {tool_note} Dates are file times.",
    "memory": "Notes kept to orient later sessions: curated, not a record of what happened. They can be "
              "rewritten or out of date. The retention sweep does not delete them. Dates are file times, not "
              "when a line was written.",
    "claude-md": "Standing instructions, not events. Only the user CLAUDE.md and the files added with "
                 "--claude-md. Dates are file times.",
    "plans": "Plans saved as files: what was intended, not what was done. The retention sweep deletes them "
             "with the transcripts. Dates are file times.",
    "docs": "Only the paths added with --docs, and only *.md files. Dates are file times.",
}

BLIND = {
    "transcripts": "sessions unused for over {days} days are deleted{cut}",
    "history": "your side only; not swept (except under the HIPAA configuration)",
    "tool-output": "large outputs only, deleted with transcripts{cut}",
    "memory": "curated notes, not a record",
    "claude-md": "instructions, not events",
    "plans": "intent, not what was done; deleted with transcripts",
    "docs": "only the paths you added",
}


def retention_lines(ret: dict, oldest_ns: int | None) -> list[str]:
    """The retention section of the map."""
    base, short = ret.get("base") or {}, ret.get("shortest")
    lines = [f"- In force: `{RETENTION_KEY}` = {base.get('days', '?')} days, from {base.get('from', '?')}."]
    if short:
        lines.append(f"- Shortest found: {short['days']} days in `{short['path']}`, in force when a session starts in "
                     f"`{short['folder']}`. A project file's value is reported to drive the sweep for every project "
                     f"on the machine ({PROJECT_SWEEP_ISSUE}).")
    user = ret.get("user") or {}
    ignored = ([user] if str(user.get("state", "")).startswith("invalid") else []) + \
        [f for f in ret.get("files", []) if f["state"].startswith("invalid")]
    for f in ignored:
        lines.append(f"- Ignored, Claude Code rejects it: `{f['path']}` is {f['state']}.")
    desktop = ret.get("desktop") or {}
    if desktop.get("state") == "set":
        lines.append(f"- `{DESKTOP_RETENTION_KEY}` in user settings: `{json.dumps(desktop.get('value'))}`.")
    if oldest_ns:
        lines.append(f"- Oldest transcript on disk: last written {short_time(ns_iso(oldest_ns))}.")
    lines += [
        "- What the sweep deletes: transcripts, subagent transcripts, tool output files and plans. history.jsonl "
        f"(except under the HIPAA configuration) and memory files are kept ({DOCS_SWEPT_URL}). Sessions started "
        f"or last continued in Claude Desktop or Cowork are kept unless `{DESKTOP_RETENTION_KEY}` is set "
        f"({DOCS_DESKTOP_URL}).",
        f"- Anthropic's settings reference: \"{DOCS_QUOTE}\" Default {DOCS_DEFAULT_DAYS} days; a whole number, "
        f"minimum 1; 0 fails validation ({DOCS_URL}).",
        f"- Project folders checked: {ret.get('folders', 0)}. For more: `python3 ctm.py retention --project-dir PATH`. "
        "Organization (managed) settings are not read.",
    ]
    return lines


def build_map(con: sqlite3.Connection, db: str) -> str:
    meta = _meta(con)
    rows = store_rows(con)
    tool_chars = int(meta.get("tool_chars") or DEFAULT_TOOL_CHARS)
    cdir = meta.get("claude_dir", "?")
    lines = [
        "# Coverage map",
        "",
        f"Generated by `ctm.py index` ({TOOL_NAME} {VERSION}) at {short_time(meta.get('built_at'))}. "
        "Do not edit: the next `index` run replaces this file.",
        "",
        f"- Index: `{db}`",
        f"- Claude Code folder: `{cdir}` ({meta.get('claude_dir_how', '?')})",
        "",
        "Rule: say \"not found\" only after every store below was searched. A store that is empty, missing "
        "or not configured was not searched, and a search cannot speak for it.",
        "",
        "| Store | Status | Files | Rows | First | Last | Where it lives |",
        "|---|---|--:|--:|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['store']} | {r['status']} | {r['files']:,} | {r['rows']:,} | {short_time(r['first'])} "
                     f"| {short_time(r['last'])} | `{r['where']}` |")
    lines += ["", "## What each store cannot tell you", ""]
    by_store = {r["store"]: r for r in rows}
    for store in STORE_ORDER:
        r = by_store[store]
        note = _tool_note(tool_chars, r["cut"])
        text = CANNOT[store].format(tool_note=note)
        if r["bad"]:
            text += f" {plural(r['bad'], 'line')} could not be read as JSON and {'is' if r['bad'] == 1 else 'are'} not indexed."
        lines.append(f"- **{store}**: {text}")

    lines += ["", "## Retention", ""]
    oldest = con.execute("SELECT MIN(mtime_ns) FROM files WHERE store='transcripts' AND mtime_ns > 0").fetchone()[0]
    lines += retention_lines(json.loads(meta.get("retention") or "{}"), oldest)

    lines += ["", "## Not searched", ""]
    others = json.loads(meta.get("unsearched") or "[]")
    if others:
        lines.append(f"Other entries in `{cdir}` are not searched: {', '.join(others)}.")
    else:
        lines.append(f"No other entries in `{cdir}`.")
    notes = json.loads(meta.get("notes") or "{}")
    if notes.get("aliases"):
        lines.append(f"{plural(notes['aliases'], 'project folder')} {'is a link' if notes['aliases'] == 1 else 'are links'} "
                     "to another project folder; the files were counted once.")
    if notes.get("bad_names"):
        lines.append(f"{plural(notes['bad_names'], 'file')} skipped: the name is not valid UTF-8.")
    lines += ["", "## Why this map exists", "",
              "Memory orients. Transcripts adjudicate. A memory note says what someone decided to keep; the "
              "transcript line is what was said. When they disagree, the transcript line is the evidence, and "
              "every hit from `find` is the address of that line.", ""]
    return "\n".join(lines)


def cmd_map(args) -> int:
    db = db_path(args.db)
    con = connect(db, create=False)
    check_schema(con)
    print(build_map(con, db), end="")
    con.close()
    return 0


# ------------------------------------------------------------------- find

_TERM = re.compile(r'"([^"]*)"|(\S+)')


def build_match(query: str, raw: bool) -> tuple[str, list[str]]:
    """User words -> an FTS5 query that matches each word or "phrase" literally (a trailing * = prefix)."""
    if raw:
        words = [w for w in re.findall(r"\w+", query) if w not in ("AND", "OR", "NOT", "NEAR")]
        return query, words
    parts, terms = [], []
    for m in _TERM.finditer(query):
        phrase, word = m.group(1), m.group(2)
        text, prefix = (phrase, False) if phrase is not None else (word, False)
        if phrase is None and len(text) > 1 and text.endswith("*"):
            text, prefix = text.rstrip("*"), True
        if not re.search(r"\w", text):
            continue
        parts.append('"' + text.replace('"', '""') + '"' + ("*" if prefix else ""))
        terms.append(text)
    if not parts:
        raise CtmError("Nothing to search for: the query has no letters or digits.")
    return " AND ".join(parts), terms


def _locate(body: str, start: int, terms: list[str]) -> int:
    """The line of a text piece that holds the most query terms (the first such line); else the piece start."""
    terms = [t.lower() for t in terms if t.strip()]
    words = sorted({w.lower() for t in terms for w in re.findall(r"\w+", t)})
    best, best_score = start, (0, 0)
    for offset, line in enumerate(body.split("\n")):
        low = line.lower()
        score = (sum(t in low for t in terms), sum(w in low for w in words))
        if score > best_score:
            best, best_score = start + offset, score
    return best


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def cmd_find(args) -> int:
    db = db_path(args.db)
    con = connect(db, create=False)
    meta = check_schema(con)
    query = " ".join(args.query).strip()
    match, terms = build_match(query, args.raw)
    if args.limit < 1:
        raise CtmError("--limit must be 1 or more")
    where, params = ["fts MATCH ?"], [match]
    if args.store:
        where.append("f.store = ?")
        params.append(args.store)
    if args.role:
        where.append("r.role = ?")
        params.append(args.role)
    if args.project:
        where.append("(lower(r.project) LIKE ? ESCAPE '\\' OR lower(r.project) LIKE ? ESCAPE '\\')")
        params += [_like(slugify(args.project).lower()), _like(args.project.lower())]
    if args.since:
        where.append("COALESCE(r.ts, f.mtime_iso) >= ?")
        params.append(bound(args.since, upper=False))
    if args.until:
        where.append("COALESCE(r.ts, f.mtime_iso) < ?")
        params.append(bound(args.until, upper=True))
    source = ("FROM fts CROSS JOIN rows AS r ON r.id = fts.rowid "
              "CROSS JOIN files AS f ON f.id = r.file_id WHERE " + " AND ".join(where))
    order = {"rank": "score, at_", "old": "at_, score", "new": "at_ DESC, score"}[args.sort]
    try:
        hits = con.execute(
            "SELECT r.id, r.line, r.ts, r.role, r.kind, r.session, r.project, r.cut, f.path, f.store, "
            f"COALESCE(r.ts, f.mtime_iso) AS at_, bm25(fts) AS score {source} ORDER BY {order} LIMIT ?",
            params + [args.limit]).fetchall()
        per_store = dict(con.execute(f"SELECT f.store, COUNT(*) {source} GROUP BY f.store", params).fetchall())
    except sqlite3.OperationalError as exc:
        raise CtmError(f"The search engine did not accept the query ({exc}). "
                       "Without --raw every word is matched literally.") from None

    found = sum(per_store.values())
    tool_chars = int(meta.get("tool_chars") or DEFAULT_TOOL_CHARS)
    if hits:
        order_note = {"rank": "best first", "old": "oldest first", "new": "newest first"}[args.sort]
        print(f"{found:,} matches for: {query}   ({order_note}, showing {len(hits)})\n")
    for n, h in enumerate(hits, 1):
        line = h["line"]
        if h["store"] not in JSONL_STORES:
            body = con.execute("SELECT body FROM fts WHERE rowid=?", (h["id"],)).fetchone()[0]
            line = _locate(body, line, terms)
        snip = con.execute("SELECT snippet(fts, 0, '>>', '<<', ' ... ', 24) FROM fts WHERE fts MATCH ? AND rowid=?",
                           (match, h["id"])).fetchone()
        when = short_time(h["at_"]) + ("" if h["ts"] else " (file time)")
        who = f"{h['role'] or '-'}/{h['kind'] or '-'}"
        head = [f"[{n}] {h['store']}", when, who]
        if h["project"]:
            head.append(h["project"])
        if h["session"]:
            head.append(f"session {h['session'][:8]}")
        if h["cut"]:
            head.append(f"first {tool_chars:,} chars indexed")
        print(" | ".join(head))
        print(f"    {h['path']}:{line}")
        print(f"    {' '.join((snip[0] if snip else '').split())}\n")

    rows = store_rows(con)
    searched = [r for r in rows if r["status"] == "indexed"]
    not_searched = [r for r in rows if r["status"] != "indexed"]
    filters = [f"--{k} {getattr(args, k)}" for k in ("store", "project", "since", "until", "role")
               if getattr(args, k)]
    if hits:
        print("Matches per store: " + " | ".join(f"{r['store']} {per_store.get(r['store'], 0):,}" for r in searched))
    else:
        days = (json.loads(meta.get("retention") or "{}")).get("days", DOCS_DEFAULT_DAYS)
        cut = f"; tool text cut at {tool_chars:,} chars" if tool_chars else ""
        print(f"No matches for: {query}")
        print("Searched (dates each store covers | what it cannot hold):")
        for r in searched:
            span = f"{short_time(r['first'])} .. {short_time(r['last'])}"
            print(f"  {r['store']:<12} {span:<36} | {BLIND[r['store']].format(days=days, cut=cut)}")
    if not_searched:
        print("Not searched: " + ", ".join(f"{r['store']} ({r['status']})" for r in not_searched))
    if filters:
        print("Filters: " + " ".join(filters))
    if not hits:
        print("Every word must appear in the same record. Try fewer words, or a prefix such as deploy*.")
    print(f"Index updated {short_time(meta.get('built_at'))}; what each store cannot tell you: python3 ctm.py map")
    con.close()
    return 0


# -------------------------------------------------------------- retention

def cmd_retention(args) -> int:
    cdir, how = resolve_claude_dir(args.claude_dir)
    info = retention_info(cdir, args.project_dir)
    user = info["user"]
    print(f"Claude Code folder: {cdir} ({how})\n")
    print(f"{RETENTION_KEY} in the settings files found:")
    rows = [("user settings", user["path"], user["state"], user["days"])]
    rows += [(f["label"], f["path"], f["state"], f["days"]) for f in info["files"]]
    for label, path, state, days in rows:
        shown = str(days) if days is not None else f"({state})"
        print(f"  {label:<24} {shown:<10} {path}")
    print(f"  Project folders checked: {info['folders']}. Sessions ran in {plural(info['from_sessions'], 'folder')} "
          f"(read from transcripts and history.jsonl), {info['gone']} of them gone; {info['given']} given with --project-dir.")
    print("  Organization (managed) settings override all of these. This tool does not read them;")
    print("  /status in Claude Code lists the setting sources in use.")

    base, short = info["base"], info["shortest"]
    print("\nIn force:")
    print(f"  where no project file sets it: {base['days']} days, from {base['from']}")
    if short:
        print(f"  shortest: {short['days']} days, when a session starts in {short['folder']}")
        print(f"            ({short['label']}: {short['path']})")
        print("  The sweep runs after a session starts, with that session's settings. A project file's value is")
        print(f"  reported to drive the sweep for every project on the machine: {PROJECT_SWEEP_ISSUE}")
        print("  Plan for the shortest value.")
    desktop = info["desktop"]
    if desktop["state"] == "set":
        print(f"  {DESKTOP_RETENTION_KEY} in user settings: {json.dumps(desktop['value'])} (0 means no age limit)")

    print(f"\nAnthropic's settings reference ({DOCS_URL}):")
    print(f"  \"{DOCS_QUOTE}\"")
    print(f"  A whole number of days, minimum 1, default {DOCS_DEFAULT_DAYS}. 0 fails validation; for long retention the")
    print("  reference suggests a large value such as 3650. The sweep shows no message.")
    print("  Sessions started or last continued in Claude Desktop or Cowork are kept at any age unless")
    print(f"  {DESKTOP_RETENTION_KEY} is set (user or managed settings): {DOCS_DESKTOP_URL}")
    print("  history.jsonl (except under the HIPAA configuration) and auto-memory files are not swept:")
    print(f"  {DOCS_SWEPT_URL}")

    stamps = []
    for src in discover(cdir, [], [])[0]:
        if src.store == "transcripts":
            try:
                stamps.append((os.stat(src.path).st_mtime_ns, src.path))
            except OSError:
                continue
    days = info["days"]
    if stamps:
        oldest_ns, oldest_path = min(stamps)
        age = (dt.datetime.now(UTC) - dt.datetime.fromtimestamp(oldest_ns / 1e9, UTC)).days
        print(f"\nTranscripts on disk: {len(stamps):,} files under {os.path.join(cdir, 'projects')}")
        print(f"  oldest, by last write: {short_time(ns_iso(oldest_ns))} ({age} days ago)")
        print(f"  {oldest_path}")
        if age > days:
            print(f"  It is older than {days} days and still on disk.")
    else:
        print(f"\nTranscripts on disk: none under {os.path.join(cdir, 'projects')}")

    print(f"\nWhat it means: the transcripts of sessions not used for more than {days} days are deleted at the next")
    print("sweep, without a message. The index is not a backup: when Claude Code deletes a transcript, the next")
    print("`index` run drops its text too. To keep a transcript, copy the file.")
    print(f"\nTo change it, edit the settings yourself (this tool never writes settings). For example, in {user['path']}:")
    print(f'  {{ "{RETENTION_KEY}": 3650 }}')
    if short:
        print("and raise or remove the shorter project values listed above.")
    return 0


# -------------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ctm.py",
        description="One search box over the records Claude Code keeps on your disk. "
                    "Local only: no network access.")
    parser.add_argument("--version", action="version", version=f"{TOOL_NAME} {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{index,find,map,retention}")
    db_opt = argparse.ArgumentParser(add_help=False)
    db_opt.add_argument("--db", metavar="PATH", help=f"index file (default: {default_db()})")
    dir_opt = argparse.ArgumentParser(add_help=False)
    dir_opt.add_argument("--claude-dir", metavar="PATH",
                         help="Claude Code folder (default: $CLAUDE_CONFIG_DIR, else ~/.claude)")

    p = sub.add_parser("index", parents=[db_opt, dir_opt], help="find the stores and build or update the index",
                       description="Find every store and index it. Files whose size and time are unchanged are "
                                   "skipped; transcripts that only grew are read from where the last run stopped.")
    p.add_argument("--claude-md", action="append", default=[], metavar="PATH",
                   help="also index this CLAUDE.md file, or the CLAUDE.md files in this project folder (remembered)")
    p.add_argument("--docs", action="append", default=[], metavar="PATH",
                   help="also index the *.md files under this folder (remembered)")
    p.add_argument("--forget", action="append", default=[], metavar="PATH",
                   help="stop indexing a path added with --claude-md or --docs")
    p.add_argument("--tool-chars", type=int, metavar="N",
                   help=f"characters indexed per tool call or tool output (default {DEFAULT_TOOL_CHARS}; 0 = all)")
    p.add_argument("--full", action="store_true", help="rebuild the index from scratch")
    p.add_argument("-q", "--quiet", action="store_true", help="print nothing unless something fails")

    p = sub.add_parser("find", parents=[db_opt], help="search every indexed store",
                       description="Search every indexed store. Each hit prints path:line, the address of the raw "
                                   "record. Every word must appear in the same record; \"quotes\" keep a phrase "
                                   "together and a trailing * matches a prefix.")
    p.add_argument("query", nargs="+", help="words to find")
    p.add_argument("--store", choices=STORE_ORDER, help="search one store only")
    p.add_argument("--project", metavar="TEXT", help="project folder path, or part of its name")
    p.add_argument("--since", metavar="DATE", help="on or after this date (YYYY-MM-DD, UTC)")
    p.add_argument("--until", metavar="DATE", help="on or before this date (YYYY-MM-DD, UTC)")
    p.add_argument("--role", choices=ROLES, help="who wrote it: user (a person), assistant (Claude), tool, system")
    p.add_argument("--limit", type=int, default=20, help="hits to show (default 20)")
    p.add_argument("--sort", choices=("rank", "old", "new"), default="rank", help="order of hits (default rank)")
    p.add_argument("--raw", action="store_true", help="pass the query to SQLite FTS5 as written (OR, NOT, NEAR)")

    sub.add_parser("map", parents=[db_opt], help="print the coverage map",
                   description="Print the coverage map written by the last index run: every store, where it "
                               "lives, how much was indexed, and what it cannot tell you.")

    p = sub.add_parser("retention", parents=[dir_opt], help="show how long Claude Code keeps transcripts",
                       description="Read cleanupPeriodDays from the user settings and from every project "
                                   "settings file found (in folders where sessions ran, and under --project-dir), "
                                   "show the shortest value in force and the oldest transcript still on disk. "
                                   "Never changes any setting.")
    p.add_argument("--project-dir", action="append", default=[], metavar="PATH",
                   help="also check the .claude settings files in this folder and the folders under it "
                        "(up to four levels down)")
    return parser


COMMANDS = {"index": cmd_index, "find": cmd_find, "map": cmd_map, "retention": cmd_retention}


def _dash_values(argv: list[str]) -> list[str]:
    """Project folder names start with '-' (they are paths); let `--project -work-app` mean `--project=-work-app`."""
    out: list[str] = []
    for arg in argv:
        if out and out[-1] == "--project" and arg.startswith("-") and not arg.startswith("--") and len(arg) > 2:
            out[-1] = f"--project={arg}"
        else:
            out.append(arg)
    return out


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    args = build_parser().parse_args(_dash_values(list(sys.argv[1:] if argv is None else argv)))
    try:
        return COMMANDS[args.command](args)
    except CtmError as exc:
        print(f"{TOOL_NAME}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(1)
