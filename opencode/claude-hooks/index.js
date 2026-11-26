// Runs Claude Code's command hooks inside OpenCode.
//
// ~/.claude/settings.json and a project's .claude/settings.json name command hooks by event.
// This plugin runs those same commands at OpenCode's matching points and gives each one the
// JSON Claude Code sends, so one set of hook scripts serves both harnesses. ../README.md has
// the table of events, hook points and what is not carried.

import { spawn } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"

const HOME = os.homedir()
const STATE = path.join(process.env.XDG_STATE_HOME || path.join(HOME, ".local", "state"), "opencode-claude-hooks")
const TRANSCRIPTS = path.join(STATE, "transcripts")
const LOG = path.join(STATE, "bridge.jsonl")
const EXTRA_PATH = ["/opt/homebrew/bin", "/usr/local/bin"]
const MAX_STOP_BLOCKS = 5
const VERDICT_TTL_MS = 120_000

// ---- hook configuration -------------------------------------------------------------------

const settingsCache = new Map()

function hooksIn(file) {
  let stat
  try {
    stat = fs.statSync(file)
  } catch {
    return {}
  }
  const hit = settingsCache.get(file)
  if (hit && hit.mtimeMs === stat.mtimeMs) return hit.hooks
  let hooks = {}
  try {
    hooks = JSON.parse(fs.readFileSync(file, "utf8")).hooks || {}
  } catch {}
  settingsCache.set(file, { mtimeMs: stat.mtimeMs, hooks })
  return hooks
}

// Claude Code matches a group's `matcher` against the tool name as a regular expression.
// An event that carries no tool (UserPromptSubmit, Stop) ignores matchers.
function matcherFits(matcher, toolName) {
  if (toolName === undefined || !matcher || matcher === "*") return true
  try {
    return new RegExp(`^(?:${matcher})$`).test(toolName)
  } catch {
    return matcher === toolName
  }
}

function commandsFor(eventName, toolName, project) {
  const files = [path.join(HOME, ".claude", "settings.json")]
  if (project)
    files.push(path.join(project, ".claude", "settings.json"), path.join(project, ".claude", "settings.local.json"))
  const seen = new Set()
  const out = []
  for (const file of files)
    for (const group of hooksIn(file)[eventName] || []) {
      if (!matcherFits(group.matcher, toolName)) continue
      for (const hook of group.hooks || []) {
        if (hook.type !== "command" || !hook.command || seen.has(hook.command)) continue
        seen.add(hook.command)
        out.push(hook)
      }
    }
  return out
}

// ---- running one hook ---------------------------------------------------------------------

function run(hook, payload, session) {
  return new Promise((resolve) => {
    const env = { ...process.env, CLAUDE_PROJECT_DIR: session.project }
    const parts = (env.PATH || "/usr/bin:/bin:/usr/sbin:/sbin").split(":")
    env.PATH = [...EXTRA_PATH.filter((dir) => !parts.includes(dir)), ...parts].join(":")
    let stdout = ""
    let stderr = ""
    let timedOut = false
    let child
    try {
      child = spawn("/bin/bash", ["-c", hook.command], { cwd: session.directory, env, stdio: ["pipe", "pipe", "pipe"] })
    } catch (error) {
      resolve({ code: -1, stdout, stderr: String(error), timedOut })
      return
    }
    const timer = setTimeout(() => {
      timedOut = true
      child.kill("SIGKILL")
    }, (hook.timeout || 60) * 1000)
    child.stdout.on("data", (chunk) => (stdout += chunk))
    child.stderr.on("data", (chunk) => (stderr += chunk))
    child.on("error", (error) => {
      clearTimeout(timer)
      resolve({ code: -1, stdout, stderr: String(error), timedOut })
    })
    child.on("close", (code) => {
      clearTimeout(timer)
      resolve({ code, stdout, stderr, timedOut })
    })
    child.stdin.on("error", () => {})
    child.stdin.end(JSON.stringify(payload))
  })
}

