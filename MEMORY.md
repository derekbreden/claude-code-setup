jsonl2md is the export tool; the user's main work lives in homesodamachine (the home soda machine appliance). It exports Claude conversations to `.md`, often re-fed into new Claude Code sessions via `@path` syntax (the export-and-continue pattern). DEFAULT_CWD in jsonl2md.py points at `/Users/derekbredensteiner/Developer/homesodamachine`. The README and jsonl2md.py cover what this tool does.

When extending: `git log` first. The history is curated — each commit is a design beat with prose; superseded work gets folded back via rebase rather than appended. Follow that example.
