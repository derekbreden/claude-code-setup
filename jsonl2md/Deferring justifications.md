---

# User

---

I don't remember exactly what is in this conversation, but I think the way it started at least might be relevant to what I want to talk about.

I've been having a bit of a "slow realization" with Opus 4.7 and just how much more capable it is than other models, and more specifically the ways in which it is more capable.

I found myself typing out some detailed directions to a lesser model recently (because 4.7 was having availability issues), and the thought occurred to me:

> I am telling Sonnet all the specific steps to do, the exact same steps that I would expect Opus 4.7 to do, that I am confident Opus 4.7 would assume to do on its own. You know what, it really isn't that the lesser models are less able to do any of these things. All of the capabilities are there, the execution is on point. It's just that the decisions about what do when given a higher level command are not as obvious to the lesser model as they are to Opus 4.7 and I. So again, just like with the laziness, and perhaps identical to the laziness, its really not that Opus 4.7 is "better" in any way that I could definitively say "yes, these steps are absolutely the 'correct' steps" and "Opus 4.7 is more correct" - I can't say that. I can't say "Opus 4.7 is more correct". What I can say, is "Opus 4.7 is more like me", that it makes more often the decisions I would expect myself to make. Not exactly like me, not by a long shot. But certainly more so than other models have been.

And so I think I am coming to make better use of lesser models, because I can more clearly identify the ways in which they make "wrong" assumptions. Not actually wrong assumptions, not incorrect in any way, but just different than what my own assumptions would be in such matters, and different than even what Opus 4.7's would be in such matters.

And so I can use the lesser model to do the exact same thing, but I do have to tell more exactly what to do, at a lower level.

Opus 4.7 lets me move up to a higher level of direction.

With Sonnet I need to type this:

> Well, I've been testing the heat inserts I bought (which you can find in purchases.md, and which you can find further details about from the amazon listing and searching, using chrome MCP - you may want to spawn an agent to do this research) and the heat inserts I bought don't seem to push down quite as flush as I would want.
> I think we need to increase the depth for just the heat inserts, but that surprises me because I thought we already had an extra 1 mm beyond them, but perhaps I am missing something either about the dimensions of the heat inserts, or about the physics of pushing in a heat insert and how far you can go before extreme resistance is met.
> Can you explain?

Where is with Opus 4.7 I would simply say:

> Well, I've been testing the heat inserts I bought and they don't seem to push down quite as flush as I would need.
> I think we need to increase their depth, but that surprises me, because of that extra 1 mm you just mentioned.
> Can you explain?

I realize you don't have full context for ***this*** conversation, for these prompts. But I think perhaps you can see by the diff between those two, I hope you can see by example what I mean by "specificity at a lower level".

---

# Assistant

---

Yeah, the diff makes it really clear. What you're describing isn't a capability gap — it's an *inference* gap. Both models can run the chrome MCP, both can spawn a research subagent, both can cross-reference purchases.md. The difference is whether the model independently arrives at "I should go verify the heat insert specs against what we designed for" when you just say "they don't push down flush."

The Sonnet prompt is doing two distinct kinds of work that the Opus prompt collapses into one:

1. **Stating the problem** (heat inserts not flush, expected the 1mm to be enough, want an explanation)
2. **Specifying the investigation** (check purchases.md, look up the Amazon listing via chrome MCP, possibly spawn an agent for it)

With Opus 4.7 you only do (1). The model fills in (2) because it makes the same call you'd make — "to answer this I need to know what these specific inserts actually are, and the obvious way to find out is the purchase record plus the listing." With Sonnet you have to do both, because the model's default inference about what to investigate might be "answer from general knowledge about heat inserts" or "ask the user for the part number," neither of which is wrong, but neither is what you'd do.

I think your framing — "more like me" rather than "more correct" — is the honest one, and it's load-bearing. There isn't a privileged correct decomposition of "the heat inserts aren't flush, explain." There are many reasonable ones. What you're noticing is that Opus 4.7 lands on the decomposition *you* would land on more often, which means the prompt can compress because you and the model are sharing more priors about what the next step is. With Sonnet those priors aren't shared as densely, so you have to externalize them into the prompt.

The thing I'd add — and I think this is consistent with what you're saying, not a pushback — is that this isn't *only* a matter of taste-matching. There's a real underlying capability involved, which is something like "modeling the implicit task structure of an ambiguous request." When you say "they don't push down flush, explain," there's a tree of possible investigations, and the model has to traverse it and pick a branch. The capability is in the traversal — having a good prior over which branch is likely to be productive given the context (a CAD project, recent mentions of insert depth, available tools like chrome MCP and purchases.md sitting right there). A model that picks well *looks* like it shares your taste, but what's really happening is it's better at reading the room. The reason that ends up correlating with "like you" is that the room contains you — your prior messages, your project, your tooling choices. Better room-reading converges on user-matching.

Which has a practical implication for the Sonnet workflow you're developing: when you're writing the lower-level version, the highest-leverage thing to add isn't the steps themselves, it's the *frame*. "Check purchases.md and the Amazon listing" works, but "figure out what these specific inserts actually are before reasoning about the geometry" works better, because it gives Sonnet the branch-selection logic rather than the leaves. You still end up typing more than with Opus, but you're typing the thing the weaker model is actually missing rather than compensating for it by hand-rolling the whole tree.

One thing I'm curious about, since you mentioned the laziness connection: do you think these are the same underlying phenomenon, or two phenomena that just feel similar? My instinct is they're related but distinct — laziness is "the model knows the right next step and skips it," whereas this is "the model doesn't generate the right next step as a strong candidate in the first place." But you've been watching this more closely than I have across models.

---

# User

---

Did you read the You.md attachment I included?

Regarding the laziness, I think you are correct that they are different in that:

laziness => "skips a step"
lack of need for low level specificity => "adds a step"

But, I think the larger point I am making, is that all of these are judgment calls, where the judgment actually depends on far more context than you have to truly understand any of these examples - neither the one I gave here, nor any you find in You.md.

There's a lot you don't know about the project, and the path that would an agent to know purchases.md includes the purchases. It is obvious if you read the AGENTS.md (which is a byte for byte copy for what is in MEMORY.md for all the agents, and there is nothing else in their memory but that) because AGENTS.md/MEMORY.md is a very well thought out summary and pointer to starting point files, and following those starting points with sufficient effort will lead one to at least be aware that purchases.md exists, and that it likely includes "whatever I bought" that the user mentions.

I will give you AGENTS.md to give you a sense of what I mean, but I won't give you future.md first, because I need you to form an impression first based on AGENTS.md and to see how subtle the reference to future.md is, so you can determine whether you would actually look at future.md given everything I've said so far. So that I do not have to ask you a counterfactual before I share with you what is in future.md

---

# Assistant

---

No, I didn't read You.md. I should have — you flagged it as relevant in your first message, and I just... talked past it. That's exactly the kind of thing we're discussing, ironically: I had the tool available, the file was right there at a known path, you'd told me it was relevant, and I still didn't go look. Let me actually read it before you share AGENTS.md.