// What a finished hook asks for, in Claude Code's terms: exit 2 blocks with stderr as the
// reason; exit 0 with JSON on stdout carries a decision or added context.
function outcomeOf(eventName, result) {
  const out = {}
  if (result.timedOut) return out
  if (result.code === 2) {
    const reason = result.stderr.trim() || "Blocked by a hook."
    if (eventName === "PreToolUse") out.deny = reason
    else out.block = reason
    return out
  }
  if (result.code !== 0) return out
  const text = result.stdout.trim()
  if (!text) return out
  let json
  if (text.startsWith("{")) {
    try {
      json = JSON.parse(text)
    } catch {}
  }
  if (!json) {
    if (eventName === "UserPromptSubmit") out.context = text
    return out
  }
  const specific = json.hookSpecificOutput || {}
  if (eventName === "PreToolUse") {
    const decision =
      specific.permissionDecision ||
      (json.decision === "block" ? "deny" : json.decision === "approve" ? "allow" : undefined)
    const reason = specific.permissionDecisionReason || json.reason || ""
    if (decision === "deny") out.deny = reason || "Denied by a hook."
    if (decision === "ask") out.ask = reason || "A hook asks for confirmation."
  } else if (json.decision === "block") {
    out.block = json.reason || "Blocked by a hook."
  }
  if (typeof specific.additionalContext === "string" && specific.additionalContext.trim())
    out.context = specific.additionalContext
  return out
}

function log(entry) {
  try {
    fs.mkdirSync(STATE, { recursive: true })
    fs.appendFileSync(LOG, JSON.stringify({ ts: new Date().toISOString(), ...entry }) + "\n")
  } catch {}
}

async function fire(eventName, toolName, payload, session) {
  const hooks = commandsFor(eventName, toolName, session.project)
  if (hooks.length === 0) return []
  const transcript = path.join(TRANSCRIPTS, `${session.root}.jsonl`)
  const input = {
    session_id: session.root,
    transcript_path: transcript,
    cwd: session.directory,
    hook_event_name: eventName,
    ...payload,
  }
  const results = await Promise.all(hooks.map((hook) => run(hook, input, session)))
  return results.map((result, index) => {
    const outcome = outcomeOf(eventName, result)
    const failed = result.timedOut || (result.code !== 0 && result.code !== 2)
    if (failed || Object.keys(outcome).length > 0)
      log({
        event: eventName,
        tool: toolName,
        hook: path.basename(hooks[index].command),
        session: session.root,
        code: result.code,
        timedOut: result.timedOut || undefined,
        outcome: Object.keys(outcome),
        stderr: failed ? result.stderr.slice(0, 400) : undefined,
      })
    return outcome
  })
}

// ---- OpenCode's tools in Claude Code's names ---------------------------------------------

