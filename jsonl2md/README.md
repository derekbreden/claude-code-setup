# jsonl2md

Export Claude conversations and local Codex tasks to clean Markdown.

This is a personal tool, put on GitHub in case it helps someone with the same setup. It is not a polished, configurable, cross-platform library — read the next section before assuming it'll work for you.

## Who this is for

You'll get value from this if **all** of the following are true:

- You're on **macOS** and use [Claude.app](https://claude.ai/download), the Codex desktop app,
  or both.
- You want plain Markdown transcripts of either:
  - **Claude Code sessions** that show in the Claude.app sidebar — i.e. ones you've given a custom title and not archived, **or**
  - **Main Claude.ai chats** from the same desktop app's sidebar (recent N), **or**
  - **User-titled Codex tasks** in the current project.
- You want **just the spoken text** — what you typed and what Claude wrote back. Nothing else.

You will *not* get value from this if:

- You're on **Linux or Windows**. Cookie decryption uses the macOS Keychain; session paths are macOS-specific.
- You want **tool calls, tool results, thinking blocks, system reminders, attachments, or files** in the output. They are dropped on purpose.
- You want to export untitled or archived sessions. The Claude and Codex task lists are deliberately the user-titled, non-archived surface.
- You need a **UI, fuzzy matching, partial-name search, paging beyond a single `--limit`, or anything beyond a list-and-export CLI**.

When I went looking for a tool that did this, I couldn't find one. Maybe the audience is small, but it's not zero.

## What it does

Three sources, each with a list verb and an export verb, plus a standalone renderer:

| Source | List | Export |
| --- | --- | --- |
| Claude Code sessions (current project, local and cloud) | `list-sessions` | `export-session "<title>"` |
| Claude.ai chats (desktop app sidebar)  | `list-chats`    | `export-chat "<name>"` |
| Codex desktop tasks (current project) | `list-codex-sessions` | `export-codex-session "<title>"` |

Plus two views across the whole project at once: `recent-prompts` — the last things *you*
asked for, newest first — and `situation`, the board of every session, how to reach it, and
whether it is still moving.

`export-session` and `export-chat` both accept `--all` and `--out <dir>`. The chat commands also accept `--limit N` (default 30) since the Claude.ai API is paged.

Plus `render <path.jsonl>` — standalone, render any Claude Code transcript file (or stdin) to Markdown on stdout, no metadata lookup.

Run `./jsonl2md.py` with no arguments to see the full help and example commands.

The Codex export reads the desktop app's normalized local history projection and keeps
only user-authored messages and visible assistant prose. Reasoning, commands, tool calls
and outputs, system/developer context, and peer-task delivery envelopes do not enter the
Markdown.

### Your side of it: `recent-prompts`

The exports are per session, and a transcript is mostly agent. `recent-prompts` inverts
both: it reads every session in the project, keeps only the turns **you** typed, and prints
them newest first with the timestamp and the exact place each one lives.

```sh
./jsonl2md.py recent-prompts                     # top 5, in full
./jsonl2md.py recent-prompts -n 20 --chars 300   # more of them, each clipped
./jsonl2md.py recent-prompts --session "PCB clean"
./jsonl2md.py recent-prompts -n 0 --json         # all of them, machine-readable
```

```
2026-08-26 22:32:21 -0500  Zip tie 2
  ~/.claude/projects/-Users-…-homesodamachine/73e77039-….jsonl:3  a162cee0-97f6-…
  | /relay Zip tie
  |
  | Whatever this agent claimed as "not mine" please take ownership of and see to resolution.
```

The user side of a transcript is not all speech. Tool results come back as role `user`, and
so does everything the harness posts under your name: background-task notifications, local
command output, the expanded body of a slash command, a peer session's message. All of that
is dropped. A slash command renders as the line you actually typed (`/relay Zip tie`), an
attached quote keeps the quote and loses its marker, and spliced-in system reminders are cut
out. The same filter now runs for every verb, so `export-session` and `delta` are clean too.