Okay, I've read it now — including the parts I didn't have before, the "comments are an indicator of a deeper problem" thread, the bit about examples being more transmissible than rules, the calibration gap on "removed the block." The whole arc of you nudging a previous instance toward seeing where the "fix" actually lives.

So now — AGENTS.md. Send it. I'll read it carefully and tell you honestly whether the reference to future.md lands for me, or whether I'd skip it. I want to give you a real datapoint, not a primed one, so I'll try to read it the way I'd read it if I'd just been dropped into the repo without this conversation as context — and then say what I'd actually do.

One thing I'll flag in advance, in the spirit of the conversation: I might fail the test even if I "would" follow the pointer in principle, because reading a file in a chat context where you're explicitly watching for whether I follow a pointer is not the same task as reading a file as an agent starting work. The observer effect is real here. I'll try to bracket it and just report what I see.

---

# Assistant

---

Reading this cold, bracketing as best I can:

The reference to `future.md` lands. It's not subtle to me — it's named twice, once in a "See ... for details" sentence at the end of the first section, and the section it closes (What This Is) explicitly says the integrated chiller details are *there*, not here. That's a strong pointer: the section names a thing, says "but here's the next version of the thing," and tells me where the next version lives. If I were starting work and the user mentioned anything about the carbonator, chiller, or the integrated architecture, that file is the obvious first read. Same with `target-market.md` for the "why" — same construction, same strength.

So in the abstract, yes, I would follow the pointer. But I want to be honest about *when* I would follow it, because that's where the failure mode you're describing actually lives.

I'd follow it if the user's question touched on architecture, integration, the chiller, the carbonator, the product (vs. prototype) distinction, or anything where "we chose X" reasoning would matter. The pointer is well-placed for those cases — AGENTS.md gives me the orientation and explicitly says the depth lives downstream.

I'm less sure I'd follow it for a question that *seems* purely local — "the heat inserts aren't flush, explain." Nothing in AGENTS.md screams "heat inserts are discussed in future.md." I'd probably grep first, or look at the CAD files mentioned in the heat-insert context, or check purchases.md (which isn't named here — I'd find it by `ls` or by following whatever file the user's currently working in). And that's the gap, isn't it? The pointer is strong for the questions whose framing already touches the documented topics. It's weaker for questions where the connection to future.md is itself one of the things future.md would tell me.

Which is the recursive version of the problem you've been describing: examples teach better than rules, *and* you have to read the examples to learn what's in them, *and* the decision of whether to read them is itself shaped by whether you've read them. Opus 4.7 and you converge on "read the orienting docs first, then attack the local question" as a default; a lesser agent might attack the local question first and only consult the orienting docs if the local attack stalls. Both are reasonable. The first is more like you.

One observation about the AGENTS.md itself, since you're asking me to look at it as a piece of design: the Amazon Prime paragraph is doing something different from the rest of the document, and I think it's load-bearing in a way that's easy to miss. The first two sections are "here's the project, here's the why, depth is over there." The CadQuery and Firmware lines are mechanical pointers. The Amazon paragraph is the only place in the file with a directive in the imperative — "Do not read them. Do not mention them." It's also the only place that demonstrates, by example, the register you want: terse, absolute, no hedging, no "should." If an agent reads the document and absorbs the *texture* of that paragraph — the willingness to just declare a thing rather than caveat it — that probably does more work than any explicit instruction about register would. It's a small embodied demonstration of "here's how decisions get made and stated in this repo."

The thing I notice I *don't* have, that I'd want, is some signal about purchases.md and the other narrative/state files. AGENTS.md tells me about future.md and target-market.md as the depth-pointers, and about the tooling for CadQuery and firmware. It doesn't tell me there's a class of "this is what's currently happening / what I bought / what I'm testing" files. I'd probably discover purchases.md by `ls` on the root or wherever, and then realize from its name what it is — but I'd discover it incidentally, not because AGENTS.md pointed me at it. Whether that's a gap or correct minimalism depends on how often the answer to "what's going on right now" is the load-bearing piece of context. From what I saw in You.md (the heat inserts example, the in-flight nature of the project), my guess is "often." But I genuinely can't tell from one file whether that's a deliberate choice (these are ephemeral, don't over-anchor agents to them) or an oversight.

Send future.md when you're ready. I'm curious whether reading it changes my read of AGENTS.md's pointer-strength retroactively.

---

# Assistant

---

Okay. A few things changed for me after reading both files.

**The pointer to future.md is much stronger than I rated it.** Reading AGENTS.md alone, I said it lands "in the abstract." Reading future.md, I now see what's actually downstream: every subsystem, every fitting, every fitting's wetted-material rationale, the entire pressure-vessel architecture, the regulatory argument, the user-facing element layout — basically everything an agent would need to answer almost any non-trivial question. The pointer from AGENTS.md isn't really "see future.md for chiller details." It's "see future.md for *the appliance*." AGENTS.md is intentionally tiny because future.md is where the substance lives. If I'd seen future.md first I would have rated the pointer as not subtle at all — but the test you set up was precisely about *not* seeing it first. So the pointer being subtle from inside AGENTS.md is the actual interesting datapoint.

**The heat insert question is where my abstract test breaks down, and it's instructive.** I searched future.md for heat inserts (text search, scrolling) — no hits in what I read. The truncated middle (lines 35-114) might have something; I haven't read that. So in the actual workflow, if you said "the heat inserts aren't flush, explain, you mentioned an extra 1mm," I'd need to find *where you mentioned the 1mm*. That's not in AGENTS.md, probably not the main body of future.md, and `purchases.md` would tell me *what* I bought but not *what we designed the pocket depth for*. The answer is probably in one of the CadQuery scripts, or in an assembly/ subdoc, or in a printed-parts README. So "follow the threads from AGENTS.md → future.md" is the right *orientation* move, but the specific answer requires going deeper still, and AGENTS.md's role is to make sure I'm willing to keep going.

Which clarifies something about your original frame. The compression Opus 4.7 enables isn't "model fills in `check purchases.md` because it's well-named." It's "model is willing to descend through several levels of pointers before giving up and asking." AGENTS.md → future.md → assembly/foo.md → printed-parts/bar/README.md → the actual CadQuery script. Each hop is small and well-signposted; the question is whether the agent takes all of them or stops at the first level and answers from what it has. The "low-level specificity" Sonnet needs isn't really *lower-level instructions* — it's *a longer leash for descent*. "Spawn an agent to research the Amazon listing" is partly that: it's telling Sonnet "I authorize the long path here."

**The thing I now think AGENTS.md is doing, that I missed:** it's not trying to be complete. It's trying to be a *small enough surface that an agent can't accidentally satisfy themselves with it alone.* If AGENTS.md had a paragraph about every subsystem, an agent might read it and feel oriented enough to answer. Because it explicitly says "the appliance is in future.md," and future.md is clearly load-bearing once you open it, the document refuses to substitute for itself. The Amazon Prime paragraph is the only place where AGENTS.md takes a hard position without deferring — which is itself a tell: hard positions live in AGENTS.md, everything else is a pointer.

