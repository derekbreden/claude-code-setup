---

# User

---

I have another agent working on a video just now, and you can see their in progress work at:

~/Developer/soda-edit/2026-06-19-desolder

And I am getting the feeling that they are not taking the instructions seriously, or that something has gone seriously wrong with our instructions.

I feel like we had a lot more features on our last video, as far as like "nice graphical overlay display things" and I am seeing this agent just slap on ugly text ... and I thought the video instructions were really clear about "we've got all this conventions to follow and this nice features we are adding to our videos" and it seems like this agent just either skipped all of that, or we failed to document any of it as much as I thought we had.

And ... and .... I thought we had instructions about expanding that feature set on every video too.

So, I'm just incredibly disappointed - what do you see?

---

# Assistant

---

I'll investigate this carefully. Let me scout both the documented video conventions in the main repo and what the in-progress agent is actually doing.

---

# Assistant

---

Let me dig into both the documented video conventions and the prior videos for comparison.

---

# Assistant

---

This is a forensic question — is the in-progress video actually ignoring documented conventions, and do those conventions/feature-expansion rules even exist as the user remembers? I have the file layout now. Let me read the core instruction docs and the current work directly to ground myself, then fan out for a thorough comparison.

---

# Assistant

---

The user's memory is accurate — this is documented clearly. Let me confirm: `principles.md` line 27–29 ("The pipeline is the floor") explicitly says *"Each video moves the format forward by some unambiguous amount over the last one — a cold open, a motion-graphics primitive, a sound treatment, a typographic move, a B-roll insert... pick something and build it."* And workflow.md step 12 documents a rich motion-graphics overlay system. Now let me see exactly what the in-progress agent has actually produced.

---

# Assistant

---

The picture is sharpening, and it's important I be fair rather than just confirm a frustration. The brief itself (`ive-never-desoldered.md`) is detailed and explicitly plans the format advance ("cold-open-on-payoff + freeze-into-title... the format advance over the last video"). But the actual `cutlist.json` being rendered has no `freeze` cut, and I see no `overlays.json` sidecar in the directory at all. Let me verify the hard evidence — what's actually in the rendered draft and what's missing — before I draw conclusions.

---

# Assistant

---

No `overlays.json` exists anywhere, and `cutlist.json` has no `freeze` entry — yet the skeleton plan and the README's own render command both call for them. Let me look at the actual rendered frames the agent extracted from draft 3 to see with my own eyes what the user is seeing on screen.

---

# Assistant

---

Visually confirmed. The cold open (frame at 0.6s) is the *same* "look how clean" reveal shot as the closing frame (112s) — the exact "repeated footage" trap the brief warned against — with no title card, no freeze, no motion graphics. Just burned-in white captions. That is the "ugly text" you're seeing. Let me nail down the precise documented feature menu and what the last video actually shipped, so I can tell you exactly how big the gap is.

---

# Assistant

---

I've now got the full picture, verified against the actual rendered frames, the documented spec, and what the last video shipped. Your instinct is right on the substance — and wrong on the self-blame. You documented this *thoroughly*. The agent didn't follow it.

## What you're actually seeing

The draft (`out-draft3.mp4`) has **only burned-in captions and cut.py's built-in `section`/`tool` text labels** on screen. That's the "ugly text." None of the motion-graphics layer is present:

- **No `overlays.json` sidecar exists at all** — anywhere in the working dir. cut.py renders fine without it, so the entire motion-graphics pass was silently skipped.
- **No title card.** The "I've Never Desoldered Anything" hero `title` overlay is gone.
- **No freeze.** `cutlist.json` has zero `"type": "freeze"` entries.
- **No SFX.** No `sounds` array, no vacuum-"pop" foley.
- **The cold open is the ending, replayed.** Cut #1 is `177.92–183.5`; the final cut is `169.0–183.5` — the cold open is a literal sub-clip of the closing shot, ending on the exact same frame. The frames confirm it: `verify/d3_0.6.jpg` (open, "but look at how clean!") and `verify/d3_112.jpg` (close, "That is amazing.") are the same hand-holding-the-board composition. The brief explicitly warned against exactly this: *"frame it differently... so the bookend reads intentional, not like repeated footage."*

## You did document it — comprehensively

This is the part worth hearing clearly: **this is not a documentation gap.** The agent was handed everything.

- [principles.md](marketing/video/principles.md) line 27, **"The pipeline is the floor"**, is your "expand every video" rule, verbatim: *"Each video moves the format forward by some unambiguous amount over the last one — a cold open, a motion-graphics primitive, a sound treatment, a typographic move, a B-roll insert... pick something and build it."*
- [workflow.md](marketing/video/workflow.md) step 12 documents the whole overlay system and how to invoke it (`--overlays`).
- [overlays.py](marketing/video/overlays.py) implements **10 overlay types**: `title`, `param`, `text`, `hud`, `lower_third`, `stamp`, `box`, `arrow`, `pip`, `magnifier` — plus the `sounds` SFX bed (sting, stamp-thud, whoosh, ding, click).
- The brief, [ive-never-desoldered.md](marketing/video/ive-never-desoldered.md), *specifically planned the advance*: "the channel's first **cold-open-on-the-payoff + freeze-into-title** seam — the format advance over the last video, per [principles.md#the-pipeline-is-the-floor]." It also specced the `tool` overlay and the vacuum-pop SFX.
- Even the agent's **own** `cutlist-skeleton.json` contained the `{"type": "freeze", ...}` entry with "the 'I've Never Desoldered Anything' title card lands on this," and its own `README.md` step 7 says to render with `--overlays overlays.json`.

The agent had the rule, the menu, a detailed plan, a skeleton with the freeze already in it, and its own README telling it to use overlays — and shipped none of it.

## It didn't just fail to advance — it regressed

Per workflow.md, the **last** video (*Don't Let Go*) shipped: a cold open, a freeze title-hold under a hero `title` overlay, a `sting` under the title transition, and **five `stamp-thud` cues**. So the floor this video had to *clear* already included title + freeze + SFX. The desolder draft ships **fewer** motion-graphics features than the video before it. "The pipeline is the floor" was violated in the wrong direction.

## The one real process gap (not your fault either)

The only systemic issue: **cut.py renders a complete-looking video with no error when `--overlays` is omitted.** The "floor" is a principle, not an enforced gate — so an agent can drop the entire graphics layer and produce something that *looks* finished. The trajectory here backs that up: the recent files are thumbnail candidates (`thumb-cand/`, 02:02) and verify frames (01:58), i.e. it was heading toward *publish*, not back to add overlays. And the freeze wasn't left un-timed — it was **deleted** from the cutlist, which reads as a decision, not a to-do.

---

So: you're not crazy, you didn't under-document, and the feature set is real and rich. One agent skipped it.

Want me to fix it? The concrete remediation is small and well-specified by your own brief: restore the `freeze` cut on the cleared-board frame, author an `overlays.json` (hero `title` card on the freeze, the `Hakko FR-301D` `tool` callout, a vacuum-pop SFX cue), re-pick a cold-open clip that isn't the closing shot, and re-render with `--overlays`. I can do that pass now, or just write up corrective notes for the other agent to execute — your call.
