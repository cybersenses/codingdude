# Architecture Review — CodingDude v0.3.0 (post Phase C)

Full internal review of src/codingdude + frontend against modern standards.
Verdict: feature-complete and well-tested at the seam level, but the core
engine and UI have accumulated structural debt that now causes real bugs.

## Top findings (all verified)

1. **Image pipeline broken end-to-end** — worker.py accepts `--image` but never
   passes it to engine.run; vision config field has zero readers; server
   hardcodes `.png`. HIGH.
2. **Chat Revert crashes** — EditBlock's onRevert calls setMessages, which
   Chat doesn't receive. HIGH.
3. **History lost on stop/crash (non-streaming path)** — only the streaming
   path persists incrementally; headless runs lose everything until success.
   HIGH.
4. **Usage under-counting** — fix-loop retries, compaction summarizer, and
   claim-verification model calls are never billed to the budget cap. HIGH.
5. **No DB migration story** — CREATE TABLE IF NOT EXISTS only;
   delete_session orphans plans rows. HIGH.
6. **Engine.run god-method** (~285 lines): toolset wiring, instruction
   assembly, streaming dispatch, fix-loop, post-processing in one body; 34
   function-level imports dodging circularity. MED but blocks all evolution.
7. **Toolset signature inconsistency** — 10 build_* functions, 5 different
   parameter shapes. MED.
8. **Auth triplicated** in server.py (authorize, run_events inline, run_ws
   variant). MED.
9. **Dual event paths** — engine emits via emit AND on_event separately;
   fix-loop bypasses traced(); worker drain loop can drop/duplicate terminal
   events. MED.
10. **Storage boundary violations** — MemoryStore/SemanticIndex reach into
    db._conn directly. MED.

## Structural recommendations (from the review)

- Toolset registry with a uniform ToolsetContext — kills the deferred-import
  tangle, makes "every feature is wired" testable
- Single typed Emitter (trace + SSE + on_event through one path)
- Split run() into prepare/assemble/execute/post-process over a RunContext
- One run_proc() subprocess helper (7 copies today)
- Incremental persistence in BOTH engine paths; usage recorded per sub-run
- Frontend: useRunStream hook + event reducer replacing the onmessage if-chain

Full detail preserved in the review agent output; prioritized fix list below.

## Fix plan (v0.4.0)

1. **Correctness batch**: image pipeline (worker→engine.run), Chat revert
   crash, delete_session cascades plans/memory, dual-path incremental
   persistence, usage accounting for all sub-runs
2. **Structure batch**: split run() into phases over a RunContext; toolset
   registry with uniform signatures; single Emitter; single run_proc/auth
   helpers; delete exceptions.py shim and dead toolset copies
3. **Frontend batch**: useRunStream/usePoll hooks, event reducer, toasts,
   TSX conversion of Chat/PlanCard/ApprovalCard
4. **Process batch**: user_version migrations, channel reaping, config
   consolidation ([checkpoints] section made real, single documented surface)