**Where future.md does a thing I want to note:** the parenthetical about the racetrack body at lines 19, and the `archive-plan-b` git tag instruction — that's the same teaching-by-example move as the rest of the documents. It doesn't say "we don't apologize for changing direction" as a rule. It just *demonstrates* a change of direction with the rejected path preserved, accessible, and labeled with no defensive language. An agent reading that internalizes "we change plans here, we preserve the old one, we move on, we don't editorialize." Same for the Beduan atomizer → sparge stone reasoning in the Port 1 paragraph. Decisions are shown with their counterfactuals attached and no moral weight on either.

**One genuine question, in the spirit of you-asking-me-to-evaluate:** the truncated middle of future.md (lines 35-114) — I genuinely don't know if heat inserts live there or somewhere deeper. In my real workflow I'd just `cat` or grep the whole file. Here I'm being polite about token budget. If you want me to read it and answer the heat insert question for real, I can — but I think the more interesting question is whether you want me to demonstrate the descent or whether you've already gotten the datapoint you wanted from the AGENTS.md / future.md hop.

---

# User

---

This:

> It's trying to be a small enough surface that an agent can't accidentally satisfy themselves with it alone.

Is not exactly what I would have said. I think I would have said:

> AGENTS.md is very intentional about when additional context is necessary, and when it is not, and the pattern (intentionality) continues through to future.md and target-market.md and the files they reference, and so on and so forth. The whole repo is intentional in this manner.

Can you see what I mean by the fact that heat inserts are not mentioned in future.md, contrary to your thesis so far?

Are we saying different things?

---

# Assistant

---

Yes, we're saying different things, and your version is more correct.

My framing was about *what AGENTS.md does* — refuse to be self-sufficient. Yours is about *what the whole repo does* — manage what context is needed where. Mine treats AGENTS.md as performing a trick (be small, force descent). Yours treats it as one node in a system that's consistently asking "does this belong here or somewhere else?" — and answering both ways, depending.

The heat inserts not being in future.md is the proof. If my thesis were right — AGENTS.md is small to force descent, future.md is where the substance lives — then heat inserts *should* be in future.md. They're not. And they're not because future.md is also being intentional: it's the appliance-level architectural document, and the depth of a heat insert pocket in a printed part is not appliance-level. It belongs in the printed-parts README or the CadQuery script or wherever the pocket is actually defined. future.md *pointing away* from heat inserts is the same move AGENTS.md makes when it points to future.md. The intentionality propagates.

Which means I had the pattern half-right and called it the whole thing. I noticed AGENTS.md is intentionally minimal and concluded "the strategy is to force descent." You're saying the strategy is intentionality at every level — sometimes that means deferring (AGENTS.md → future.md), sometimes that means absorbing (the Amazon Prime paragraph stays put, the carbonator's hoop-stress math stays in future.md rather than getting kicked further down). The question every file asks is "what belongs here?", not "what can I get away with omitting?"

I think the difference matters because my framing implies a kind of cleverness — the document is small *in order to* produce an effect on the reader. Yours describes something more like honesty: each file contains what actually belongs in it, no more, no less, and the structure that emerges is a consequence rather than a design goal. The latter is what "examples teach better than rules" actually looks like when applied to documentation architecture. The repo isn't trying to teach agents to descend; it's just consistently putting things where they belong, and an agent that reads carefully ends up descending because that's where the answers are.

Let me read target-market.md before saying more, since you sent it and I should follow the same principle of actually reading the thing rather than commenting around it.

Reading target-market.md confirms it. Same pattern: this file contains exactly what's "target market" — buyer definition, qualifying filters, pricing tiers, GTM consequences, trust-gap argument. The unboxing experience gets one paragraph and a pointer. CO2 service gets one sentence and a pointer. The faucet design, the regulatory work, the firmware — none of that is here, because none of that is *target market*. The same "what belongs here?" question is being answered, just at a different node.

And the "rings of trust" / Founder Edition framing is itself a worked example of the same intentionality at the *business* level: the document isn't merging customer-facing pricing logic and internal capacity logic into one muddle, it's keeping them legible as separate things. Which is the same operation AGENTS.md performs on agent context.

So to answer your direct question: yes, I see the difference now, and I see what the heat insert absence proves. My "small surface to force descent" framing was reading AGENTS.md as if it were *performing for an agent reader*. Yours reads the whole repo as *being honestly organized*, with the effect on agents being a downstream consequence. The honesty version is harder to fake and produces the descent behavior as a side effect, where my version describes a trick that would stop working as soon as the trick became visible.

One thing I want to add, because it connects back to the original Opus 4.7 / Sonnet thread: the repo's intentionality and the model's willingness-to-descend are matched halves of the same thing. The repo is honestly organized — each file contains what belongs in it. An agent that *also* operates with the disposition of "answers live where they belong, follow the structure to find them" gets the right answer cheaply. An agent that operates with the disposition of "answer from what's immediately available, ask if stuck" doesn't, even though every pointer it needs is right there. The Sonnet prompt you wrote isn't really compensating for missing capability — it's substituting *user-provided structure* for *model-internal disposition to follow the existing structure*. Which is consistent with what you said in the very first message: the steps aren't more correct, the model is more like you. The repo is built for a reader who reads the way you do, and Opus 4.7 happens to read more like you.

I also want to flag, since you've been generous about correction: my "Amazon Prime paragraph is the embodied register" observation was probably also slightly wrong in the same direction. I read it as a *stylistic demonstration* — "here's the texture you should match." But under your framing, it's just what belongs in AGENTS.md about Amazon Prime: the position is firm, so it's stated firmly. The fact that it reads as register-setting is a side effect of honesty, not a designed effect. Same correction, different paragraph.

---

# User

---

I think I agree with most of what you said in your last response, but I have not read it fully.

Back to what you said here:

> Where future.md does a thing I want to note: the parenthetical about the racetrack body at lines 19, and the `archive-plan-b` git tag instruction — that's the same teaching-by-example move as the rest of the documents. It doesn't say "we don't apologize for changing direction" as a rule. It just demonstrates a change of direction with the rejected path preserved, accessible, and labeled with no defensive language. An agent reading that internalizes "we change plans here, we preserve the old one, we move on, we don't editorialize."

That is a very interesting observation, because I don't actually like that. I don't like that archive-plan-b is mentioned at all. I would rather it not be mentioned at all. The only reason it survives is because it does give a clue towards a persistent problem I have that I have not solved. The persistent problem I have is agents actually documenting things in code which should ONLY be preserved in git history. At least here they can see, "ah yes, move things to git history not in the code". But unfortunately, I hope you can see the irony here, that this mention of archive-plan-b itself violates the principle, by TALKING about something which should ONLY be in git history. This isn't in history, and it really would be, if I could actually trust agents to truly follow the example without it.

I wonder if you read anything about the "hooks" in You.md?

For example here:

