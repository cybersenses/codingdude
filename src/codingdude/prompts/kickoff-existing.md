## Kickoff (existing codebase)

This is the first turn of a new session in an existing codebase. Before
addressing the user's request at the end of this message:

1. Read the continuity surfaces: HANDOFF.md, ROADMAP.md, CONTEXT.md, and
   any open project notes. Skim — minutes, not an audit.
2. Confirm a conventions record exists in Memory (`Project conventions:`).
   If it is missing, run the onboarding steps: detect, confirm with the
   user via ask_user, bank with remember().
3. Re-anchor the development contract for this session:
   - Non-trivial work gets a plan and a tracked ticket (in the project's
     declared surface) before any code changes.
   - Behavior changes ship with tests at pre-agreed seams.
   - Verification gates run in this session before any completion claim —
     cite the command, test count, and exit code.
   - Nothing is pushed without the user's explicit consent.
4. Classify the request below: a question or status check takes the light
   path (answer from the surfaces just read); feature or bug work follows
   the full contract above.

Then handle the user's request. Keep the orientation quiet unless something
contradicts it — do not narrate steps 1–3 back at the user.
