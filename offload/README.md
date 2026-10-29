# offload

`transcript_offload.py` keeps the transcripts of archived Claude Code and Codex
sessions in iCloud Drive instead of on this Mac's disk. A Claude Code session
moves once the desktop app no longer shows it in the sidebar, because it is
archived or the app has no record of it, and none of its files has been written
for a day. Its transcripts and spilled tool results of 64 KB or more go to
`iCloud Drive/Agent transcripts/claude/projects/<project>/` under their
original relative paths, and a symlink takes each one's place. The app's
Settings → Claude Code → Archive inactive sessions decides when an idle session
leaves the sidebar.

A Codex rollout of 64 KB or more in `~/.codex/archived_sessions` moves to
`iCloud Drive/Agent transcripts/codex/archived_sessions/` once it has gone a day
without a write, with a symlink in its place. A rollout the Codex app has
unarchived into `~/.codex/sessions` gets its file back on the next run.

Any iCloud copy under `Agent transcripts` is evicted from the disk once iCloud
reports it uploaded and it has gone a day without a write.

The Claude desktop app reads a transcript only from a regular file inside real
directories, so it shows an offloaded session's transcript as unavailable.
Unarchiving the session brings its files back on the next run. The Claude Code
CLI reads and appends through the symlinks, and iCloud downloads an evicted
copy on first read.

ripgrep skips symlinks unless given `-L`. Every file a search reads is
downloaded again and evicted a day later.

## Use

```sh
# Dry run: what would move, come back, and be evicted
python3 offload/transcript_offload.py

# Move, restore and evict
python3 offload/transcript_offload.py --apply
```

`--hours` sets the idle time; the default is 24.

## Scheduled offload

`install.sh` renders `launchd/com.derekbredensteiner.transcript-offload.plist.in`
into `~/Library/LaunchAgents/` and loads it. The agent runs the script with
`--apply` every 3600 seconds and logs to `~/.config/transcript-offload/offload.log`.

Eviction asks the iCloud daemon about one file at a time. During a large upload
a run can take many minutes; a run that finds the previous one still going
exits.

A run brings sidebar sessions back first and evicts last. To bring an
unarchived session back now instead of on the next hourly run, restart the job.
`-k` stops a run that is still going:

```sh
launchctl kickstart -k gui/$(id -u)/com.derekbredensteiner.transcript-offload
```