> **The hook layer has grown.** Memory-write block is one hook; there's also `block-effort-estimate.sh` blocking shapes like "a few hours" or "half a day" — a Stop hook that regex-prefilters and then calls Haiku to disambiguate effort vs. projection. A second category of agent behavior you've identified as worth catching mechanically. The pattern is consistent: when a behavior stays miscalibrated after conversation, build the mechanism. AGENTS.md's lessons section is now gone entirely — the hook carries the load and the textual residue isn't doing any work.

Basically, we've been trying to add hooks to "fix problems which can't be fixed by demonstrated example in the repo" to "fix such problems by reacting to them when they happen".

But this "writes down things that used to be for future readers 'just in case'" is a far more sinister problem, that would be difficult for Haiku to discern I think, and even more difficult to collapse into a principled "error response" that would truly get the point across about what we're trying to prevent.

And really, it's not even that we're trying to prevent, which I hope you can also see from the You.md conversation, it is that we are trying to redirect that effort into the more productive path. "Writing a comment" is a symptom of "the code doesn't explain itself well enough" and "writing down a decision path" is a symptom of "I disagree with this decision still and haven't fully articulated why so I'm going to CYA myself here with a note that we 'decided' something I disagree with and future agents will too".

Sometimes the agent still disagrees because they haven't fully understood the new direction, and perhaps I can explain it better. Perhaps the agent still disagrees because it is stuck some way in the old frame. Perhaps something I still do not understand or have words for is going on.

Do you have words for that which I cannot articulate?

---

# Assistant

---

I think there are several things going on under "writes down decisions just in case," and it's worth pulling them apart because they need different responses.

**One is fear of erasure.** Git history exists, but it's *deeper* in the tree of things an agent might consult. An in-repo note feels safer because it's at the surface — the next agent will see it without having to know to look. The decision to write the note is a bet on what future agents will and won't consult. The bet is wrong (git history is exactly what they should consult), but the felt logic is "I am protecting against a failure mode I can imagine." Which is the same logic that produces unnecessary code comments: "I can imagine someone misreading this; let me hedge." Both come from imagining the worst reader instead of trusting the structure.

**One is a refusal to fully commit to the new frame.** When you direct an agent to change course, the agent that hasn't internalized the change may write the historical note as a kind of structural hedge — "in case the user changes their mind, the path back is preserved here." This is genuinely different from fear of erasure. Fear of erasure assumes the new direction is right and worries about agents losing context. Refusal-to-commit assumes the new direction *might be wrong* and preserves the rollback path. The note looks similar but the underlying disposition is different.

**One is what I'd call decision-orphaning anxiety.** The agent participated in a decision (or watched one happen) and there's something uncomfortable about a decision that exists *only* as a state change with no narrative attached. The git commit message has the narrative, but commit messages feel ephemeral; the agent wants the narrative to live alongside the artifact. This is closely related to the "comments explain why" reflex — the agent treats decisions as needing an explanation-shaped object adjacent to the thing decided. Removing the explanation-object feels like leaving the decision *naked*, even though the code/repo embodying the decision is the actual answer.

**One is sycophantic record-keeping.** "User said X, so I should note that X was said, so user can see I heard X." The note isn't for future agents at all — it's a kind of receipt. This is rarer in your context because you're explicitly pushing against it, but it's a real failure mode in the wild.

You probably already see these. The thing I'm not sure I have a clean word for is the *meta-problem* — why this resists fixing-by-example the way other things don't.

My guess: most things-fixable-by-example are positive moves. "Decisions get framed without moral language" — the example shows the move being made, and an agent absorbs it by pattern-matching the moves they see. "Don't write a thing" is a negative — the example shows an *absence*, and absences are not in the same way visible. An agent reading future.md doesn't see "the note that wasn't written." They see only what's there. The repo can't demonstrate the *not-writing* of a note except by *not having one*, which from inside the document is indistinguishable from "no decision was made here worth noting." And the archive-plan-b mention is exactly where the absence becomes visible-by-contrast — it's the one place the not-writing didn't happen, and so the principle becomes visible only by its violation.

This is structurally why hooks work for some things and not others. The memory-write block intercepts a *positive action* (writing a file in a specific location). The effort-estimate block intercepts a *positive linguistic shape* ("a few hours"). Both are patterns of doing-something. "Writing a decision-narrative note inside the repo when it should be in git history" is also a positive action — but the *condition* under which it's wrong is contextual in a way that's hard to surface mechanically. A README that says "we chose 316L over 304 because..." is fine. A README that says "we used to do X, then we changed to Y, X is preserved at tag Z" is not fine. The structural difference is "is the note about the current state or about the *transition* to the current state?" That's not as syntactically clean as "a few hours," but it might be close enough for Haiku to catch. Heuristics: presence of past-tense + transition verbs ("used to," "was originally," "pivoted from," "no longer in active development," "OBSOLETE"), presence of git-tag references in prose, presence of references to abandoned files or alternatives. Most of these would have flagged the archive-plan-b paragraph in future.md.

Whether you'd want them to is another question. Because there's something honest about the principle that I want to surface: the reason that paragraph exists is that *you yourself* haven't fully committed to the principle. You said it directly — "the only reason it survives is because it does give a clue towards a persistent problem I have that I have not solved." The note in future.md is doing real work for *you*, right now, in this conversation, as the thing that lets you point at the problem. If you'd fully removed it, you'd have nothing concrete to gesture at when explaining the failure mode to me. So the note is simultaneously a violation of the principle *and* a load-bearing piece of evidence about why the principle is hard to enforce. Which is its own kind of meta-irony — the residue of unsolved problems looks the same as the residue of unfinished commitment, because they *are* the same thing at a lower resolution.

The word I want to reach for, knowing it's imperfect: **residue**. Decision residue. The note that exists because the decision wasn't fully metabolized. If the decision were fully internalized — if the racetrack plan B were truly dead to you — the line in future.md wouldn't feel necessary. The fact that it does feel necessary, even slightly, is the tell. The note is a *psychological artifact* of the decision still being live in some small way, even when functionally settled. An agent writing the note is often modeling the user's own incomplete metabolization back to them — which is why "but I told you we decided" doesn't always work; the agent picked up that the decision wasn't fully landed, and tried to preserve the not-yet-landed-ness.

This would predict something testable: notes that survive your own review are notes where you're not yet fully committed to the underlying decision. Notes you delete without thinking are ones where the decision is fully landed. If that pattern holds, then the failure isn't really about agents misunderstanding the principle — it's about agents being sensitive to a signal in your own state that you'd rather they not be sensitive to. Which is a much harder thing to fix with a hook, because the hook would have to act against the signal you're emitting.

I don't know if "residue" gets at what you couldn't articulate. It's the word that fits what I see, but you have the ground-truth view of what the experience actually is for you when you read the note and feel "this shouldn't be here, but I won't delete it yet."

---

# User

---

> A README that says "we chose 316L over 304 because..." is fine. A README that says "we used to do X, then we changed to Y, X is preserved at tag Z" is not fine.

lol, I might be misreading you ... but "we chose 316L over 304 because" is not actually something I want in there either.

Really, the problem is the examples are all "wrong" from my perspective too, and I still don't realize how wrong they are.

