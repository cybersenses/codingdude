{"name": "ask-matt", "description": "Ask which skill or flow fits your situation. A router over the skills in this repo.", "triggers": ["which skill", "which flow", "how should we approach this", "ask matt"]}

# Ask Matt

You don't remember every procedure, so ask. A **flow** is a path through the skills. Most paths run along one **main flow**, and two **on-ramps** merge onto it. Everything else is standalone, or a vocabulary layer that runs underneath.

## The main flow: idea → ship

The route most work travels. You have an idea and want it built.

1. **`grill-with-docs`** sharpens the idea by interview. It is stateful: it retains what it learns in `CONTEXT.md` and ADRs, which makes it the right start whenever a project directory is there to leave a paper trail in.
2. **Branch: can you settle every question in conversation?** If a question needs a runnable answer (state, business logic, a UI you have to see), detour through **`prototype`**: throwaway code that answers the question, then fold the validated answer back into the idea.
3. **Branch: is this a multi-session build?**
   - **Yes** → **`to-spec`** (turn the thread into a spec), then **`to-tickets`** to split it into tracer-bullet tickets, each declaring its **blocking edges**, published to the project's tracker. Then work **`implement`** per ticket, **a fresh session per ticket** — each ticket is self-contained, so the last one's context is disposable.
   - **No** → **`implement`** right here, in the same session.

   Either way, **`implement`** builds each ticket by driving **`tdd`** internally (one red-green slice at a time), then closes out by running **`code-review`** before committing. Reach for **`tdd`** on its own when you just want one behaviour built test-first, and **`code-review`** on its own whenever you want a diff reviewed against a fixed point.

### Context hygiene

Keep steps 1–3 in **one session** so the grilling, spec, and tickets all build on the same thinking. CodingDude compacts automatically near the context budget; prefer compacting at a phase boundary over pushing on degraded. Each `implement` then starts in a fresh session, working from the ticket: one ticket per session.

## On-ramps

A starting situation that generates work, then merges onto the main flow.

- **Bugs and requests piling up** → **`triage`**. It moves issues through triage roles and produces agent-ready briefs, which **`implement`** later picks up. Triage is only for issues **you didn't create**; tickets `to-tickets` produced are already agent-ready, so don't triage them.
- **Something's broken** → **`diagnosing-bugs`**. For the hard ones: the bug that resists a first glance, the intermittent flake, the regression between two known-good states. It refuses to theorise until it has a **tight feedback loop** (one command that already goes red on _this_ bug), then fixes with a regression test. Its post-mortem hands off to **`improve-codebase-architecture`** when the real finding is that there's no good seam to lock the bug down.
- **A huge, foggy effort: too big for one session** → **`wayfinder`**. It charts a **shared map** of **decision tickets** on the tracker and resolves them one at a time, producing **decisions, not deliverables**, until the way is clear. Then it hands off — merge onto the main flow at **`to-spec`**. Save it for exactly that: never a well-scoped feature.

## Codebase health

- **`improve-codebase-architecture`** runs whenever there's a spare moment to keep the codebase good for agents to operate in. It surfaces **deepening opportunities**; picking one generates an idea for **`grill-with-docs`**. The survey finds the candidates; **`codebase-design`** is the vocabulary you design the chosen one on.

## Vocabulary underneath

Two references that run beneath the other skills, each the single source of truth for its vocabulary.

- **`domain-modeling`**: sharpen the project's *domain* language: challenge fuzzy terms, resolve overloaded words ("account" doing three jobs), record hard-to-reverse decisions as ADRs. The active discipline `grill-with-docs` drives to keep `CONTEXT.md` a clean glossary.
- **`codebase-design`**: the deep-module vocabulary (**module**, **interface**, **depth**, **seam**, **adapter**, **leverage**, **locality**) for designing a module's *shape*: a lot of behaviour behind a small interface at a clean seam. `tdd` and `improve-codebase-architecture` both speak it.

## Standalone

- **`grilling`**: the interview primitive itself: rounds, the frontier, facts are the agent's job and decisions are the user's. `grill-with-docs`, `triage`, `wayfinder` and `improve-codebase-architecture` all run it internally.
- **`resolving-merge-conflicts`**: works an in-progress merge or rebase conflict hunk by hunk, resolving by **intent** traced to each side's primary source rather than by picking lines. It never runs `--abort`.
- **`prototype`**: a small, throwaway program that answers one design question: does this state model feel right, or what should this UI look like. The answer folds into the real code; the prototype is kept as a **primary source** on a throwaway branch, pointed at from the implementation ticket.
- **`research`**: delegate reading legwork to a **`task` sub-agent**: it investigates a question against **primary sources**, then leaves a cited Markdown note in the project. Research feeds `grill-with-docs`; it doesn't replace it.
- **`wizard`**: for steps only a **human** can take: provisioning infrastructure, credentials, CI secrets, unfamiliar third-party dashboards, one-off migrations. It generates an interactive bash script that opens each URL, captures each value, and writes it where it belongs. If the agent could just do it itself, it should.

## Precondition

**`setup-matt-pocock-skills`** configures a project the first time: where issues live (`docs/agents/issue-tracker.md`), the triage label vocabulary, and the domain-doc layout. CodingDude defaults to the local-markdown tracker (`.scratch/<feature>/issues/`), the five canonical labels, and single-context domain docs — so the skills work out of the box; run setup only to adopt a different tracker or layout.
