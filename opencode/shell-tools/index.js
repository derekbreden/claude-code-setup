// Gives OpenCode's shell tool the grep and find that Claude Code's own shell uses on this Mac.
//
// Claude Code's Bash tool defines `grep` and `find` as shell functions over the ugrep and bfs
// built into the claude binary: ignore files are honoured and .git and binary files are skipped.
// OpenCode's shell tool runs the system's, so a whole-tree `grep -r` walks build outputs and
// caches and takes minutes where Claude Code's takes seconds. This plugin puts bin/, which holds
// the same two commands as scripts, at the front of PATH for every command the shell tool runs.

import path from "node:path"
import { fileURLToPath } from "node:url"

const BIN = path.join(path.dirname(fileURLToPath(import.meta.url)), "bin")

export default {
  id: "shell-tools",
  async setup(ctx) {
    await ctx.shell.hook("create.before", (event) => {
      const current = event.env.PATH ?? process.env.PATH ?? ""
      if (!current.split(":").includes(BIN)) event.env.PATH = current ? `${BIN}:${current}` : BIN
    })
  },
}
