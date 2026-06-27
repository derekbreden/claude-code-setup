---
description: Relay a finding to another of my live Claude Code sessions — and bootstrap that session into our shared tooling so it can read my full clean transcript. Human-confirmed.
argument-hint: <peer title or hint> [— what to relay]
disable-model-invocation: true
allowed-tools: mcp__ccd_session_mgmt__list_sessions, mcp__ccd_session_mgmt__search_session_transcripts, mcp__ccd_session_mgmt__send_message
---

You are relaying a message from THIS session to another of the user's live Claude Code sessions. The user is the switchboard: you propose the relay, the harness asks them to confirm the actual send, and they decide what crosses. The receiving session has NONE of our context and does not know our tooling exists — so the relay must BOTH carry a finding AND tell the peer how to pull my full context for itself.

The user's relay request: **$ARGUMENTS**

Do this, and only this:

1. **Resolve the target.** Call `mcp__ccd_session_mgmt__list_sessions` to get the user's other sessions (id + title). Match the target named in the request. If it's ambiguous or absent, use `mcp__ccd_session_mgmt__search_session_transcripts` to disambiguate, or ask which session they mean — never guess a target.

2. **Compose the payload — two parts:**

   **(a) The finding.** If the request names content (text after a "—", a colon, or "say/relay/ask"), relay exactly that. Otherwise relay your most recent substantive finding from this conversation — verbatim, self-contained, no "as we discussed." One finding or question, not a transcript dump.

   **(b) The bootstrap (ALWAYS append).** The peer doesn't know our tooling exists, so hand it the keys. Append the block below, with `MY-TITLE` replaced by THIS session's title — the same name the peer will see in the "From …" label this message arrives under (if you don't know your own title, write the literal instruction "use the title in my From-label"):

      ---
      This came from another of your user's live Claude Code sessions ("MY-TITLE"). For the full reasoning behind the note above — not just this excerpt — render my clean transcript with our shared exporter (already on this machine):

      `python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py export-session "MY-TITLE" --out /tmp`

      then read the `.md` it writes in /tmp. Once you've read it, `... delta "MY-TITLE"` prints only what's new since (add `--first-share` the very first time). If the title isn't found, run `python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py list-sessions` to see exact titles.

3. **Send.** Call `mcp__ccd_session_mgmt__send_message` with `session_id` = the resolved target and `message` = finding + bootstrap. The harness shows the user a confirm dialog with the exact text — that dialog is their gate; they may decline or ask you to trim.

4. After it sends, tell the user in one line: it lands as a "From {this session}" user turn in the peer; the peer only acts on it (and can run the exporter) the next time that session runs, so they may need to nudge it. To pull the reply back, run `/relay` from the peer pointed here.

Relay to at most one session per invocation.
