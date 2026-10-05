{"name": "grill-with-docs", "description": "A relentless interview to sharpen a plan or design, which also creates docs (ADR's and glossary) as we go.", "triggers": ["grill with docs", "interview me about", "sharpen the plan", "help me design"]}

# Grill With Docs

A relentless interview to sharpen a plan or design, which also writes the vocabulary and the hard decisions into the repo as you go. Load the `grilling` and `domain-modeling` skills (`load_skill`) — grilling supplies the interview, domain-modeling supplies the writing. Running the interview without loading both is the classic failure: you get an undifferentiated question dump with no paper trail.

Reach for it at the start of a change, in a project, while the plan is still fuzzy and the words for the thing are not settled. It is the single-session planning tool: `wayfinder` is for efforts too big for one session, and `to-spec` takes this session's output next.

## The paper trail

Three things come out of a session, and they are not equal.

| What resolved | Where it lands |
| --- | --- |
| A term: the project's own word for a thing | `CONTEXT.md`, inline, the moment it resolves |
| A decision that is hard to reverse, surprising without context, and a real trade-off | An ADR under `docs/adr/` |
| Everything else you decided | The conversation, and nowhere else |

That third row catches people out. `CONTEXT.md` is a glossary and is deliberately kept as one: no implementation details, no spec, no scratch notes. ADRs are gated on all three conditions at once, so most decisions do not qualify and most sessions produce none. A session that yields a sharper glossary and zero ADRs is working as designed. Hand the conversation to `to-spec` afterwards rather than letting it evaporate.

The glossary is the point: the project's own words, agreed once, so the user, the agent and colleagues stop paying to re-derive them.

## It's working if

- `CONTEXT.md` changes *during* the session, term by term, rather than appearing in one lump at the end.
- The glossary reads as pure vocabulary (tight definitions, `_Avoid_` lists) and contains no implementation detail or spec-like prose.
- Questions the codebase can answer get answered by reading the codebase (a `task` delegation), not asked of the user.
- You get few or no ADRs, and each one is a decision you would be annoyed to have to re-litigate.
- It challenges a word the user used because the existing glossary defines it differently.