One case reads the other way. A slash command normally arrives wearing an envelope, but one
that never expands arrives flagged the same way an injected body is, carrying nothing but the
line that was typed. That line is speech — a fleet driven by slash commands reads as an empty
one without it — and its shape is what separates the two: across 1795 flagged records in this
corpus, a lone command line matched once, and it was the invocation.

`--since` turns it into a question with a yes/no answer, and the exit status carries that
answer — 0 if anything falls in the window, 1 if nothing does. That is the gate an automated
caller needs:

```sh
./jsonl2md.py recent-prompts --since 1h -n 0 --exclude "$MY_SESSION" || exit 0
```

`--exclude` takes a title, a `cliSessionId` prefix, or the peer address an untitled session
answers to, and is repeatable. A tool that reads its own session counts its own prompts as the
human's and finds work it already did, so anything automated passes its own id here — and
because a helper is spawned rather than named, the exclusion has to reach untitled sessions or
it fails for the one caller that depends on it.

The question this gate asks is whether the human is here, so it looks where he talks, which
includes sessions that have not been titled yet. A new session is untitled until it earns a
name, which makes it the likeliest home of the freshest thing he said.

### Who else is here: `situation`

```
SESSION             ADDRESS             STATE     STOPPED    ASKED  LAST
3mf                 3mf                 working         -      21m  `changed()` now reports only my own two files…
Zip tie 2           Zip tie 2           STOPPED        2m      30m  Not mine — that's another session hardening…
Manager 3           (relay only)        -               -    2h09m  > B — Box contains Pack instead of copying it…
Clearances          homesodamachine-b0  STOPPED    11h06m   11h12m  Done and settled. **14/14 checks green…
```

A session is a title to you, a `name` to `SendMessage`, and a pid to the process table, and
those three disagree — "Clearances" answers to `homesodamachine-b0`. Joining them by name is
the mistake waiting to be made, so this joins them by `cliSessionId`, which all three carry.
The state column comes from [`peer_idle.py`](peer_idle.py), imported rather than
reimplemented. Live sessions that were never titled fold in under their peer name in
parentheses: invisible to `list-sessions` by design, but still workers, still reachable, and
possibly the ones holding something nobody owns. They run through `--exclude` on the way in,
the same as the titled half.

### The rules under test: `selftest`

```sh
./jsonl2md.py selftest      # prints N/N, exits 1 on failure
```

Two rules here fail silently when they break, which is why they are the ones held. A gate that
cannot see the human reports a quiet hour and the routine simply does not run. An `--exclude`
that misses reads a helper's own work back to it as a peer's. Neither raises, neither shows up
in output anyone reads, and both would sit broken indefinitely. Each case was checked against
a deliberately broken copy of the code it guards, so a case that stops holding fails rather
than passing on a mutation.

### Reading everything at once: `--compact`

A long session is mostly agent. Between two things you said there can be dozens of assistant
messages, one per tool step, and the shape of that run reads off its first lines and its
last: what it set out to do, and what it landed. The middle is the working.

`--compact [N]` coalesces each run of consecutive assistant turns into one block and cuts
that middle out, keeping N lines at either end (default 6). **Your own turns are never cut** —
they are the spine the rest hangs off, and the reason to read a compacted transcript at all.

```sh
./jsonl2md.py export-session --all --compact --out ./compact   # every titled session
./jsonl2md.py export-session --all --compact 3 --out ./tighter
./jsonl2md.py delta "PCB clean" --tail 40 --compact
./jsonl2md.py render path/to/session.jsonl --compact
```

The cut is marked in place, and it counts both what it removed and how many messages it
spanned:

```
[... 39 lines across 11 messages ...]
```

Across twelve live sessions that is roughly 500 KB of transcript down to 100 KB — small
enough to read the whole project's dialogue in one pass.

### Sharing only what's new: `delta` and `watch`

