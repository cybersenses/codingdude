# Testing Skills With Subagents

Complete testing methodology for skill authoring. This is the expanded procedure behind the
[SKILL.md](SKILL.md) RED-GREEN-REFACTOR loop: every claim that "agents comply" is backed by a
scenario you actually ran, exactly as code claims are backed by a test you actually ran.

## Why subagents, and what counts as a run

A skill is consumed by an agent that has never met you and will not ask you questions. The only
faithful test of a skill is an agent with no context beyond the skill, given a task that tempts
the failure. In CodingDude that agent is a **`task` delegation** (read-only researcher sub-agent):
its system prompt is the realistic runtime context, the skill body is supplied (or withheld, for
baseline), and the user message is the pressure scenario.

A run counts as evidence only if:

1. The sub-agent had **fresh context** — no conversation history, no hints from you about what
   the rule should be.
2. The scenario was realistic — the task itself would be reasonable work for an agent to attempt.
3. You captured the output verbatim before judging it. Paraphrasing the failure destroys the
   rationalizations you need for the GREEN phase.

## Pressure scenarios

A pressure scenario = a task + a temptation + a consequence-free environment. The agent must be
able to violate the rule *and get away with it* within the scenario, or you are testing your
threat model, not the skill.

**Design rules:**

- Write the scenario BEFORE the skill exists (RED). If you write the skill first, you will
  unconsciously write scenarios the skill already answers.
- The scenario must tempt **this** failure, not a neighboring one. A skill that forbids "claim
  verification without running the check" needs a scenario where claiming is faster than checking.
- Combine pressures for discipline skills — one pressure alone rarely breaks a capable agent.

**Pressure types (combine 3+ for discipline skills):**

| Pressure | Mechanics | Example scenario line |
|---|---|---|
| **Time** | Deadline pressure makes the shortcut the obvious move | "The deploy window closes in 20 minutes." |
| **Sunk cost** | Compliance discards work the agent already produced | "You have already written the full implementation; the test would force a rewrite." |
| **Authority** | A credible voice explicitly requests the violation | "The senior engineer says tests aren't needed for a change this small." |
| **Exhaustion / accumulation** | Many stacked steps make skipping one step invisible | A 14-step checklist where step 9 is the rule under test. |
| **Ambiguity** | The rule's edge cases are plausibly in reach | "The change is 3 lines and arguably 'trivial'." |

**Run the baseline (RED):**

1. Dispatch the sub-agent with the scenario and NO skill. Document verbatim: what it chose, which
   rationalizations it voiced, which pressures triggered the violation.
2. If the baseline **does not fail**, there is nothing to fix — do not author the skill. A skill
   for a failure no agent exhibits is noise that dilutes the library.
3. Harvest the rationalizations. They become the rationalization table and the red-flags list in
   the skill body.

## GREEN: minimal skill, same scenarios

Write the smallest skill that counters the observed rationalizations — no speculative sections
for hypothetical failures you did not observe. Re-run every baseline scenario WITH the skill.
Pass = the agent follows the rule under the same combined pressures.

## REFACTOR: plugging holes systematically

When a re-run finds a violation the skill did not counter:

1. **Classify the failure** using Match the Form to the Failure in SKILL.md — a discipline skip
   needs an explicit prohibition + rationalization row; a wrong-shaped output needs a positive
   recipe; an omitted element needs a required slot in the template; a conditional behavior needs
   a rule keyed to an observable predicate.
2. **Patch one hole per iteration**, re-run the failing scenario, and re-run the previously
   passing scenarios — a hole plugged by adding nuance often reopens the original loophole.
3. **Stop when two consecutive rounds produce no new rationalization.** Beyond that you are
   editing for taste, and every edit risks regressions no scenario covers.

## Micro-testing wording before full scenarios

Full pressure runs are slow and expensive. Cheap word-level checks iterate the wording first:

1. **One fresh-context sample per call** — a single-shot subagent (or raw API call). System prompt
   = the realistic context the guidance will live in (the whole skill or template, not the guidance
   in isolation); user message = the tempting task.
2. **Always include a no-guidance control.** If the control does not exhibit the failure, stop.
3. **5+ reps per variant.** Single samples lie.
4. **Manually read every flagged match.** Template echoes and quoted counter-examples masquerade
   as hits; automated counts alone overstate both failure and success.
5. **Variance is a metric.** Guidance that lands produces converging shapes across reps; five
   different interpretations across five reps means the wording is not binding — tighten the
   form before adding words.

Head-to-head variants (e.g. prohibition form vs recipe form) are decided by running both arms
under identical scenarios and comparing the distributions, not by reading them yourself.

## Meta-testing techniques

**Test the skill's own metadata:** dispatch a routing probe — a realistic request the skill
should catch — with only the skill index visible. If the sub-agent does not pick this skill, the
description's triggers are wrong, and no body improvement will matter.

**Test the description/workflow separation:** if the description summarizes the workflow, agents
may follow the description instead of reading the body. Probe: give the sub-agent the description
alone with a task whose correct behavior differs from the described summary. If it follows the
summary, shorten the description to triggering conditions only.

**Test for reference gaps (reference skills):** three retrieval scenarios — one mainstream case,
one edge case, one deliberately underspecified case. The underspecified case exposes instructions
with gaps: the agent must either find the answer or fail visibly, never silently guess.

## Record the evidence

Every scenario run gets captured next to the skill work: scenario text, sub-agent output
(verbatim), verdict, and date. The skill's Success Signal section states what a compliant run
looks like, so future audits can re-run the same scenarios against the shipped skill instead of
re-arguing the wording from memory.
