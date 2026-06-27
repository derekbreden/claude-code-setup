# jsonl2md

Export Claude conversations from the macOS Claude.app desktop client to clean Markdown.

This is a personal tool, put on GitHub in case it helps someone with the same setup. It is not a polished, configurable, cross-platform library — read the next section before assuming it'll work for you.

## Who this is for

You'll get value from this if **all** of the following are true:

- You're on **macOS** and use [Claude.app](https://claude.ai/download) (the desktop client).
- You want plain Markdown transcripts of either:
  - **Claude Code sessions** that show in the Claude.app sidebar — i.e. ones you've given a custom title and not archived, **or**
  - **Main Claude.ai chats** from the same desktop app's sidebar (recent N).
- You want **just the spoken text** — what you typed and what Claude wrote back. Nothing else.

You will *not* get value from this if:

- You're on **Linux or Windows**. Cookie decryption uses the macOS Keychain; session paths are macOS-specific.
- You want **tool calls, tool results, thinking blocks, system reminders, attachments, or files** in the output. They are dropped on purpose.
- You want to export **Claude Code sessions you haven't given a custom title to**, or sessions you've archived. The filter requires `titleSource: "user"` and `isArchived: false`. There is no flag to widen this.
- You need a **UI, fuzzy matching, partial-name search, paging beyond a single `--limit`, or anything beyond a list-and-export CLI**.

When I went looking for a tool that did this, I couldn't find one. Maybe the audience is small, but it's not zero.

## What it does

Two sources, each with a list verb and an export verb, plus a standalone renderer:

| Source | List | Export |
| --- | --- | --- |
| Claude Code sessions (current project) | `list-sessions` | `export-session "<title>"` |
| Claude.ai chats (desktop app sidebar)  | `list-chats`    | `export-chat "<name>"` |

`export-session` and `export-chat` both accept `--all` and `--out <dir>`. The chat commands also accept `--limit N` (default 30) since the Claude.ai API is paged.

Plus `render <path.jsonl>` — standalone, render any Claude Code transcript file (or stdin) to Markdown on stdout, no metadata lookup.

Run `./jsonl2md.py` with no arguments to see the full help and example commands.

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

See [SALON.md](SALON.md) for the human-mediated session-to-session relay workflow these commands are built for.

## Install

```sh
pip install -r requirements.txt
```

That installs `cryptography` (used to decrypt Claude.app's cookie store on macOS).

Optional — install the `/relay` slash command (the Salon Protocol's invocation surface; see [SALON.md](SALON.md)):

```sh
ln -s "$PWD/commands/relay.md" ~/.claude/commands/relay.md
```

## Usage

```sh
# Claude Code sessions (current project on disk)
./jsonl2md.py list-sessions
./jsonl2md.py list-sessions --cwd /Users/me/some-other-project
./jsonl2md.py export-session "Professor - done"
./jsonl2md.py export-session "Professor - done" --out ~/Desktop
./jsonl2md.py export-session --all --out ./exports

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
- **Tool calls, tool results, thinking blocks, system messages, attachments, and files are unconditionally stripped.** There is no flag to include them. The whole reason the tool exists is to produce a transcript of just the spoken text.
- **Output filenames are the session/chat title verbatim**, with `/`, `\`, and `:` replaced by `_`. Filename collisions silently overwrite.
- **macOS only.** The cookie decryption format, keychain service name, and filesystem paths are all macOS-specific. A Linux/Windows port would need new code in three places.
- **No license file.** Treat it as a reference implementation; copy what's useful.

## Samples

`samples/` has two real exports — `Professor - done` and `Chief of Staff - Beta Testers` — as `.md` files, so you can see what the output looks like before installing anything.
