# CodingDude — a personal coding agent.
# Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""DE-7a (#298): the fixed six-function registry — LLM staffing by cognitive
function.

`langs.py` pattern: code-defined, fail-fast, not operator-editable. Each
entry defines a **locked tool policy** and a **prompt overlay**; the
operator configures only **model + thinking** per function
(`[models.functions.<name>]`, parsed in config.py). The policy lock is the
safety property: tuning cost/quality is a config change, changing what a
function may *do* requires a code change here. Delegation sessions can
never gain shell/edit/delegation capability through this registry — the
read-only delegation contract (R13) outranks any entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config


@dataclass(frozen=True)
class FunctionSpec:
    """One cognitive function: locked capability classes, a prompt overlay,
    and the recommended model/thinking setup (documentation, not a mode)."""

    name: str
    # Locked capability classes. 'read'/'analyze' map to the delegation
    # read-only toolset; 'web' adds the web toolset. 'shell', 'edit' and
    # 'delegation' are deliberately absent from every entry: a delegate
    # session must not be able to route around approval tiers (R13).
    tool_policy: tuple[str, ...]
    # Prompt overlay appended to the session instructions for this function.
    overlay: str
    # Recommended setup, shown in the manual and the ModelsConfig panel —
    # guidance, never hidden switching.
    recommended: str


FUNCTIONS: dict[str, FunctionSpec] = {
    'designer': FunctionSpec(
        name='designer',
        tool_policy=('read', 'analyze'),
        overlay=(
            'You are working as the designer: shape the user-facing behavior '
            'before the code. Prefer reading real usage over assuming it; '
            'state the intended interaction, the states it can be in, and '
            'the failure surface. Recommend the smallest design that '
            'satisfies the contract — no speculative features.'
        ),
        recommended='strong model, high thinking — one focused pass per design question',
    ),
    'architect': FunctionSpec(
        name='architect',
        tool_policy=('read', 'analyze'),
        overlay=(
            'You are working as the architect: map the seams before any '
            'implementation. Identify the module that should own the '
            'behavior, its public interface, and every caller and callee it '
            'touches (upstream/downstream impact). Prefer deepening an '
            'existing module and reusing its helpers over adding new ones; '
            'one source of truth per behavior.'
        ),
        recommended='strongest model, max thinking — used rarely, at plan and cross-cutting decisions',
    ),
    'coder': FunctionSpec(
        name='coder',
        tool_policy=('read', 'analyze'),
        overlay=(
            'You are working as the coder: implement exactly the contract '
            'given, matching the codebase\'s existing style and vocabulary. '
            'Reuse named existing helpers; guard clauses and early returns; '
            'no speculative abstractions. Verify the change compiles and the '
            'targeted tests pass before reporting done.'
        ),
        recommended='strong model, medium thinking — the bulk of implementation work',
    ),
    'debugger': FunctionSpec(
        name='debugger',
        tool_policy=('read', 'analyze'),
        overlay=(
            'You are working as the debugger: one hypothesis at a time, '
            'each confirmed or killed by evidence you actually ran (command, '
            'exit code, key output line — cite them). Never fix blind. If a '
            'hypothesis survives two probes unchanged, widen the frame '
            'before the next guess.'
        ),
        recommended='fast model, medium thinking — probe loops where speed matters',
    ),
    'evaluator': FunctionSpec(
        name='evaluator',
        tool_policy=('read', 'analyze'),
        overlay=(
            'You are grading work against its ticket contract, not general '
            'impressions. Functionality first: does the claimed behavior '
            'exist and does the evidence chain (commands, exit codes, key '
            'output lines) actually support it? Cross-check exit codes '
            'against the diff for evidence theater. NEEDS_WORK findings '
            'must name file and symbol; PASS only when the contract is met '
            'AND the evidence holds.'
        ),
        recommended='cheap model, low thinking — many passes, each tightly scoped',
    ),
    'researcher': FunctionSpec(
        name='researcher',
        tool_policy=('read', 'analyze', 'web'),
        overlay=(
            'You are working as the researcher: answer from high-trust '
            'primary sources (official docs, specs) and cite where each '
            'claim came from. Flag contradictions between sources and '
            'confidence levels; never present a guess as a sourced fact.'
        ),
        recommended='cheap model, low thinking — breadth reads, not deep reasoning',
    ),
}


def function_spec(name: str) -> FunctionSpec | None:
    """The registry entry for `name`, or None when it is not one of the six."""
    return FUNCTIONS.get(name)


def resolve_function_config(
    config: Config, name: str,
) -> tuple[str, str | None] | None:
    """(model_name, thinking-config-string) for a cognitive function.

    Resolution chain (explicit -> subagent -> main): an explicit
    `[models.functions.<name>]` entry wins; otherwise the subagent slot
    (falling back to the main slot when unset — both are required fields in
    practice, the fallback is defensive). `thinking` comes from the entry
    when set, else the global lineup thinking. An unknown function returns
    None — callers turn that into a fail-fast at their own boundary (the
    config-load path rejects it outright; the delegate tool raises
    ModelRetry so the agent can correct itself).
    """
    entry = config.models.functions.get(name)
    if entry is not None and entry.model:
        thinking = (
            entry.thinking if entry.thinking else config.models.thinking)
        return entry.model, thinking
    if name not in FUNCTIONS:
        return None
    model = config.models.subagent or config.models.main
    return model, config.models.thinking