`export-session` always dumps the whole conversation. When you're relaying one session into another and only want *what changed since you last shared*, use `delta`:

| Command | Effect |
| --- | --- |
| `delta "<title>"` | print the user/assistant turns added since the last `--commit` — a **preview** that does *not* advance the cursor |
| `delta "<title>" --commit` | same, and mark those turns as shared (advance the cursor) |
| `delta "<title>" --tail K` | ignore the cursor; print just the last K exchanges |
| `delta "<title>" --reset` | forget the cursor and share from the start |
| `delta "<title>" --first-share` | confirm emitting a whole transcript when no cursor exists yet |
| `watch "<title>"` | stream new turns to your terminal as the session grows (Ctrl-C to stop) |

The positional accepts an exact session title **or** a raw `cliSessionId`, so untitled/archived sessions stay reachable. The cursor lives per session at `~/.jsonl2md/cursors/<cliSessionId>.json` and anchors on the last transcript *record* seen — not the last rendered turn — so the ~70% of records that are tool/thinking plumbing between two turns never desync the delta. The cursor advances **only** on `--commit`, so it always reflects what you actually relayed, never what you merely previewed.

See [SALON.md](SALON.md) for the `/relay` pull workflow these commands back — bringing one session's clean transcript into another.

## Install

```sh
pip install -r requirements.txt
```

