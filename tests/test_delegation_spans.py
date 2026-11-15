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
"""R94-A (#345): a delegation's span names the function that ran it.

Every delegation used to be constructed as ``name='delegate'``, so a designer
run and a coder run — possibly on different models — were indistinguishable in
any trace backend. These tests pin the name on the pure helper, prove it is
injective over the function registry, prove the delegate ``Agent`` takes its
name from that helper rather than a literal, and prove the
``DELEGATION_COMPLETED`` event reports the same value so trace and event speak
one vocabulary.
"""

import ast
from pathlib import Path

import pytest
from helpers import agent_call_nodes, scripted
from pydantic_ai.messages import ModelResponse, TextPart

from codingdude.delegation import delegate_span_name
from codingdude.tools import build_delegation_toolset

#: The fixed function registry (functions.py) — the only values the tool
#: accepts, so the only values a span name may be derived from.
FUNCTIONS = ('designer', 'architect', 'coder', 'debugger', 'evaluator', 'researcher')


def _ctx():
    """Synthetic run context: the delegation reads only usage + parent limits."""
    from types import SimpleNamespace

    from pydantic_ai.usage import RunUsage, UsageLimits

    return SimpleNamespace(usage=RunUsage(), usage_limits=UsageLimits())


def test_a_delegation_without_a_function_gets_the_bare_stable_name():
    """Function is optional; its absence must still yield a valid, fixed name."""
    assert delegate_span_name(None) == 'delegate'
    assert delegate_span_name('') == 'delegate'


@pytest.mark.parametrize('function', FUNCTIONS)
def test_each_function_profile_names_its_own_span(function):
    assert delegate_span_name(function) == f'delegate.{function}'


def test_every_function_profile_gets_a_distinct_span_name():
    """The acceptance condition: two delegations with different functions must
    not collapse to one span name."""
    names = {delegate_span_name(f) for f in FUNCTIONS}
    assert len(names) == len(FUNCTIONS)


def test_the_span_name_cannot_carry_unbounded_model_output():
    """Derived from a bounded registry value, never from task text.

    An unbounded string in a span name is unbounded trace cardinality — every
    distinct task would mint a new span name and defeat aggregation.
    """
    wild = delegate_span_name(
        'Designer: please rewrite the whole module ' + 'x' * 500
    )
    assert wild.startswith('delegate.')
    assert len(wild) <= 40
    assert wild == wild.lower()
    assert ' ' not in wild
    assert all(c.isalnum() or c in '._-' for c in wild)


def test_the_delegation_agent_takes_its_name_from_the_span_helper():
    """The helper is only the source of truth if the Agent actually uses it.

    A literal name would leave the helper as dead code and every span unnamed,
    so this checks the data flow, not just the helper's existence: the
    ``name=`` argument must be a direct call to the helper or a variable
    assigned from one.
    """
    import codingdude.tools as tools_module

    tree = ast.parse(Path(tools_module.__file__).read_text(encoding='utf-8'))
    derived = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and ast.unparse(node.value.func).endswith('delegate_span_name')
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    names = [
        ast.unparse(keyword.value)
        for node in agent_call_nodes(tree)
        for keyword in node.keywords
        if keyword.arg == 'name'
    ]
    assert names, 'no Agent(name=...) found in tools.py — guard is blind'
    assert any(
        n in derived or n.startswith('delegate_span_name(') for n in names
    ), f'Agent name comes from nowhere: {names} (derived: {sorted(derived)})'
    assert "'delegate'" not in names, 'the hardcoded span name survived'


async def test_the_completed_event_carries_the_same_span_name(workdir):
    """Trace and event must agree rather than invent two vocabularies."""
    events = []
    toolset = build_delegation_toolset(
        workdir,
        scripted(lambda m, i: ModelResponse(parts=[TextPart(content='done')])),
        emitter=events.append,
        session_id='s1',
    )
    [delegate] = [t for t in toolset.tools.values()]
    await delegate.function(_ctx(), task='look around')
    completed = [e for e in events if e['type'] == 'DELEGATION_COMPLETED']
    assert len(completed) == 1
    assert completed[0]['span'] == delegate_span_name(None)
    # The existing field is unchanged — the new key adds, it does not rename.
    assert completed[0]['function'] is None
