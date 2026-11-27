# Memory notes

You have a persistent, file-based memory. It is shared with the Claude Code and Codex sessions that work in the same project, and it lives outside the repository:

    ~/.claude/projects/<the project's path with every "/" replaced by "-">/memory/

For `/Users/derekbredensteiner/Developer/homesodamachine` that folder is `/Users/derekbredensteiner/.claude/projects/-Users-derekbredensteiner-Developer-homesodamachine/memory/`.

`MEMORY.md` in that folder is the index, and it is part of your instructions. Each line points at one note file in the same folder. Read a note with the read tool when its line bears on the task. A note records what was true when it was written. If it names a file, function or flag, check that it still exists before relying on it.

## Writing a note

A note is one file holding one fact, with this frontmatter:

```markdown
---
name: <short-kebab-case-slug>
description: <one-line summary, used later to decide relevance>
metadata:
  type: user | feedback | project | reference
  model: <app, model, effort>
---

<the fact. For feedback and project notes, follow with **Why:** and **How to apply:** lines. Link related notes as [[their-name]].>
```

`model` is the `Model:` line that `python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py whoami` prints, without its label. It names the app and model that wrote the note.

- `user`: who the user is, their role, expertise and preferences.
- `feedback`: guidance the user gave on how to work, corrections and confirmed approaches alike, with the reason.
- `project`: ongoing work, goals or constraints that the code and Git history do not record. Write dates as absolute dates.
- `reference`: pointers to outside resources such as URLs, dashboards and tickets.

After writing the file, add one line for it to `MEMORY.md`: `- [Title](file.md) — hook`. The index holds one line per note and none of a note's content.

Before saving, look for a note that already covers the subject and update that one. Delete a note that turns out to be wrong.

Save what is both applicable and durable: it would change what a later session does, and it holds across sessions and tasks. Leave out what the repository already records (code structure, past fixes, Git history, `AGENTS.md`), what matters only to this conversation, and records of finished work.