That installs `cryptography` (used to decrypt Claude.app's cookie store on macOS).

Optional — install the `/relay` pull command (see [SALON.md](SALON.md)):

```sh
ln -s "$PWD/commands/relay.md" ~/.claude/commands/relay.md
```

## Usage

```sh
# Codex desktop tasks (current project on disk)
./jsonl2md.py list-codex-sessions
./jsonl2md.py export-codex-session "Manager 2" --out /tmp

# Claude Code sessions (current project on disk)
./jsonl2md.py list-sessions
./jsonl2md.py list-sessions --cwd /Users/me/some-other-project
./jsonl2md.py export-session "Professor - done"
./jsonl2md.py export-session "Professor - done" --out ~/Desktop
./jsonl2md.py export-session --all --out ./exports
./jsonl2md.py export-session --all --compact --out ./compact

# What you asked for most recently, across every session
./jsonl2md.py recent-prompts
./jsonl2md.py recent-prompts -n 20 --chars 300

# Hold the rules the automated callers depend on
./jsonl2md.py selftest

# Claude.ai chats (desktop app sidebar)
./jsonl2md.py list-chats
./jsonl2md.py list-chats --limit 50
./jsonl2md.py export-chat "Go to Market Strategy"
./jsonl2md.py export-chat --all --limit 10 --out ./chat-exports

# Share only what's new since you last shared
./jsonl2md.py delta "Professor - done"            # preview new turns; cursor untouched
./jsonl2md.py delta "Professor - done" --commit   # same, and mark them shared
./jsonl2md.py delta "Professor - done" --tail 2   # just the last 2 exchanges
./jsonl2md.py watch "Professor - done"            # stream new turns live as they land

# Standalone: any Claude Code .jsonl file
./jsonl2md.py render path/to/session.jsonl > out.md
cat session.jsonl | ./jsonl2md.py render > out.md
```

## How it finds things

**Claude Code sessions:**

- Metadata is read from `~/Library/Application Support/Claude/claude-code-sessions/<workspace>/<device>/local_*.json`. Each metadata file has `cliSessionId`, `cwd`, `title`, `titleSource`, `isArchived`, `lastActivityAt`. The filter is `cwd == --cwd` AND `isArchived == false` AND `titleSource == "user"`.
- Transcripts are at `~/.claude/projects/<cwd-with-/-replaced-by-->/<cliSessionId>.jsonl`.

**Cloud sessions:**

A session started in the Code section of the desktop app can run on Anthropic's machines. It
has a title you gave it and a transcript you can read, and neither is on this disk — the only
local trace is its id in `remote-session-spaces.json`. So it is read the way the CLI reads it:

- `GET https://api.anthropic.com/v1/code/sessions` for the list, `…/events` for the transcript.
  Event payloads are Claude Code transcript records already, so they render through the same
  path as a `.jsonl`; only the flags marking a record as machine-written differ in spelling.
- Auth is the OAuth grant `claude` signed in with, read from the Keychain item
  `Claude Code-credentials` (or `~/.claude/.credentials.json`) and refreshed when it has aged
  out. The refresh token rotates on use, so the new grant is written back where the CLI looks.
- A cloud worker has no working directory, so a cloud session is matched to a project by **git
  remote** — two checkouts of one repo see the same cloud sessions.
- Only `environment_kind == "anthropic_cloud"` is listed. A cloud record also exists for each
  session running *here* (`bridge`), and that one is already listed from its own metadata and
  its own transcript.
- The list is cached for a minute under `~/.jsonl2md/cloud/`, which is what keeps a listing
  as fast as it was when every session was a file — on the warm path the added work is one
  JSON read and an `origin` URL parsed out of `.git/config`. A transcript is cached
  against the session's `last_event_at` — a session that has not gained an event cannot have
  changed. When the network is gone the stale copy is served, so the sessions that *are* on
  this disk still list. `JSONL2MD_NO_CLOUD=1` skips the cloud entirely.
- Reading is the whole of it: `send` refuses a cloud target, because the relay mailbox is a
  directory under this HOME that a worker on another machine never looks in.

**Claude.ai chats:**

- The script reads encrypted cookies from `~/Library/Application Support/Claude/Cookies` and decrypts them with the AES key stored in your macOS Keychain under `Claude Safe Storage` / `Claude Key`. The first run prompts for keychain access — pick **Always Allow** if you want it silent thereafter.
- It then calls `https://claude.ai/api/organizations/<lastActiveOrg>/chat_conversations` and `/chat_conversations/<uuid>` with that session cookie.

## Output format

Every user/assistant turn renders as:

```
---

# User

---

{content}
```

The `---` lines are wrapped in blank lines so they render as horizontal rules in any standard Markdown viewer; the `# User` / `# Assistant` between them gives an unambiguous, scrollable speaker label.

## Intentional trade-offs

This list exists because each item is a thing somebody might reasonably want different and won't get without forking:

- **`DEFAULT_CWD` is hardcoded to the author's project path.** Pass `--cwd` every time, or change the constant at the top of `jsonl2md.py` in your fork.
- **The session filter is fixed.** `list-sessions` and `export-session` only see custom-titled, non-archived sessions in the target cwd. There is no flag to widen it. Sessions you never named are invisible to this tool — that's the whole point of the filter, since it matches Claude.app's visible sidebar exactly.
- **`list-chats` and `export-chat --all` are bounded by `--limit`** (default 30). The Claude.ai API supports paging; I have never needed it. Bump the limit if you need older chats.
- **Tool calls, tool results, thinking blocks, system messages, attachments, and files are unconditionally stripped.** There is no flag to include them. The whole reason the tool exists is to produce a transcript of just the spoken text. That includes the things the harness posts under *your* name — task notifications, peer-session messages, command bodies, local command output — which are system messages wearing a user record.
- **Output filenames are the session/chat title verbatim**, with `/`, `\`, and `:` replaced by `_`. Filename collisions silently overwrite.
- **macOS only.** The cookie decryption format, keychain service names, and filesystem paths are all macOS-specific. A Linux/Windows port would need new code in three places.
- **Cloud reads cost a network round trip**, and the OAuth refresh writes back to your Keychain. Both are what the CLI itself does; `JSONL2MD_NO_CLOUD=1` opts out of the whole path.
- **No license file.** Treat it as a reference implementation; copy what's useful.

## Samples

`samples/` has two real exports — `Professor - done` and `Chief of Staff - Beta Testers` — as `.md` files, so you can see what the output looks like before installing anything.