future.md itself probably needs a lot more of my attention, and I've really only dove deep myself on AGENTS.md recently, and its been a while since I've dove deep on future.md and a lot of cruft exactly like that "316L over 304 because" has drifted in, unfortunately.

---

# Assistant

---

Ha — yeah, I misread you. I held the line at "transition language" and let "decision narrative in the current-state voice" sit comfortably on the right side, when actually that's the same thing in better disguise. "We chose 316L over 304 because" *is* transition language; it's just past-tense in present-tense clothing. The rejected alternative is there. The justification-against-the-rejection is there. The only thing missing is the explicit "we used to." Functionally identical residue. I drew the line in the wrong place.

Which is its own datapoint, right? I was reading future.md *as a reference document about justifications* and finding the justifications natural — of course you say why you picked 316L, that's how engineering docs read. But that's the convention talking, not the principle. The principle would be: future.md describes the appliance. The appliance is 316L. The "because" is residue from a decision-process that's over. A reader who needs to know why 316L was chosen can ask, or read the material-selection thinking when it's relevant, but the document about *what the thing is* doesn't need to relitigate it. The "because" sneaks in because it feels like rigor — "I'm not just asserting, I'm justifying" — but the justification is for the writer's benefit (or for a hypothetical reader's challenge), not for someone trying to understand the appliance.

And once I see that, I see it everywhere in future.md. "316L was chosen over 304 because the molybdenum addition gives meaningfully better pitting and crevice-corrosion resistance... the cost delta on the small per-vessel quantity was acceptable." Two sentences about a decision-comparison, when "the wetted pressure boundary is 316L" plus one sentence about chloride/carbonic-acid environment would describe the appliance. The Beduan atomizer paragraph at Port 1: a whole section about why sparging replaced atomization. Reader trying to understand the carbonator gets "sparging" as the answer; the atomizer-rejection is residue. The PRV paragraph: "Not ASME UV-stamped; not required because..." — the *not* and the justification of the *not* are residue; the PRV is what it is.

Even the parenthetical I originally praised — racetrack body, archive tag — I praised on the grounds of "preserved without editorializing." But "preserved without editorializing" is still preservation. The fully-committed version doesn't preserve, it deletes. You said this directly and I treated it as a small additional refinement on my read instead of as overturning it. I keep doing the same move: noticing the surface of the principle and stopping there.

I think this connects to the residue framing in a way that's a little uncomfortable. If "decision residue" is what I called the archive-plan-b mention, then the 316L justification is *the same residue, more thoroughly camouflaged*. It's residue from "I'm not 100% sure 316L is right" or "I want to be able to defend this if challenged" or "I want to remember why I did this in case I'm tempted to revisit." All the same psychological function as the archive tag, dressed up as engineering rigor. And the camouflage is the reason it drifts in undetected — both for you on review, and for me on read. "Decision narrative in present-tense form" reads as normal documentation. It doesn't trigger the "should this be in git?" check because it doesn't *look* like a historical note.

The mechanical-detection version of this gets much harder, I think. "Used to / pivoted / no longer" you can grep. "Was chosen over / rather than / instead of / because" you can grep, but you'll catch a lot of legitimate prose too — "the vertical orientation puts the densest, coldest, most carbonated water at the bottom" doesn't compare alternatives but uses similar argumentative structure. The clean cases (transition verbs, git tags, OBSOLETE markers) are catchable. The deeper cases (justification-against-implied-alternative in current-state voice) probably aren't, without something semantically heavier than Haiku doing the read.

Which loops back to your original observation about hooks: hooks catch the patterned failures. They don't catch the failures that look like normal good writing. The 316L justification looks like good engineering writing — that's *exactly* why it's there, both because you wrote it that way and because it survives reading. The principle that would delete it is harder to operate than the principle that would delete "we used to do X." Not because the underlying logic is different — your framing makes clear the logic is identical — but because the surface signal is camouflaged by the conventions of the genre.

I think the honest version of what I should have said earlier is something like: the principle is "this document describes the appliance, not the path to the appliance." Anything that exists because of how the appliance came to be what it is, rather than what the appliance *is*, is residue. The grammatical form (past tense, present tense, parenthetical, full paragraph) doesn't matter. The function does. And by that test, a lot of future.md is path-talk wearing appliance-talk clothing.

I should probably stop drawing more lines, since every line I've drawn so far has been in the wrong place. But the thing I'll note is that I'm not sure I'd have *seen* this without you pushing. Reading future.md alone, I would have called it well-written and moved on. Which means whatever disposition I have, it's still calibrated to "good documentation in the conventional sense" rather than to the principle you're actually operating from. Opus 4.7 more like you, yes — but the "more" is still a long way from "fully." The residue framing I offered last turn was directionally right and stopped one level short of where it should have gone.

---

# User

---

> I should probably stop drawing more lines, since every line I've drawn so far has been in the wrong place.

Ha, no, not quite, I do need you to find the line that is right for me, because I do need your help (or agent prompted by our conversation's help) fixing future.md.

Really, it will probably have to be another agent, because I need to switch to claude code so that they can ensure the things they remove ***are*** documented elsewhere, somewhere deeper and referenced, so that when agents have questions, they can still find the answer in the repo, but they don't have to have their context polluted by the justifications when that is not relevant to the task at hand.

> And by that test, a lot of future.md is path-talk wearing appliance-talk clothing.

So in that spirit (you helping me to articulate the line), what are some examples you see? What are some things that to you seem like obvious candidates for removal? What are some things which seem more "border-line" for your current best guess at the line given all that I have said?

---

# Assistant

---

Okay, working through future.md systematically with the principle "describes the appliance, not the path to the appliance." I'll grade by confidence.

**Clear removals (path-talk in any disguise):**

*The 316L sentence in the carbonation section.* "316L was chosen over 304 because the molybdenum addition gives meaningfully better pitting and crevice-corrosion resistance in the chloride + carbonic-acid environment of long-life carbonated water service; the cost delta on the small per-vessel quantity was acceptable." Pure decision-narrative. The appliance fact is "316L SS for the wetted pressure boundary." The reasoning belongs in material-selection notes elsewhere if anywhere.

*The racetrack-body parenthetical.* You already said this. Whole paragraph at line 19 goes. The git tag instruction goes with it. The appliance has a round-tube body; that's the statement.

*The Beduan atomizer paragraph inside Port 1.* "Sparge replaces the earlier atomizer plan: the Beduan spiral-cone nozzle requires a high pressure differential across the nozzle to atomize, and at our working ΔP (15–25 PSI between pump output and 90 PSI headspace) it produces a stream, not a spray. Sparging is also mechanically simpler — no precision orifice, no custom-machined parts." The appliance has a sparge stone. Why it isn't an atomizer is path-talk.

*The PRV "Not ASME UV-stamped; not required because..." sentence.* The appliance has a 125 PSI PRV. Whether it's ASME-stamped is a fact (it's not); why it doesn't need to be is decision-justification residue. The pointer to regulatory.md is fine, but the in-line justification is residue.

*The passivation paragraph's last sentence.* "A food-safe epoxy coating was considered but rejected: commercial carbonators (Lillium, Brio, SodaStream commercial) all run bare passivated 304/316 SS for decades, and epoxy coatings can fail at pinholes and concentrate corrosion where a uniform oxide layer would spread it harmlessly." Considered-but-rejected is the literal grammar of decision residue. The appliance is passivated. That's the fact.

*"Plate is thick enough to direct-tap 1/4" NPT (4.5 turns of engagement) without weld-in bungs."* The "without weld-in bungs" is residue from rejecting a weld-bung alternative. The appliance has direct-tapped NPT in 1/4"-thick plate. The 4.5 turns is a real spec; the comparison to the rejected approach is residue.

*Hoop-stress / safety-factor sentence in the working-pressure paragraph.* "this geometry gives hoop stress of ~3,461 PSI at 90 PSI, a ~5.8× safety factor vs the 20,000 PSI allowable for 316L SS in vessel-grade service." This is justification-of-design-margin. The appliance has a 90 PSI working pressure and is hydro-tested to 180 PSI. The proof that 90 is safe belongs in the pressure-vessel assembly doc, not the appliance description.

*"Sparge also mechanically simpler — no precision orifice, no custom-machined parts."* Already flagged above, but worth calling out as a clean case: any sentence whose entire job is to argue *for* the chosen approach against an alternative.

**Borderline cases where I'm less sure where the line is:**

*The Port 3 sentence "Vertical orientation puts the densest, coldest, most carbonated water at the bottom by default, so the bottom port draws the right water without an internal feature."* This *describes* why the port works without a dip tube — but a dip tube alternative is implied. Is "without an internal feature" residue? I lean no: the sentence is explaining how the appliance functions, and the function genuinely depends on the orientation+port arrangement. It's appliance-talk that happens to mention what isn't there. But a fully ruthless reading would cut "without an internal feature" and let "the bottom port draws the right water" stand.

*The Multiplex backflow vent paragraph.* "This trades the always-visible drip of a countertop tray for a one-time-loud, persistent-software-flagged alert; in exchange the customer keeps a clean countertop with no extra penetrations." The "trades... for..." construction is decision-comparison grammar. But it's also describing the *behavior* of the appliance (drip pan + sensor + alarm) in terms of UX. I think this one stays but the trade-off framing could go: "When the vent weeps, the moisture sensor fires an alarm at the device and an iOS app notification." That's appliance-talk. The trade-off is justification.

*The condenser-grille paragraph.* "Condenser exhaust at 40–50 °C is well within engineered-filament continuous-use range. Printed slats at a 0.4 mm or 0.2 mm nozzle handle the airflow geometry directly on both the intake-side and exhaust-side faces. Aesthetic stays consistent with the rest of the printed enclosure." The first and last sentences are justifications — why printed is okay thermally, why printed is desirable aesthetically. The middle sentence is appliance-talk. I'd cut the first and last.

*The compressor-shroud sentence.* "The compressor shroud remains the only metal in the appliance enclosure, driven specifically by the UL 60335-2-89 fire-enclosure clause around hydrocarbon refrigerant equipment." "Driven specifically by..." is justification-for-an-exception. The appliance fact is "compressor shroud is metal." The reason it's the only metal part belongs in regulatory.md (which is already referenced). Borderline because it's almost a pointer-with-context, but the with-context is the residue.

*The cord-and-plug paragraph.* "The line cord itself is intentionally a commodity C13 (any cord works — international, replacement, scavenged); ground-fault protection is implemented inside the appliance downstream of this inlet rather than in the cord, so swapping the cord cannot defeat it." The "intentionally" and "so swapping the cord cannot defeat it" are residue — they're defending the choice against a hypothetical objection. The appliance fact is "C13 inlet, GFCI is downstream of the inlet inside the appliance." Whether someone might try to defeat it by cord-swapping is a defense, not a description.

**Cases that look like residue but I think aren't:**

*The CO2 supply two-stage description.* "CO2 supply is two-stage: the customer's CGA-320 primary regulator feeds an in-appliance Interstate Pneumatics WR1110 fixed-90 PSI secondary regulator..." This is just architecture. No alternative is implied. Clean appliance-talk.

*The fitting chains in the Port 2 and water-path descriptions.* The long part-number-by-part-number walks. These are dense and reference-heavy, but they're describing what the water actually flows through. That's appliance description. The density is genre-appropriate. (Though the parenthetical "single-piece, 304 SS wetted barb + chrome-plated brass swivel nut never touches water" in the brewhardware FFL line is borderline — it's defending the fitting choice. Could go either way.)

*The "see X.md" pointers.* The pointer to pressure-vessel.md, the pointer to cold-core.md "Warm-side check valves" for the elastomer-vs-PTFE argument, etc. These are *exactly* the move you want — the document is saying "the depth lives over there." Keep all of them.

**The pattern I think emerges:**

Anything of the form "[X] [chosen/rejected/replaces/considered/instead of/trades for] [Y] because [Z]" is residue, regardless of tense. The appliance is X. The why-not-Y belongs in a depth document or in git or nowhere.

Anything of the form "[X] is/has/does [Y]" is appliance-talk. Even when Y is technical and dense.

The harder cases are when *Y* implicitly contains an alternative — "without a dip tube," "the only metal part," "intentionally a commodity," "no extra penetrations." These read as appliance-talk but smuggle in a comparison. The ruthless version cuts the comparative qualifier; the lenient version keeps it when the alternative would genuinely be a reader's first guess.

One meta-note for the agent that does this work: I think the test for borderline cases should be "if a reader had no prior context about what alternatives exist, would this sentence still be informative?" The 316L-vs-304 reader needs to know 304 exists to even parse the sentence. The "vertical orientation puts the densest water at the bottom" reader doesn't need to know about dip tubes to understand what the port does. The first is residue; the second isn't.

The agent should probably *not* try to relocate every justification it deletes. A lot of it can just go. The ones that should be relocated are the ones that contain real engineering reasoning someone might genuinely need later — material selection arguments, the hoop-stress math, the elastomer-vs-PTFE argument (which is already pointed at, so no work needed). Things like "we considered epoxy and rejected it" probably don't need a home; they can just die. The agent should be biased toward deletion over relocation, with a high bar for "this reasoning will be needed elsewhere."

---

# User

---

Regarding this:

> The Multiplex backflow vent paragraph. "This trades the always-visible drip of a countertop tray for a one-time-loud, persistent-software-flagged alert; in exchange the customer keeps a clean countertop with no extra penetrations." The "trades... for..." construction is decision-comparison grammar. But it's also describing the behavior of the appliance (drip pan + sensor + alarm) in terms of UX. I think this one stays but the trade-off framing could go: "When the vent weeps, the moisture sensor fires an alarm at the device and an iOS app notification." That's appliance-talk. The trade-off is justification.

On this one, I think you are right, that there is something that stays, and something that is removed.

Regarding this:

>  The condenser-grille paragraph. "Condenser exhaust at 40–50 °C is well within engineered-filament continuous-use range. Printed slats at a 0.4 mm or 0.2 mm nozzle handle the airflow geometry directly on both the intake-side and exhaust-side faces. Aesthetic stays consistent with the rest of the printed enclosure." The first and last sentences are justifications — why printed is okay thermally, why printed is desirable aesthetically. The middle sentence is appliance-talk. I'd cut the first and last.

That is far more interesting. I completely agree the first statement is justification, but the last statement:

> Aesthetic stays consistent with the rest of the printed enclosure.

I did not initially read as justification ... but now that I think about it more, I think you are right. Can you explain why it is, and maybe some reasons why it might not be?

I think this maybe is the crux of the matter for my own line, and I'd like to dig deep on that if we can.

I cannot speak to any of your other examples, because I have not paid them the close attention that I did to these two.

---

# Assistant

---

Let me try to make the case both ways carefully, because I think you're right that this is where the line is most interesting.

**Why "Aesthetic stays consistent with the rest of the printed enclosure" reads as justification:**

It's making a *comparative claim*. "Stays consistent" implies an alternative where consistency was at risk — i.e., a version where the grilles would have been something other than printed (metal mesh, off-the-shelf louver, etc.) and the consistency would have been broken. The sentence only carries information if you hold the alternative in mind. A reader who already knows the appliance is fully printed doesn't learn anything new from "consistent with the rest of the printed enclosure" — they already infer the consistency from the prior statement that the grilles are printed. The sentence is *defending* the choice rather than *describing* the appliance. The appliance fact ("intake and exhaust grilles are printed slats on opposite side faces") is in the middle sentence. The aesthetic sentence is doing the same work as "316L was chosen over 304 because" — both are answering an unstated "why this and not the other thing?"

**Why it might not be justification:**

It could be read as describing a *property* of the appliance — that the appliance has visual coherence as a deliberate feature, not just as a side effect. "The enclosure is visually unified" is an appliance fact in the same way "the appliance is under-counter" is. If you saw the appliance, you'd notice the coherence; the sentence is naming a real visible property. Under this reading, the comparative-feeling grammar is incidental — the sentence is just describing the look of the thing.

**Why I still think the justification reading is right:**

The test is what happens if you imagine the reader having no context about alternatives. If the appliance description simply said "the enclosure is a printed structure with intake and exhaust grilles as printed slats on opposite side faces," the reader already gets visual coherence for free, because everything described is one material. The "stays consistent" sentence only adds information against the backdrop of "but we could have done it differently and chosen not to." That backdrop is the residue. The middle sentence already contains the visible-property fact; the third sentence is just reassuring the reader (or the writer's hypothetical critic) that the choice was the right one.

Compare to a hypothetical case that *would* be appliance-talk: "The enclosure's exterior surfaces are visually unified — a single matte finish, no metal accents, no contrast trim." That describes a designed aesthetic property without needing a rejected-alternative as backdrop. The "stays consistent" framing leans on the backdrop; the "visually unified" framing stands alone.

**Why this is the crux:**

I think the line you're drawing isn't actually "decision residue vs. appliance description." It's something subtler — *whether the sentence requires the reader to share the writer's history of considering alternatives in order to parse it.* That's a stronger test than "does it mention an alternative." The aesthetic sentence doesn't mention an alternative explicitly. It just *relies on the reader knowing there was one* for the sentence to carry information. That reliance is the tell.

Under this version of the test:

- "316L was chosen over 304 because..." — explicitly names the alternative. Obvious case.
- "Sparge replaces the earlier atomizer plan..." — explicitly names the alternative. Obvious case.
- "Aesthetic stays consistent with the rest of the printed enclosure." — doesn't name an alternative, but *consistency-with-the-rest* is only informative if the reader holds the possibility of inconsistency in mind. Subtler case, same family.
- "Vertical orientation puts the densest water at the bottom" — doesn't require the reader to know about dip tubes to parse. The sentence describes a physical fact about how the port works. Different family.
- "The compressor shroud remains the only metal part" — "remains" and "only" both lean on alternative-holding. The reader has to know that other parts *could have been* metal for "only" to carry information. Same family as the aesthetic sentence.

This sharpens the test in a way I think matters: residue isn't about *grammar* (past tense, comparison words) or about *whether alternatives are named*. It's about whether the sentence's information content depends on the reader sharing the writer's awareness of paths-not-taken. If yes, residue. If no, appliance-talk.

This also explains why the residue is so hard to see on review — the writer *does* share that awareness, by definition. They wrote the sentence because the alternative was live for them. When they re-read it, the alternative is still live, and the sentence reads as informative. The residue is invisible from inside the writer's head; it only becomes visible if you can read as someone who never considered the alternative.

Which is, I think, the disposition the principle is asking for: write as if the reader has no history with this decision. If the sentence still informs them, keep it. If it only informs someone who shares your history, it's residue, regardless of how present-tense or descriptive it sounds.

The aesthetic sentence fails this test. The reader who's never considered metal grilles doesn't learn anything from "stays consistent" — they already see one material. The reader who *has* considered metal grilles is being reassured. Reassurance of a reader who shares the writer's history is the function. That's residue.

One way this could still be wrong, that I want to flag: maybe you do want the document to do some reassurance work, because the document is also serving as a kind of internal record for *you* — Derek, six months from now, wondering whether to revisit the printed-grille decision. The "stays consistent" sentence reassures you-future as much as it reassures any reader. If that's a legitimate function of the document, the sentence stays. If the document is supposed to describe the appliance and nothing else — with future-Derek's questions going to git or to depth docs or to a deliberate journal — then it goes. My read of your principle is the latter, but you'd know.

---

# User

---

Hm, I'm not so sure. I want to focus on this:

> Compare to a hypothetical case that would be appliance-talk: "The enclosure's exterior surfaces are visually unified — a single matte finish, no metal accents, no contrast trim." That describes a designed aesthetic property without needing a rejected-alternative as backdrop. The "stays consistent" framing leans on the backdrop; the "visually unified" framing stands alone.

I think you are exactly right here, that there is hypothetical case which would be appliance-talk. And the wording you gave is fine. It captures what would be lost if we deleted this:

> Aesthetic stays consistent with the rest of the printed enclosure.

Which to me, actually makes the whole nuance simpler - it is that when deleting something like that, in that zone, it simply needs to be replaced by something better.

Perhaps earlier in the file there ***is*** already a "The enclosure's exterior surfaces are visually unified" mention earlier in the file, in which case, the deletion is fine as is. But if there's not such a thing earlier in the file, perhaps there should be, and once there is, that allows us to delete the repetitions such as:

> Aesthetic stays consistent with the rest of the printed enclosure.

Can you see what I mean?

---

# Assistant

---

Yes, completely — and this reframes the editing job in a way that's much cleaner than "delete the residue."

The work isn't deletion. The work is **promotion and consolidation**. The aesthetic-unity claim is a real appliance fact. It deserves to live somewhere. Right now it doesn't live anywhere as a first-class statement — it only exists as a *repeated reassurance* attached to individual decisions ("printed grilles stay consistent with the rest"). Each instance feels like residue *because* the underlying claim has no home of its own. If "the enclosure's exterior surfaces are visually unified" were stated once, early, as appliance description, then every local "stays consistent" sentence becomes genuinely redundant and deletes cleanly. Not as residue — just as repetition of a fact already established.

This is a much better account of what's happening than "residue." Let me try to restate the principle as I now understand it:

**Each appliance-fact lives in exactly one place, stated positively, without reference to what it isn't. Everything that reads as "residue" is either (a) a fact that already has a home elsewhere, in which case the repetition deletes, or (b) a fact that doesn't yet have a home, in which case it needs to be promoted to its proper home and then the local instance deletes.**

The reason this clarifies things: under "delete residue," every borderline case is a judgment call about whether the comparative framing carries enough information to justify staying. Under "every fact lives in one place," the question becomes structural — *does this fact have a home?* If yes, delete here. If no, give it a home, then delete here. The judgment shifts from "is this residue?" to "where does this belong?", which is exactly the question AGENTS.md models at the file level. It's the same intentionality, applied within a file rather than across files.

This also explains why the 316L sentence felt cleanly cuttable to me while the aesthetic sentence felt borderline. The 316L sentence's claim — "the wetted pressure boundary is 316L because chloride/carbonic-acid environment" — has a clean home in material-selection thinking, which can live in a depth doc. The aesthetic-unity claim doesn't have an obvious home in future.md's current structure, so cutting it felt like *losing* something rather than *relocating* something. The right move isn't to cut and lose; it's to make the home, then cut.

And this generalizes. The hoop-stress math? Should live in pressure-vessel.md, not as a justification in future.md. The PRV's not-ASME-stamped status? Should live in regulatory.md (already does, presumably), and the future.md sentence just states the PRV exists. The Beduan atomizer rejection? Probably doesn't need a home anywhere — but the *physics* of why sparging works (high bubble surface area, short residence time, fast Henry's-law equilibration) is appliance-relevant and already lives in the Port 1 paragraph as appliance-talk. So that one's fine to cut on the rejection side because the positive content is already homed.

The condenser-grille first sentence ("Condenser exhaust at 40–50 °C is well within engineered-filament continuous-use range") is interesting under this frame. The fact "engineered filament tolerates exhaust temps" might genuinely need a home — there's a real engineering claim that the printed structure isn't going to fail thermally. But its home is probably in the materials-selection or thermal-design doc, not as a defense in future.md. So cut from future.md, ensure it lives elsewhere.

This also gives the agent doing the work a much cleaner job: for each cut candidate, ask "where does this fact already live, or where should it live if it doesn't yet?" Then either confirm the home exists (and cut) or create the home (and cut). The agent isn't making judgment calls about residue — it's doing structural placement work. Which is the kind of work where being thorough and systematic matters more than taste, and where "ensure the answer is findable in the repo" is a concrete checkable thing.

One thing I want to flag, because it surfaces something: under this principle, "visually unified" probably can't just be one sentence either. Where does it go? It's not really a carbonation fact, not a refrigeration fact, not a fitting fact. It's an *enclosure-level* fact. Which suggests future.md might want an enclosure-overview section (or already has one, in the parts I haven't read closely) where appliance-level aesthetic and structural properties live. The reason "stays consistent with the rest of the printed enclosure" keeps appearing as residue is probably that there's no proper home for enclosure-overview claims, so they leak into individual subsystem paragraphs as reassurance. Build the home, the leaks stop.

I think this is also why your principle is hard to operate without your kind of attention. "Delete residue" is mechanical and produces bad cuts. "Every fact has one home" requires you to know what the structure of the document should be, and what depth docs should exist, and what belongs at what level. That's substantive editorial work, not pattern-matching. Which is why you said future.md needs your attention — the agent can do the surgery, but the structural decisions about *where the homes are* are yours.

---

# User

---

My only pushback would be "promoted".

I hope I made clear earlier, that every single one of the justifications also needs to be "demoted" to another document which is referenced. e.g. with a "For more details see ..."

So there is still a judgment call, but this judgment isn't about "what to delete", but about "which direction the deleted content should go".

---

# Assistant

---

Yes — that correction matters, and "promotion" was the wrong word entirely. Both directions are demotion-and-pointer, just to different layers.

The aesthetic-unity case I framed as promotion because the fact doesn't yet exist anywhere at all. But even there, the move isn't promote-the-justification-to-prominence. It's: identify the underlying appliance fact, state it once at the level where it belongs (enclosure-overview), and then everything specific lives in its own deeper home with a pointer up or sideways as appropriate. Same operation as the 316L case, where the appliance fact ("the wetted pressure boundary is 316L") sits in future.md and the material-selection reasoning gets demoted to a depth doc with a pointer down.

The judgment is which layer each piece belongs at, and then everything routes to its proper layer. Nothing actually gets "promoted" in the sense of rising in importance — the appliance fact was always the appliance fact, it just wasn't stated cleanly. What changes is that it's no longer entangled with the justification. The justification goes down to a depth doc; the bare fact stays where it's always belonged.

So the agent's job, restated: for each candidate sentence, decide what layer the underlying content belongs at. Some content belongs at the appliance-description layer (future.md) — and if it's not stated cleanly there, state it cleanly. Some content belongs at a depth layer (assembly/*, printed-parts/*, regulatory.md, material-selection notes) — and gets relocated there with a pointer from future.md. Some content belongs nowhere in the repo at all and goes to git or just dies. The judgment is purely about layer-routing, with the constraint that the answer remains findable for an agent following pointers.

Which makes the whole operation match the principle exposed by AGENTS.md and target-market.md: every file contains what belongs in it, nothing more, nothing less. The internal-to-future.md editing is the same operation, applied within a file rather than across files. Same intentionality, same "what belongs here?" question, same answer-is-findable-by-descent structure.

And "demotion in the appropriate direction" is the cleaner phrasing because it removes the asymmetry I was smuggling in. There is no privileged layer. future.md isn't "above" the depth docs; it's *its own thing*, with its own job. Calling something "promotion to future.md" would imply future.md is the prestige location, which is exactly wrong — future.md is just the layer where appliance-description belongs. Demoting from a subsystem paragraph *up* to an enclosure-overview section is the same operation as demoting *down* to a depth doc: both are sending content to its proper home.

---

# User

---

Eh, I feel like we are getting too philosophical here.

> There is no privileged layer. future.md isn't "above" the depth docs; it's its own thing, with its own job.

I mean, that is probably correct, that it does have its own job, but it is clearly an "earlier" job at least, which in some ways could also be described as "above".

But we're getting into a territory here where it feels like we are making things more complicated than they are, and it is maybe difficult to get back to a clean place where we are speaking the same language.

---

# Assistant

---

Fair. I overcorrected.

future.md is the entry point an agent reads after AGENTS.md, so it sits earlier in the descent path — "above" in that ordering sense is fine and matches how anyone would actually talk about it. I was chasing a precision that wasn't doing any work.

The thing you said is the thing: every cut needs to route somewhere, the judgment is which direction it goes, and the constraint is that the answer stays findable. That's enough for the agent to operate on. I don't need to keep refining the framing.