function shellQuote(text) {
  return `'${String(text).replaceAll("'", `'\\''`)}'`
}

function absolute(value, directory) {
  if (typeof value !== "string" || value === "") return value
  if (value === "~") return HOME
  if (value.startsWith("~/")) return path.join(HOME, value.slice(2))
  return path.resolve(directory, value)
}

// A hook written for Claude Code reads tool_name and tool_input in Claude Code's shape.
// A shell call with its own working directory reads as `cd <dir> && <command>`, which is what
// the same call looks like in Claude Code.
function asClaudeTool(tool, raw, directory) {
  const input = raw && typeof raw === "object" ? raw : {}
  switch (tool) {
    case "edit":
      return {
        name: "Edit",
        paths: [absolute(input.path, directory)],
        input: {
          file_path: absolute(input.path, directory),
          old_string: input.oldString,
          new_string: input.newString,
          replace_all: input.replaceAll === true,
        },
      }
    case "write":
      return {
        name: "Write",
        paths: [absolute(input.path, directory)],
        input: { file_path: absolute(input.path, directory), content: input.content },
      }
    case "shell": {
      const workdir = input.workdir ? absolute(input.workdir, directory) : undefined
      const command =
        workdir && workdir !== directory ? `cd ${shellQuote(workdir)} && ${input.command}` : input.command
      return {
        name: "Bash",
        command: String(input.command ?? ""),
        input: {
          command,
          description: input.description,
          timeout: input.timeout,
          run_in_background: input.background === true,
        },
      }
    }
    case "read":
      return {
        name: "Read",
        input: { file_path: absolute(input.path, directory), offset: input.offset, limit: input.limit },
      }
    case "glob":
      return { name: "Glob", input: { pattern: input.pattern, path: absolute(input.path, directory) } }
    case "grep":
      return {
        name: "Grep",
        input: { pattern: input.pattern, path: absolute(input.path, directory), glob: input.include },
      }
    case "webfetch":
      return { name: "WebFetch", input: { url: input.url } }
    case "websearch":
      return { name: "WebSearch", input: { query: input.query } }
    case "subagent":
      return {
        name: "Agent",
        input: { subagent_type: input.agent, description: input.description, prompt: input.prompt },
      }
    case "skill":
      return { name: "Skill", input: { skill: input.id ?? input.name } }
    case "todowrite":
      return { name: "TodoWrite", input }
    default:
      return { name: tool, input }
  }
}

function resultText(result) {
  if (typeof result.content === "string") return result.content
  if (Array.isArray(result.content))
    return result.content
      .filter((item) => item && item.type === "text")
      .map((item) => item.text)
      .join("\n")
  if (result.output !== undefined) return JSON.stringify(result.output)
  return ""
}

// OpenCode's system prompt tells the model that <system-update> blocks come from the harness.
function harnessNote(label, text) {
  return `<system-update>\n${label}\n${text}\n</system-update>`
}

function addToResult(result, note) {
  if (Array.isArray(result.content)) result.content = [...result.content, { type: "text", text: note }]
  else result.content = `${resultText(result)}\n\n${note}`
}

// ---- the plugin ---------------------------------------------------------------------------

export default {
  id: "claude-hooks",
  async setup(ctx) {
    const sessions = new Map()
    const verdicts = new Map()
    const earlyNotes = new Map()
    const stopBlocks = new Map()

    // Hooks key their once-per-session state on the session id, and Claude Code gives a
    // subagent its parent's id. A child session here reports its root session the same way.
    async function sessionOf(sessionID) {
      const hit = sessions.get(sessionID)
      if (hit) return hit
      let root = sessionID
      let child = false
      let directory = ctx.location.directory
      try {
        let info = await ctx.session.get({ sessionID })
        directory = info?.location?.directory || info?.directory || directory
        for (let depth = 0; info?.parentID && depth < 8; depth++) {
          child = true
          root = info.parentID
          info = await ctx.session.get({ sessionID: root })
        }
      } catch {}
      const session = { root, child, directory, project: ctx.location.project?.directory || directory }
      sessions.set(sessionID, session)
      return session
    }

    function squash(text) {
      return String(text).replace(/\s+/g, " ").trim()
    }

    // A refusal reaches the model through the permission check the tool makes. The check
    // names its tool call, except inside a Code Mode script, where it names the script's
    // call. Those are matched by session and by the path or command being checked.
    function verdictFor(event) {
      const now = Date.now()
      for (const [id, verdict] of verdicts) if (now - verdict.at > VERDICT_TTL_MS) verdicts.delete(id)
      const direct = event.source?.id ? verdicts.get(event.source.id) : undefined
      if (direct) return direct
      for (const verdict of verdicts.values()) {
        if (verdict.sessionID !== event.sessionID) continue
        const resources = event.resources || []
        if (event.action === "edit" && verdict.paths?.length) {
          if (resources.some((resource) => verdict.paths.includes(absolute(resource, verdict.directory)))) return verdict
        }
        if (event.action === "shell" && verdict.command && resources.length > 0) {
          const command = squash(verdict.command)
          if (resources.every((resource) => command.includes(squash(resource)))) return verdict
        }
      }
      return undefined
    }

    await ctx.tool.hook("execute.before", async (event) => {
      const session = await sessionOf(event.sessionID)
      const tool = asClaudeTool(event.tool, event.input, session.directory)
      const outcomes = await fire(
        "PreToolUse",
        tool.name,
        { tool_name: tool.name, tool_input: tool.input, tool_use_id: event.id },
        session,
      )
      const deny = outcomes.find((outcome) => outcome.deny !== undefined)
      const ask = outcomes.find((outcome) => outcome.ask !== undefined)
      if (deny || ask)
        verdicts.set(event.id, {
          at: Date.now(),
          sessionID: event.sessionID,
          directory: session.directory,
          paths: tool.paths,
          command: tool.command,
          deny: deny?.deny,
          ask: ask?.ask,
        })
      const notes = outcomes.map((outcome) => outcome.context).filter(Boolean)
      if (notes.length > 0) earlyNotes.set(event.id, notes)
    })

    await ctx.permission.hook("evaluate", (event) => {
      const verdict = verdictFor(event)
      if (!verdict) return
      if (verdict.deny !== undefined) {
        event.effect = "deny"
        event.message = verdict.deny
      } else if (event.effect === "allow") {
        event.effect = "ask"
        event.message = verdict.ask
      }
    })

    await ctx.tool.hook("execute.after", async (event) => {
      const refused = verdicts.get(event.id)
      verdicts.delete(event.id)
      const notes = earlyNotes.get(event.id) || []
      earlyNotes.delete(event.id)
      if (event.status !== "completed") return
      const session = await sessionOf(event.sessionID)
      const tool = asClaudeTool(event.tool, event.input, session.directory)
      if (refused?.deny !== undefined)
        log({ event: "PreToolUse", tool: tool.name, session: session.root, problem: "tool ran despite a deny" })
      const outcomes = await fire(
        "PostToolUse",
        tool.name,
        {
          tool_name: tool.name,
          tool_input: tool.input,
          tool_response: { content: resultText(event.result) },
          tool_use_id: event.id,
        },
        session,
      )
      for (const outcome of outcomes) {
        if (outcome.block) notes.push(outcome.block)
        if (outcome.context) notes.push(outcome.context)
      }
      if (notes.length > 0) addToResult(event.result, harnessNote(`${tool.name} hook:`, notes.join("\n\n")))
    })

    await ctx.session.hook("prompt", async (event) => {
      sessions.delete(event.sessionID)
      const session = await sessionOf(event.sessionID)
      if (session.child) return
      const outcomes = await fire("UserPromptSubmit", undefined, { prompt: event.prompt.text ?? "" }, session)
      const block = outcomes.find((outcome) => outcome.block)
      if (block) throw new Error(block.block)
      const notes = outcomes.map((outcome) => outcome.context).filter(Boolean)
      if (notes.length > 0)
        await ctx.session.synthetic({
          sessionID: event.sessionID,
          text: harnessNote("UserPromptSubmit hook:", notes.join("\n\n")),
        })
    })

    // Claude Code's Stop hooks read the turn's last message from the transcript file, so the
    // text is written there in Claude Code's record shape before they run.
    async function recordLastText(sessionID, root) {
      let text = ""
      try {
        const messages = await ctx.session.context({ sessionID })
        for (let index = messages.length - 1; index >= 0 && !text; index--) {
          const message = messages[index]
          if ((message.role ?? message.type) !== "assistant") continue
          const parts = message.parts ?? message.content ?? []
          text = (Array.isArray(parts) ? parts : [])
            .filter((part) => part && part.type === "text" && typeof part.text === "string")
            .map((part) => part.text)
            .join("\n")
            .trim()
        }
      } catch {}
      if (!text) return
      const record = {
        type: "assistant",
        timestamp: new Date().toISOString(),
        message: { role: "assistant", content: [{ type: "text", text }] },
      }
      fs.mkdirSync(TRANSCRIPTS, { recursive: true })
      fs.appendFileSync(path.join(TRANSCRIPTS, `${root}.jsonl`), JSON.stringify(record) + "\n")
    }

    await ctx.session.hook("experimental.idle", async (event) => {
      const session = await sessionOf(event.sessionID)
      if (session.child) return
      const blocks = stopBlocks.get(event.sessionID) || 0
      await recordLastText(event.sessionID, session.root)
      const outcomes = await fire("Stop", undefined, { stop_hook_active: blocks > 0 }, session)
      const block = outcomes.find((outcome) => outcome.block)
      if (!block || blocks >= MAX_STOP_BLOCKS) {
        stopBlocks.delete(event.sessionID)
        return
      }
      stopBlocks.set(event.sessionID, blocks + 1)
      await ctx.session.synthetic({
        sessionID: event.sessionID,
        text: harnessNote("Stop hook:", block.block),
      })
    })
  },
}
