---
description: Relay your most recent finding (or a specified message) to another of my live Claude Code sessions, human-confirmed.
argument-hint: <peer title or hint> [— what to relay]
disable-model-invocation: true
allowed-tools: mcp__ccd_session_mgmt__list_sessions, mcp__ccd_session_mgmt__search_session_transcripts, mcp__ccd_session_mgmt__send_message
---

You are relaying a message from THIS session to another of the user's live Claude Code sessions. The user is the switchboard: you propose the relay, the harness asks them to confirm the actual send, and they decide what crosses.

The user's relay request: **$ARGUMENTS**

Do this, and only this:

1. Call `mcp__ccd_session_mgmt__list_sessions` to get the user's other sessions (id + title). Match the target named in the request. If it's ambiguous or absent, use `mcp__ccd_session_mgmt__search_session_transcripts` to disambiguate, or ask the user which session they mean — never guess a target.

2. Decide the payload:
   - If the request names content to relay (text after a "—", a colon, or "say/relay/ask"), relay exactly that.
   - Otherwise relay YOUR most recent substantive finding from this conversation — verbatim and self-contained, no preamble, no "as we discussed." Assume the receiving session has **none** of our context; include the minimum it needs to act on it.
   - Keep it to one finding or question. This is a curated excerpt, not a transcript dump.

3. Call `mcp__ccd_session_mgmt__send_message` with `session_id` = the resolved target and `message` = the payload. The harness shows the user a confirmation dialog with the exact text — that dialog is their gate; they may decline or ask you to trim before it crosses.

4. After it sends, tell the user in one line: it lands as a "From {this session}" user turn in the peer, but the peer only acts on it the next time that session runs — so they may need to switch to it and nudge it. To pull the reply back, run `/relay` from the peer pointed at this session.

Relay to at most one session per invocation.
